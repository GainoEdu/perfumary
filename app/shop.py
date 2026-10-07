import io
import re

from flask import Blueprint, Response, abort, render_template, request, send_file, url_for
from sqlalchemy import and_, case, or_
from sqlalchemy.orm import joinedload, selectinload

from .extensions import db, limiter
from .models import Banner, Brand, Category, Family, Media, Product
from .utils import get_settings, only_digits

bp = Blueprint("shop", __name__)
PER_PAGE = 12


def visible():
    return Product.query.options(selectinload(Product.images), joinedload(Product.brand)).filter(Product.active.is_(True))


def _section(flag, query_fn, limit=8):
    return query_fn().limit(limit).all() if get_settings().get(flag) == "1" else []


@bp.route("/")
def index():
    s = get_settings()
    on = lambda k: s.get(k) == "1"
    ctx = {
        "banners": Banner.query.filter_by(active=True).order_by(Banner.position, Banner.id).all() if on("show_banners") else [],
        "featured": _section("show_featured", lambda: visible().filter(Product.featured.is_(True)).order_by(Product.created_at.desc())),
        "bestsellers": _section("show_bestsellers", lambda: visible().filter(Product.bestseller.is_(True)).order_by(Product.created_at.desc())),
        "offers": _section("show_offers", lambda: visible().filter(Product.promo_active.is_(True), Product.promo_price.isnot(None))),
        "new": _section("show_new", lambda: visible().order_by(Product.created_at.desc())),
        "brands": _section("show_brands", lambda: Brand.query.filter_by(active=True).order_by(Brand.name), 12),
        "categories": _section("show_categories", lambda: Category.query.filter_by(active=True).order_by(Category.name), 12),
    }
    return render_template("index.html", title=s["store_name"], description=s["seo_description"], **ctx)


def _like(term):
    return "%" + term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


@bp.route("/produtos")
def products():
    q = visible()
    a = request.args
    term = (a.get("q") or "").strip()[:80]
    if term:
        like = _like(term)
        q = q.filter(or_(Product.name.ilike(like, escape="\\"), Product.short_description.ilike(like, escape="\\"),
                         Product.top_notes.ilike(like, escape="\\"), Product.heart_notes.ilike(like, escape="\\"),
                         Product.base_notes.ilike(like, escape="\\"),
                         Product.brand.has(Brand.name.ilike(like, escape="\\"))))
    current = {}
    for arg, model, col in (("marca", Brand, Product.brand_id), ("categoria", Category, Product.category_id),
                            ("familia", Family, Product.family_id)):
        slug = a.get(arg)
        if slug:
            obj = model.query.filter_by(slug=slug).first()
            current[arg] = obj
            q = q.filter(col == (obj.id if obj else -1))
    gender = (a.get("genero") or "").strip()[:40]
    if gender:
        q = q.filter(Product.gender == gender)
    if a.get("promo") == "1":
        q = q.filter(Product.promo_active.is_(True), Product.promo_price.isnot(None))
    price = case((and_(Product.promo_active.is_(True), Product.promo_price.isnot(None)), Product.promo_price),
                 else_=Product.price)
    order = a.get("ordem", "novos")
    q = q.order_by({"menor": price.asc(), "maior": price.desc(), "nome": Product.name.asc()}.get(order, Product.created_at.desc()))
    page = request.args.get("page", 1, type=int)
    pagination = q.paginate(page=max(page, 1), per_page=PER_PAGE, error_out=False)
    genders = [g[0] for g in db.session.query(Product.gender).filter(Product.active.is_(True), Product.gender.isnot(None))
               .distinct().order_by(Product.gender).all() if g[0]]
    return render_template(
        "products.html", pagination=pagination, term=term, current=current, order=order, gender=gender, genders=genders,
        brands=Brand.query.filter_by(active=True).order_by(Brand.name).all(),
        categories=Category.query.filter_by(active=True).order_by(Category.name).all(),
        families=Family.query.filter_by(active=True).order_by(Family.name).all(), title="Perfumes",
    )


@bp.route("/produto/<slug>")
def product(slug):
    p = visible().filter_by(slug=slug).first_or_404()
    related = visible().filter(Product.id != p.id, or_(Product.brand_id == p.brand_id, Product.category_id == p.category_id)).limit(4).all()
    desc = p.short_description or (p.description or "")[:150]
    og = url_for("shop.media", media_id=p.main_image.media_id, _external=True) if p.main_image else None
    return render_template("product.html", p=p, related=related, title=p.name, description=desc, og_image=og)


@bp.route("/media/<int:media_id>")
@limiter.exempt
def media(media_id):
    m = db.session.get(Media, media_id)
    if not m or m.mimetype not in ("image/jpeg", "image/png", "image/webp"):
        abort(404)
    return send_file(io.BytesIO(m.data), mimetype=m.mimetype, max_age=31536000, etag=str(m.id))


@bp.route("/theme.css")
@limiter.exempt
def theme():
    s = get_settings()
    default = {"color_primary": "#b8923a", "color_secondary": "#111111", "color_button": "#111111",
               "color_button_text": "#ffffff", "color_bg": "#faf6ef", "color_text": "#1b1b1b"}
    v = {k: (s[k] if re.match(r"^#[0-9a-fA-F]{6}$", s.get(k) or "") else d) for k, d in default.items()}
    css = (":root{--primary:%(color_primary)s;--secondary:%(color_secondary)s;--btn:%(color_button)s;"
           "--btn-text:%(color_button_text)s;--bg:%(color_bg)s;--text:%(color_text)s}" % v)
    return Response(css, mimetype="text/css", headers={"Cache-Control": "public, max-age=60"})


@bp.route("/healthz")
@limiter.exempt
def healthz():
    return "ok"


@bp.route("/robots.txt")
@limiter.exempt
def robots():
    body = ("User-agent: *\nDisallow: /admin\nDisallow: /carrinho\nDisallow: /checkout\nDisallow: /minha-conta\n"
            f"Sitemap: {url_for('shop.sitemap', _external=True)}\n")
    return Response(body, mimetype="text/plain")


@bp.route("/sitemap.xml")
@limiter.exempt
def sitemap():
    urls = [url_for("shop.index", _external=True), url_for("shop.products", _external=True)]
    urls += [url_for("shop.product", slug=p.slug, _external=True) for p in visible().with_entities(Product.slug).all()]
    xml = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")
    return Response(xml, mimetype="application/xml")
