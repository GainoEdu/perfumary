from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .extensions import db, limiter
from .models import Order, User
from .utils import EMAIL_RE, is_safe_url, only_digits, password_error

bp = Blueprint("auth", __name__)


def start_session(user):
    """Renova a sessão no login (evita session fixation), preservando só o carrinho."""
    cart = session.get("cart")
    session.clear()
    if cart:
        session["cart"] = cart
    login_user(user)
    session.permanent = True


def _fake_check(password):
    from werkzeug.security import check_password_hash, generate_password_hash
    check_password_hash(generate_password_hash("dummy-password"), password or "")  # tempo constante


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 40 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.account"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()
        if user and user.active and user.check_password(password):
            start_session(user)
            nxt = request.args.get("next")
            if user.is_admin and not nxt:
                return redirect(url_for("admin.dashboard"))
            return redirect(nxt if nxt and is_safe_url(nxt) else url_for("auth.account"))
        if not user:
            _fake_check(password)
        flash("E-mail ou senha incorretos.", "error")
    return render_template("login.html", title="Entrar")


@bp.route("/cadastro", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("auth.account"))
    form = {}
    if request.method == "POST":
        form = request.form
        name = (form.get("name") or "").strip()
        email = (form.get("email") or "").strip().lower()
        phone = only_digits(form.get("phone"))
        password = form.get("password") or ""
        errors = []
        if len(name) < 3 or len(name) > 120:
            errors.append("Informe seu nome completo.")
        if not EMAIL_RE.match(email) or len(email) > 255:
            errors.append("E-mail inválido.")
        if len(phone) not in (10, 11):
            errors.append("Telefone inválido (DDD + número).")
        if password != form.get("password2"):
            errors.append("As senhas não conferem.")
        pe = password_error(password)
        if pe:
            errors.append(pe)
        if not errors and User.query.filter_by(email=email).first():
            errors.append("Este e-mail já está cadastrado.")
        if not errors:
            user = User(name=name, email=email, phone=phone, is_admin=False, active=True)  # is_admin nunca vem do form
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            start_session(user)
            flash("Cadastro realizado com sucesso!", "success")
            nxt = request.args.get("next")
            return redirect(nxt if nxt and is_safe_url(nxt) else url_for("auth.account"))
        for e in errors:
            flash(e, "error")
    return render_template("register.html", form=form, title="Criar conta")


@bp.post("/logout")
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("shop.index"))


@bp.route("/minha-conta", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "profile":
            name = (request.form.get("name") or "").strip()
            phone = only_digits(request.form.get("phone"))
            if len(name) < 3 or len(name) > 120 or len(phone) not in (10, 11):
                flash("Verifique nome e telefone.", "error")
            else:
                current_user.name, current_user.phone = name, phone
                db.session.commit()
                flash("Dados atualizados.", "success")
        elif action == "password":
            new = request.form.get("new_password") or ""
            if not current_user.check_password(request.form.get("current_password") or ""):
                flash("Senha atual incorreta.", "error")
            elif password_error(new):
                flash(password_error(new), "error")
            elif new != request.form.get("new_password2"):
                flash("As senhas não conferem.", "error")
            else:
                current_user.set_password(new)
                db.session.commit()
                flash("Senha alterada.", "success")
        return redirect(url_for("auth.account"))
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template("account.html", orders=orders, title="Minha conta")


@bp.route("/minha-conta/pedidos/<number>")
@login_required
def order_detail(number):
    # filtra por user_id: um cliente nunca vê o pedido de outro (anti-IDOR)
    order = Order.query.filter_by(number=number, user_id=current_user.id).first_or_404()
    return render_template("order_detail.html", order=order, title=f"Pedido {order.number}")
