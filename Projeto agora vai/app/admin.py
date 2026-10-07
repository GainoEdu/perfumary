from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, logout_user
from sqlalchemy import func, or_, update

from .auth import start_session
from .extensions import db, limiter
from .models import (Banner, Brand, Category, Family, Order, ORDER_STATUSES, Product, ProductImage, REVENUE_STATUSES,
                     User)
from .settings_def import FIELDS, GROUPS
from .utils import (EMAIL_RE, InvalidImage, delete_media, get_settings, is_safe_url, parse_int, parse_money,
                    password_error, safe_link, save_image, save_settings_group, slugify, unique_slug)

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
def guard():
    """TODAS as rotas /admin/* exigem usuário autenticado + administrador ativo (checado no servidor)."""
    if request.endpoint == "admin.login":
        return None
    if not current_user.is_authenticated:
        return redirect(url_for("admin.login", next=request.path))
    if not (current_user.is_admin and current_user.active):
        abort(403)
    return None


# ---------------- login / logout ----------------
@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("8 per minute; 30 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for("admin.dashboard"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()
        if user and user.is_admin and user.active and user.check_password(password):
            start_session(user)
            nxt = request.args.get("next")
            return redirect(nxt if nxt and is_safe_url(nxt) and nxt.startswith("/admin") else url_for("admin.dashboard"))
        if not user:
            from .auth import _fake_check
            _fake_check(password)
        flash("Credenciais inválidas.", "error")
    return render_template("admin/login.html", title="Entrar no painel")


@bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("admin.login"))


# ---------------- dashboard ----------------
@bp.route("/")
def dashboard():
    revenue = db.session.query(func.coalesce(func.sum(Order.total), 0)).filter(Order.status.in_(REVENUE_STATUSES)).scalar()
    stats = {
        "revenue": revenue,
        "orders": Order.query.count(),
        "pending": Order.query.filter_by(status=ORDER_STATUSES[0]).count(),
        "products": Product.query.count(),
        "customers": User.query.filter_by(is_admin=False).count(),
    }
    low = Product.query.filter(Product.active.is_(True), Product.stock <= Product.min_stock).order_by(Product.stock).limit(8).all()
    recent = Order.query.order_by(Order.created_at.desc()).limit(8).all()
    return render_template("admin/dashboard.html", stats=stats, low=low, recent=recent, title="Dashboard")


# ---------------- produtos ----------------
TEXT_FIELDS = {"short_description": 300, "description": 10000, "sku": 60, "barcode": 60, "manufacturer": 120,
               "origin_country": 80, "volume": 40, "top_notes": 1000, "heart_notes": 1000, "base_notes": 1000,
               "longevity": 80, "projection": 80, "occasion": 120, "gender": 40}
BOOL_FIELDS = ("active", "featured", "bestseller", "promo_active")


def _fk(model, raw):
    i = parse_int(raw)
    return i if i and db.session.get(model, i) else None


def parse_product(form, pid=None):
    """Lista branca de campos (anti mass-assignment). Retorna (valores, erros)."""
    v, errors = {}, []
    v["name"] = (form.get("name") or "").strip()
    if not v["name"] or len(v["name"]) > 200:
        errors.append("Informe o nome do produto (até 200 caracteres).")
    for f, size in TEXT_FIELDS.items():
        v[f] = (form.get(f) or "").strip()[:size] or None
    v["price"] = parse_money(form.get("price"))
    if v["price"] is None or v["price"] <= 0:
        errors.append("Informe um preço válido.")
    raw_promo = (form.get("promo_price") or "").strip()
    v["promo_price"] = parse_money(raw_promo) if raw_promo else None
    if raw_promo and v["promo_price"] is None:
        errors.append("Preço promocional inválido.")
    v["promo_active"] = bool(form.get("promo_active"))
    if v["promo_active"] and (v["promo_price"] is None or (v["price"] is not None and v["promo_price"] >= v["price"])):
        errors.append("Para ativar a promoção, informe um preço promocional menor que o preço normal.")
    v["stock"] = parse_int(form.get("stock"), None, 0, 1_000_000)
    v["min_stock"] = parse_int(form.get("min_stock") or "5", None, 0, 1_000_000)
    if v["stock"] is None or v["min_stock"] is None:
        errors.append("Estoque e estoque mínimo devem ser números inteiros ≥ 0.")
    raw_year = (form.get("launch_year") or "").strip()
    v["launch_year"] = parse_int(raw_year, None, 1700, 2100) if raw_year else None
    if raw_year and v["launch_year"] is None:
        errors.append("Ano de lançamento inválido.")
    v["brand_id"] = _fk(Brand, form.get("brand_id"))
    v["category_id"] = _fk(Category, form.get("category_id"))
    v["family_id"] = _fk(Family, form.get("family_id"))
    for b in ("active", "featured", "bestseller"):
        v[b] = bool(form.get(b))
    if v["sku"] and Product.query.filter(Product.sku == v["sku"], Product.id != (pid or 0)).first():
        errors.append("Já existe outro produto com este SKU.")
    return v, errors


def add_images(product, files):
    limit = current_app.config["MAX_IMAGES_PER_PRODUCT"]
    for f in files:
        if not f or not f.filename:
            continue
        if len(product.images) >= limit:
            flash(f"Limite de {limit} imagens por produto.", "error")
            break
        try:
            media = save_image(f)
        except InvalidImage as e:
            flash(f"{f.filename}: {e}", "error")
            continue
        pos = max([i.position for i in product.images], default=-1) + 1
        has_main = any(i.is_main for i in product.images)
        db.session.add(ProductImage(product=product, media_id=media.id, position=pos, is_main=not has_main))
        db.session.flush()


def product_data(p):
    if request.method == "POST":
        return request.form
    if p is None:
        return {"active": "1", "stock": "0", "min_stock": "5"}
    d = {c: ("" if getattr(p, c) is None else str(getattr(p, c))) for c in
         ("name", "brand_id", "category_id", "family_id", "price", "promo_price", "launch_year", "stock", "min_stock",
          *TEXT_FIELDS)}
    for b in BOOL_FIELDS:
        d[b] = "1" if getattr(p, b) else ""
    return d


@bp.route("/produtos")
def products():
    q = Product.query
    term = (request.args.get("q") or "").strip()[:80]
    if term:
        like = "%" + term.replace("%", r"\%").replace("_", r"\_") + "%"
        q = q.filter(or_(Product.name.ilike(like, escape="\\"), Product.sku.ilike(like, escape="\\")))
    page = request.args.get("page", 1, type=int)
    pagination = q.order_by(Product.created_at.desc()).paginate(page=max(page, 1), per_page=20, error_out=False)
    return render_template("admin/products.html", pagination=pagination, term=term, title="Produtos")


@bp.route("/produtos/novo", methods=["GET", "POST"])
@bp.route("/produtos/<int:pid>/editar", methods=["GET", "POST"])
def product_form(pid=None):
    p = db.get_or_404(Product, pid) if pid else None
    if request.method == "POST":
        vals, errors = parse_product(request.form, pid)
        if not errors:
            if p is None:
                p = Product(slug=unique_slug(Product, vals["name"]), **vals)
                db.session.add(p)
            else:
                for k, val in vals.items():
                    setattr(p, k, val)
            db.session.flush()
            add_images(p, request.files.getlist("images"))
            db.session.commit()
            flash("Produto salvo.", "success")
            return redirect(url_for("admin.product_form", pid=p.id))
        for e in errors:
            flash(e, "error")
    return render_template("admin/product_form.html", p=p, data=product_data(p), brands=Brand.query.order_by(Brand.name).all(),
                           categories=Category.query.order_by(Category.name).all(),
                           families=Family.query.order_by(Family.name).all(),
                           title="Editar produto" if p else "Novo produto")


@bp.post("/produtos/<int:pid>/excluir")
def product_delete(pid):
    p = db.get_or_404(Product, pid)
    media_ids = [i.media_id for i in p.images]
    db.session.delete(p)
    db.session.flush()
    for mid in media_ids:
        delete_media(mid)
    db.session.commit()
    flash("Produto excluído.", "success")
    return redirect(url_for("admin.products"))


@bp.post("/imagens/<int:iid>/<action>")
def image_action(iid, action):
    img = db.get_or_404(ProductImage, iid)
    product = img.product
    imgs = list(product.images)
    if action == "excluir":
        was_main = img.is_main
        imgs.remove(img)
        mid = img.media_id
        db.session.delete(img)
        db.session.flush()
        delete_media(mid)
        if was_main and imgs:
            imgs[0].is_main = True
    elif action == "principal":
        for i in imgs:
            i.is_main = i.id == img.id
    elif action in ("subir", "descer"):
        idx = imgs.index(img)
        j = idx - 1 if action == "subir" else idx + 1
        if 0 <= j < len(imgs):
            imgs[idx], imgs[j] = imgs[j], imgs[idx]
        for pos, i in enumerate(imgs):
            i.position = pos
    else:
        abort(404)
    db.session.commit()
    return redirect(url_for("admin.product_form", pid=product.id))


# ---------------- marcas / categorias / famílias ----------------
KINDS = {
    "marcas": {"model": Brand, "title": "Marcas", "singular": "Marca", "fk": Product.brand_id, "logo": True},
    "categorias": {"model": Category, "title": "Categorias", "singular": "Categoria", "fk": Product.category_id, "logo": False},
    "familias": {"model": Family, "title": "Famílias olfativas", "singular": "Família olfativa", "fk": Product.family_id, "logo": False},
}
KIND_CONVERTER = "<any(marcas,categorias,familias):kind>"


@bp.route(f"/{KIND_CONVERTER}")
def taxonomy_list(kind):
    k = KINDS[kind]
    items = k["model"].query.order_by(k["model"].name).all()
    counts = dict(db.session.query(k["fk"], func.count(Product.id)).group_by(k["fk"]).all())
    return render_template("admin/taxonomy_list.html", kind=kind, k=k, items=items, counts=counts, title=k["title"])


@bp.route(f"/{KIND_CONVERTER}/novo", methods=["GET", "POST"])
@bp.route(f"/{KIND_CONVERTER}/<int:tid>/editar", methods=["GET", "POST"])
def taxonomy_form(kind, tid=None):
    k = KINDS[kind]
    model = k["model"]
    item = db.get_or_404(model, tid) if tid else None
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        slug = slugify(request.form.get("slug") or name)
        errors = []
        if not name or len(name) > 120:
            errors.append("Informe o nome (até 120 caracteres).")
        if model.query.filter(func.lower(model.name) == name.lower(), model.id != (tid or 0)).first():
            errors.append("Já existe um registro com este nome.")
        if model.query.filter(model.slug == slug, model.id != (tid or 0)).first():
            errors.append("Já existe um registro com este slug.")
        if not errors:
            if item is None:
                item = model(name=name, slug=slug)
                db.session.add(item)
            item.name, item.slug = name, slug
            item.description = (request.form.get("description") or "").strip()[:2000] or None
            item.active = bool(request.form.get("active"))
            if k["logo"]:
                f = request.files.get("logo")
                try:
                    if f and f.filename:
                        old = item.logo_media_id
                        item.logo_media_id = save_image(f, 600).id
                        delete_media(old)
                    elif request.form.get("logo__remove"):
                        delete_media(item.logo_media_id)
                        item.logo_media_id = None
                except InvalidImage as e:
                    flash(f"Logo: {e}", "error")
            db.session.commit()
            flash(f"{k['singular']} salva(o).", "success")
            return redirect(url_for("admin.taxonomy_list", kind=kind))
        for e in errors:
            flash(e, "error")
    data = request.form if request.method == "POST" else (
        {"name": item.name, "slug": item.slug, "description": item.description or "", "active": "1" if item.active else ""}
        if item else {"active": "1"})
    return render_template("admin/taxonomy_form.html", kind=kind, k=k, item=item, data=data,
                           title=("Editar " if item else "Nova(o) ") + k["singular"].lower())


@bp.post(f"/{KIND_CONVERTER}/<int:tid>/excluir")
def taxonomy_delete(kind, tid):
    k = KINDS[kind]
    item = db.get_or_404(k["model"], tid)
    db.session.execute(update(Product).where(k["fk"] == tid).values({k["fk"].key: None}))
    if k["logo"]:
        delete_media(item.logo_media_id)
    db.session.delete(item)
    db.session.commit()
    flash("Registro excluído. Os produtos vinculados ficaram sem este vínculo.", "success")
    return redirect(url_for("admin.taxonomy_list", kind=kind))


# ---------------- estoque ----------------
@bp.route("/estoque")
def stock():
    q = Product.query
    term = (request.args.get("q") or "").strip()[:80]
    if term:
        like = "%" + term.replace("%", r"\%").replace("_", r"\_") + "%"
        q = q.filter(or_(Product.name.ilike(like, escape="\\"), Product.sku.ilike(like, escape="\\")))
    if request.args.get("baixo") == "1":
        q = q.filter(Product.stock <= Product.min_stock)
    page = request.args.get("page", 1, type=int)
    pagination = q.order_by(Product.stock.asc(), Product.name).paginate(page=max(page, 1), per_page=30, error_out=False)
    return render_template("admin/stock.html", pagination=pagination, term=term, low=request.args.get("baixo") == "1", title="Estoque")


@bp.post("/estoque/<int:pid>")
def stock_update(pid):
    p = db.get_or_404(Product, pid)
    stock_v = parse_int(request.form.get("stock"), None, 0, 1_000_000)
    min_v = parse_int(request.form.get("min_stock"), None, 0, 1_000_000)
    if stock_v is None or min_v is None:
        flash("Valores inválidos.", "error")
    else:
        p.stock, p.min_stock = stock_v, min_v
        db.session.commit()
        flash(f"Estoque de “{p.name}” atualizado.", "success")
    nxt = request.form.get("next")
    return redirect(nxt if nxt and is_safe_url(nxt) else url_for("admin.stock"))


# ---------------- pedidos ----------------
@bp.route("/pedidos")
def orders():
    q = Order.query
    term = (request.args.get("q") or "").strip()[:80]
    status = request.args.get("status") or ""
    if term:
        like = "%" + term.replace("%", r"\%").replace("_", r"\_") + "%"
        q = q.filter(or_(Order.number.ilike(like, escape="\\"), Order.customer_name.ilike(like, escape="\\"),
                         Order.email.ilike(like, escape="\\"), Order.cpf.ilike(like, escape="\\")))
    if status in ORDER_STATUSES:
        q = q.filter(Order.status == status)
    page = request.args.get("page", 1, type=int)
    pagination = q.order_by(Order.created_at.desc()).paginate(page=max(page, 1), per_page=20, error_out=False)
    return render_template("admin/orders.html", pagination=pagination, term=term, status=status, statuses=ORDER_STATUSES,
                           title="Pedidos")


@bp.route("/pedidos/<int:oid>")
def order_detail(oid):
    order = db.get_or_404(Order, oid)
    return render_template("admin/order_detail.html", order=order, statuses=ORDER_STATUSES, title=f"Pedido {order.number}")


@bp.post("/pedidos/<int:oid>/status")
def order_status(oid):
    order = db.get_or_404(Order, oid)
    new = request.form.get("status")
    if new not in ORDER_STATUSES:
        flash("Status inválido.", "error")
    elif order.status == "Cancelado" and new != "Cancelado":
        flash("Pedido cancelado não pode ser reaberto.", "error")
    else:
        if new == "Cancelado" and order.status != "Cancelado":
            for it in order.items:  # devolve ao estoque
                if it.product_id:
                    db.session.execute(update(Product).where(Product.id == it.product_id)
                                       .values(stock=Product.stock + it.quantity))
        order.status = new
        db.session.commit()
        flash("Status atualizado.", "success")
    return redirect(url_for("admin.order_detail", oid=oid))


# ---------------- clientes ----------------
@bp.route("/clientes")
def customers():
    q = db.session.query(User, func.count(Order.id)).outerjoin(Order, Order.user_id == User.id).filter(User.is_admin.is_(False))
    term = (request.args.get("q") or "").strip()[:80]
    if term:
        like = "%" + term.replace("%", r"\%").replace("_", r"\_") + "%"
        q = q.filter(or_(User.name.ilike(like, escape="\\"), User.email.ilike(like, escape="\\")))
    page = request.args.get("page", 1, type=int)
    pagination = q.group_by(User.id).order_by(User.created_at.desc()).paginate(page=max(page, 1), per_page=25, error_out=False)
    return render_template("admin/customers.html", pagination=pagination, term=term, title="Clientes")


@bp.post("/clientes/<int:uid>/alternar")
def customer_toggle(uid):
    u = db.get_or_404(User, uid)
    if u.is_admin:
        abort(403)
    u.active = not u.active
    db.session.commit()
    flash("Cliente ativado." if u.active else "Cliente bloqueado.", "success")
    return redirect(url_for("admin.customers"))


# ---------------- banners ----------------
@bp.route("/banners")
def banners():
    return render_template("admin/banners.html", items=Banner.query.order_by(Banner.position, Banner.id).all(), title="Banners")


@bp.route("/banners/novo", methods=["GET", "POST"])
@bp.route("/banners/<int:bid>/editar", methods=["GET", "POST"])
def banner_form(bid=None):
    b = db.get_or_404(Banner, bid) if bid else None
    if request.method == "POST":
        f = request.form
        title = (f.get("title") or "").strip()[:160]
        if not title:
            flash("Informe o título.", "error")
        else:
            if b is None:
                b = Banner(title=title)
                db.session.add(b)
            b.title = title
            b.subtitle = (f.get("subtitle") or "").strip()[:300] or None
            b.button_text = (f.get("button_text") or "").strip()[:60] or None
            b.link = safe_link(f.get("link")) if (f.get("link") or "").strip() else None
            b.position = parse_int(f.get("position"), 0, 0, 9999)
            b.active = bool(f.get("active"))
            file = request.files.get("image")
            try:
                if file and file.filename:
                    old = b.media_id
                    b.media_id = save_image(file).id
                    delete_media(old)
                elif f.get("image__remove"):
                    delete_media(b.media_id)
                    b.media_id = None
            except InvalidImage as e:
                flash(f"Imagem: {e}", "error")
            db.session.commit()
            flash("Banner salvo.", "success")
            return redirect(url_for("admin.banners"))
    data = request.form if request.method == "POST" else (
        {"title": b.title, "subtitle": b.subtitle or "", "button_text": b.button_text or "", "link": b.link or "",
         "position": str(b.position), "active": "1" if b.active else ""} if b else {"active": "1", "position": "0"})
    return render_template("admin/banner_form.html", b=b, data=data, title="Editar banner" if b else "Novo banner")


@bp.post("/banners/<int:bid>/excluir")
def banner_delete(bid):
    b = db.get_or_404(Banner, bid)
    delete_media(b.media_id)
    db.session.delete(b)
    db.session.commit()
    flash("Banner excluído.", "success")
    return redirect(url_for("admin.banners"))


# ---------------- homepage / aparência / configurações ----------------
def _settings_page(group, title, intro=""):
    keys = [k for _, ks in GROUPS[group] for k in ks]
    if request.method == "POST":
        errors = save_settings_group(keys, request.form, request.files)
        db.session.commit()
        for e in errors:
            flash(e, "error")
        if not errors:
            flash("Alterações salvas.", "success")
        return redirect(request.path)
    s = get_settings()
    sections = [(h, [{"key": k, "label": FIELDS[k][0], "type": FIELDS[k][1], "help": FIELDS[k][3], "value": s.get(k, "")}
                     for k in ks]) for h, ks in GROUPS[group]]
    return render_template("admin/settings.html", sections=sections, title=title, intro=intro, group=group)


@bp.route("/homepage", methods=["GET", "POST"])
def homepage():
    return _settings_page("homepage", "Página inicial")


@bp.route("/aparencia", methods=["GET", "POST"])
def appearance():
    return _settings_page("appearance", "Aparência")


@bp.route("/configuracoes", methods=["GET", "POST"])
def settings():
    return _settings_page("store", "Configurações da loja")


# ---------------- conta do administrador ----------------
@bp.route("/conta", methods=["GET", "POST"])
def account():
    if request.method == "POST":
        if request.form.get("action") == "profile":
            name = (request.form.get("name") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            if len(name) < 2 or not EMAIL_RE.match(email):
                flash("Verifique nome e e-mail.", "error")
            elif User.query.filter(User.email == email, User.id != current_user.id).first():
                flash("Este e-mail já está em uso.", "error")
            else:
                current_user.name, current_user.email = name, email
                db.session.commit()
                flash("Dados atualizados.", "success")
        else:
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
        return redirect(url_for("admin.account"))
    return render_template("admin/account.html", title="Minha conta")
