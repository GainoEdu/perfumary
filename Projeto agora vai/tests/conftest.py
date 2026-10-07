import io
from decimal import Decimal

import pytest
from PIL import Image

from app import create_app
from app.bootstrap import init_database
from app.extensions import db
from app.models import Brand, Category, Product, User

ADMIN_EMAIL = "admin@test.com"
ADMIN_PASSWORD = "Admin1234!"
VALID_CPF = "52998224725"


def make_app(tmp_path, **extra):
    cfg = {"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 't.db'}", "WTF_CSRF_ENABLED": False,
           "RATELIMIT_ENABLED": False, "SECRET_KEY": "test-secret", "SESSION_COOKIE_SECURE": False}
    cfg.update(extra)
    app = create_app(cfg)
    init_database(app)  # exercita migrations + seed + admin automáticos
    return app


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)
    return make_app(tmp_path)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_client(app):
    c = app.test_client()
    r = c.post("/admin/login", data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 302
    return c


def png_file(name="foto.png"):
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(buf, "PNG")
    buf.seek(0)
    return (buf, name)


def register(client, email="ana@test.com", password="Senha1234"):
    return client.post("/cadastro", data={"name": "Ana Souza", "email": email, "phone": "19999998888",
                                          "password": password, "password2": password}, follow_redirects=False)


def make_product(app, name="Perfume Teste", price="100.00", stock=10, **kw):
    with app.app_context():
        p = Product(name=name, slug=name.lower().replace(" ", "-"), price=Decimal(price), stock=stock, **kw)
        db.session.add(p)
        db.session.commit()
        return p.id


def checkout_data(**over):
    d = {"name": "Ana Souza", "cpf": VALID_CPF, "phone": "19999998888", "email": "ana@test.com", "zip_code": "13500000",
         "state": "SP", "city": "Rio Claro", "neighborhood": "Centro", "street": "Rua 1", "street_number": "10"}
    d.update(over)
    return d
