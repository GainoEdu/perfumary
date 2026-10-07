from decimal import Decimal

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import update

from .extensions import db, limiter
from .models import Order, OrderItem, Product
from .payments import get_gateway
from .utils import EMAIL_RE, UFS, get_settings, is_safe_url, only_digits, parse_money, valid_cpf
import secrets
from datetime import datetime

bp = Blueprint("cart", __name__)
MAX_QTY = 20


class OrderError(Exception):
    pass


# ---------- carrinho (sessão guarda só id -> quantidade; preço vem SEMPRE do banco) ----------
def read_cart():
    cart = session.get("cart")
    clean = {}
    if isinstance(cart, dict):
        for k, v in cart.items():
            if str(k).isdigit() and isinstance(v, int) and v > 0:
                clean[str(k)] = min(v, MAX_QTY)
    return clean


def write_cart(cart):
    session["cart"] = cart
    session.modified = True


def cart_count():
    try:
        return sum(read_cart().values())
    except Exception:
        return 0


def cart_items():
    """Retorna (itens, subtotal) já validados contra o banco (ativo, estoque, preço real)."""
    cart = read_cart()
    ids = [int(k) for k in cart]
    products = {}
    if ids:
        products = {p.id: p for p in Product.query.filter(Product.id.in_(ids), Product.active.is_(True)).all()}
    items, subtotal, new_cart, changed = [], Decimal("0.00"), {}, False
    for k, qty in cart.items():
        p = products.get(int(k))
        if not p or p.stock <= 0:
            changed = True
            continue
        if qty > p.stock:
            qty, changed = p.stock, True
        line = p.current_price * qty
        items.append({"product": p, "qty": qty, "line_total": line})
        subtotal += line
        new_cart[k] = qty
    if changed:
        g.cart_adjusted = True
        write_cart(new_cart)
        flash("Seu carrinho foi ajustado conforme a disponibilidade de estoque.", "info")
    return items, subtotal


def calc_totals(subtotal):
    s = get_settings()
    flat = parse_money(s.get("shipping_flat")) or Decimal("0.00")
    free_above = parse_money(s.get("free_shipping_above")) or Decimal("0.00")
    shipping = Decimal("0.00") if (free_above > 0 and subtotal >= free_above) or subtotal == 0 else flat
    discount = Decimal("0.00")
    return shipping, discount, subtotal + shipping - discount


def _back(default="cart.view"):
    nxt = request.form.get("next")
    return redirect(nxt if nxt and is_safe_url(nxt) else url_for(default))


@bp.route("/carrinho")
def view():
    items, subtotal = cart_items()
    shipping, discount, total = calc_totals(subtotal)
    return render_template("cart.html", items=items, subtotal=subtotal, shipping=shipping, discount=discount, total=total,
                           title="Carrinho")


@bp.post("/carrinho/adicionar/<int:product_id>")
@limiter.limit("60 per minute")
def add(product_id):
    p = Product.query.filter_by(id=product_id, active=True).first_or_404()
    qty = request.form.get("qty", type=int) or 1
    qty = max(1, min(qty, MAX_QTY))
    cart = read_cart()
    current = cart.get(str(p.id), 0)
    if p.stock <= 0:
        flash("Produto esgotado.", "error")
        return _back()
    new_qty = min(current + qty, p.stock, MAX_QTY)
    if current + qty > new_qty:
        flash(f"Quantidade limitada ao estoque disponível ({p.stock}).", "info")
    cart[str(p.id)] = new_qty
    write_cart(cart)
    flash("Produto adicionado ao carrinho.", "success")
    return redirect(url_for("cart.view"))


@bp.post("/carrinho/atualizar/<int:product_id>")
def update_qty(product_id):
    cart = read_cart()
    qty = request.form.get("qty", type=int)
    if str(product_id) in cart and qty is not None:
        if qty <= 0:
            cart.pop(str(product_id))
        else:
            p = Product.query.filter_by(id=product_id, active=True).first()
            cart[str(product_id)] = max(1, min(qty, MAX_QTY, p.stock if p else 1))
        write_cart(cart)
    return redirect(url_for("cart.view"))


@bp.post("/carrinho/remover/<int:product_id>")
def remove(product_id):
    cart = read_cart()
    cart.pop(str(product_id), None)
    write_cart(cart)
    return redirect(url_for("cart.view"))


@bp.post("/carrinho/limpar")
def clear():
    write_cart({})
    return redirect(url_for("cart.view"))


# ---------- checkout ----------
def validate_checkout(form):
    d = {k: (form.get(k) or "").strip() for k in
         ("name", "cpf", "phone", "email", "zip_code", "state", "city", "neighborhood", "street", "street_number", "complement")}
    errors = []
    if len(d["name"]) < 3 or len(d["name"]) > 120:
        errors.append("Informe seu nome completo.")
    if not valid_cpf(d["cpf"]):
        errors.append("CPF inválido.")
    if len(only_digits(d["phone"])) not in (10, 11):
        errors.append("Telefone inválido (informe DDD + número).")
    if not EMAIL_RE.match(d["email"]) or len(d["email"]) > 255:
        errors.append("E-mail inválido.")
    if len(only_digits(d["zip_code"])) != 8:
        errors.append("CEP inválido.")
    if d["state"].upper() not in UFS:
        errors.append("Selecione o estado.")
    for key, label, size in (("city", "cidade", 100), ("neighborhood", "bairro", 100), ("street", "rua", 150),
                             ("street_number", "número", 20)):
        if not d[key] or len(d[key]) > size:
            errors.append(f"Informe a {label}." if key != "street_number" else "Informe o número.")
    if len(d["complement"]) > 100:
        errors.append("Complemento muito longo.")
    d["state"] = d["state"].upper()
    d["cpf"] = only_digits(d["cpf"])
    d["zip_code"] = only_digits(d["zip_code"])
    d["phone"] = only_digits(d["phone"])
    return d, errors


def new_order_number():
    while True:
        n = f"{datetime.now():%y%m%d}-{secrets.token_hex(3).upper()}"
        if not Order.query.filter_by(number=n).first():
            return n


def create_order(user, data):
    """Cria o pedido em UMA transação, com preços e estoque lidos/atualizados no banco."""
    cart = read_cart()
    if not cart:
        raise OrderError("Seu carrinho está vazio.")
    products = {p.id: p for p in Product.query.filter(Product.id.in_([int(k) for k in cart]), Product.active.is_(True))
                .order_by(Product.id).all()}
    order = Order(number=new_order_number(), user_id=user.id, customer_name=data["name"], cpf=data["cpf"],
                  phone=data["phone"], email=data["email"], zip_code=data["zip_code"], state=data["state"],
                  city=data["city"], neighborhood=data["neighborhood"], street=data["street"],
                  street_number=data["street_number"], complement=data["complement"] or None,
                  subtotal=0, shipping=0, discount=0, total=0)
    subtotal = Decimal("0.00")
    try:
        for k in sorted(cart, key=int):
            qty, p = cart[k], products.get(int(k))
            if not p:
                raise OrderError("Um dos produtos não está mais disponível.")
            # baixa de estoque atômica: só funciona se ainda houver quantidade suficiente
            res = db.session.execute(
                update(Product).where(Product.id == p.id, Product.stock >= qty, Product.active.is_(True))
                .values(stock=Product.stock - qty))
            if res.rowcount != 1:
                raise OrderError(f"Estoque insuficiente para “{p.name}”.")
            line = p.current_price * qty
            subtotal += line
            order.items.append(OrderItem(product_id=p.id, name=p.name, sku=p.sku, unit_price=p.current_price,
                                         quantity=qty, line_total=line))
        shipping, discount, total = calc_totals(subtotal)
        order.subtotal, order.shipping, order.discount, order.total = subtotal, shipping, discount, total
        db.session.add(order)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return order


@bp.route("/checkout", methods=["GET", "POST"])
@login_required
@limiter.limit("20 per minute", methods=["POST"])
def checkout():
    items, subtotal = cart_items()
    if not items:
        flash("Seu carrinho está vazio.", "info")
        return redirect(url_for("cart.view"))
    if request.method == "POST" and g.get("cart_adjusted"):
        flash("O estoque mudou e seu carrinho foi ajustado. Revise antes de confirmar.", "error")
        return redirect(url_for("cart.view"))
    shipping, discount, total = calc_totals(subtotal)
    form = {"name": current_user.name, "email": current_user.email, "phone": current_user.phone or ""}
    if request.method == "POST":
        data, errors = validate_checkout(request.form)
        form = request.form
        if not errors:
            try:
                order = create_order(current_user, data)
            except OrderError as e:
                errors.append(str(e))
            else:
                write_cart({})
                url = get_gateway().create_payment(order)
                flash("Pedido realizado com sucesso!", "success")
                return redirect(url or url_for("auth.order_detail", number=order.number))
        for e in errors:
            flash(e, "error")
    return render_template("checkout.html", items=items, subtotal=subtotal, shipping=shipping, discount=discount,
                           total=total, form=form, ufs=UFS, title="Finalizar pedido")
