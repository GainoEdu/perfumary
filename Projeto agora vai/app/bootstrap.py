"""Inicialização automática: banco, migrations, dados iniciais e administrador."""
import logging
import os
import secrets
import time

from flask_migrate import upgrade
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from .extensions import db
from .models import Brand, Category, Family, Product, Setting, User
from .utils import slugify

log = logging.getLogger("bootstrap")
MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")
LOCK_KEY = 726354188

CATEGORIES = ["Feminino", "Masculino", "Unissex", "Infantil", "Body Splash", "Eau de Parfum", "Eau de Toilette", "Deo Colônia"]
FAMILIES = ["Floral", "Amadeirado", "Cítrico", "Frutado", "Gourmand", "Oriental", "Aquático", "Aromático"]
BRANDS = ["O Boticário", "Natura", "Eudora", "Avon", "Dior", "Chanel", "Carolina Herrera", "Lancôme", "Maison Demo"]
DEMO_PRODUCTS = [
    ("Noir Absolu (demonstração)", "Maison Demo", "Eau de Parfum", "Amadeirado", "100 ml", "389.90", "329.90", True, "Unissex"),
    ("Fleur de Lune (demonstração)", "Maison Demo", "Feminino", "Floral", "50 ml", "259.90", None, False, "Feminino"),
    ("Citrus Vert (demonstração)", "Maison Demo", "Eau de Toilette", "Cítrico", "75 ml", "199.90", None, False, "Masculino"),
    ("Ambre Doré (demonstração)", "Maison Demo", "Eau de Parfum", "Oriental", "100 ml", "449.90", "399.90", True, "Unissex"),
]


def _wait_for_db(retries=15, delay=3):
    for attempt in range(1, retries + 1):
        try:
            db.session.execute(text("SELECT 1"))
            return
        except OperationalError as exc:
            db.session.rollback()
            log.warning("Aguardando banco (%s/%s): %s", attempt, retries, str(exc).splitlines()[0])
            time.sleep(delay)
    raise RuntimeError("Não foi possível conectar ao banco de dados.")


def seed_initial_data():
    """Dados de demonstração. Rodam UMA vez; se o admin apagar, não voltam."""
    if db.session.get(Setting, "seed_done"):
        return
    from decimal import Decimal
    for name in CATEGORIES:
        db.session.add(Category(name=name, slug=slugify(name)))
    for name in FAMILIES:
        db.session.add(Family(name=name, slug=slugify(name)))
    for name in BRANDS:
        db.session.add(Brand(name=name, slug=slugify(name), description="Marca de exemplo (dado inicial) — edite ou exclua no painel."))
    db.session.flush()
    brands = {b.name: b for b in Brand.query.all()}
    cats = {c.name: c for c in Category.query.all()}
    fams = {f.name: f for f in Family.query.all()}
    for i, (name, brand, cat, fam, vol, price, promo, featured, gender) in enumerate(DEMO_PRODUCTS, 1):
        db.session.add(Product(
            name=name, slug=slugify(name), brand_id=brands[brand].id, category_id=cats[cat].id,
            family_id=fams[fam].id, volume=vol, price=Decimal(price),
            promo_price=Decimal(promo) if promo else None, promo_active=bool(promo),
            short_description="Produto de demonstração — edite ou exclua no painel.",
            description="Este é um produto de exemplo criado automaticamente. Exclua-o em Admin > Produtos.",
            top_notes="Bergamota, Pimenta rosa", heart_notes="Jasmim, Íris", base_notes="Âmbar, Cedro, Baunilha",
            longevity="Alta", projection="Moderada", occasion="Dia a dia e noite", gender=gender,
            stock=25, min_stock=5, featured=featured, bestseller=i in (1, 4), sku=f"DEMO-{i:03d}",
        ))
    db.session.add(Setting(key="seed_done", value="1"))
    db.session.commit()
    log.info("Dados iniciais de demonstração criados.")


def ensure_admin():
    """Cria o 1º administrador somente se NENHUM existir. Nunca sobrescreve."""
    if User.query.filter_by(is_admin=True).first():
        return
    email = (os.environ.get("ADMIN_EMAIL") or "admin@minhaloja.com").strip().lower()
    name = os.environ.get("ADMIN_NAME") or "Administrador"
    password = os.environ.get("ADMIN_PASSWORD") or ""
    generated = False
    if len(password) < 8:
        password, generated = secrets.token_urlsafe(12), True
    if User.query.filter_by(email=email).first():
        log.error("O e-mail %s já existe como cliente; defina outro ADMIN_EMAIL.", email)
        return
    admin = User(name=name, email=email, is_admin=True, active=True)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    log.warning("=" * 60)
    log.warning("ADMINISTRADOR CRIADO: %s", email)
    if generated:
        log.warning("SENHA INICIAL (aparece só agora, troque em Admin > Conta): %s", password)
    else:
        log.warning("Senha: a definida em ADMIN_PASSWORD.")
    log.warning("=" * 60)


def init_database(app):
    with app.app_context():
        _wait_for_db()
        lock_conn = None
        if db.engine.dialect.name == "postgresql":  # evita corrida entre workers/deploys
            lock_conn = db.engine.connect()
            lock_conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
            lock_conn.commit()
        try:
            upgrade(directory=MIGRATIONS_DIR)  # migrations pendentes (nunca destrutivo)
            seed_initial_data()
            ensure_admin()
        finally:
            if lock_conn is not None:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
                lock_conn.commit()
                lock_conn.close()
        log.warning("Banco pronto.")
