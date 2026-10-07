from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, make_app, register
from app.extensions import db
from app.models import User


def test_register_login_logout(client):
    assert register(client).status_code == 302
    assert client.get("/minha-conta").status_code == 200
    client.post("/logout")
    assert client.get("/minha-conta").status_code == 302
    r = client.post("/login", data={"email": "ana@test.com", "password": "Senha1234"})
    assert r.status_code == 302 and client.get("/minha-conta").status_code == 200


def test_register_validations(client, app):
    assert register(client, password="curta").status_code == 200
    assert register(client, password="somenteletras").status_code == 200
    register(client)
    client.post("/logout")
    assert register(client).status_code == 200  # e-mail duplicado
    with app.app_context():
        assert User.query.filter_by(email="ana@test.com").count() == 1


def test_register_cannot_set_admin(client, app):
    client.post("/cadastro", data={"name": "Eve Hacker", "email": "eve@test.com", "phone": "19999998888",
                                   "password": "Senha1234", "password2": "Senha1234", "is_admin": "1"})
    with app.app_context():
        assert User.query.filter_by(email="eve@test.com").one().is_admin is False


def test_wrong_password(client):
    register(client)
    client.post("/logout")
    r = client.post("/login", data={"email": "ana@test.com", "password": "errada123"})
    assert r.status_code == 200 and b"incorretos" in r.data


def test_password_is_hashed(client, app):
    register(client)
    with app.app_context():
        u = User.query.filter_by(email="ana@test.com").one()
        assert "Senha1234" not in u.password_hash


def test_account_change_password(client):
    register(client)
    client.post("/minha-conta", data={"action": "password", "current_password": "Senha1234",
                                      "new_password": "NovaSenha99", "new_password2": "NovaSenha99"})
    client.post("/logout")
    assert client.post("/login", data={"email": "ana@test.com", "password": "NovaSenha99"}).status_code == 302


def test_open_redirect_blocked(client):
    register(client)
    client.post("/logout")
    r = client.post("/login?next=https://evil.com", data={"email": "ana@test.com", "password": "Senha1234"})
    assert "evil.com" not in r.headers["Location"]


def test_admin_permissions(client, admin_client):
    # anônimo -> login do admin
    r = client.get("/admin/")
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]
    for path in ("/admin/produtos", "/admin/pedidos", "/admin/homepage", "/admin/clientes"):
        assert client.get(path).status_code == 302
    # cliente comum -> 403
    register(client)
    for path in ("/admin/", "/admin/produtos", "/admin/configuracoes"):
        assert client.get(path).status_code == 403
    assert client.post("/admin/produtos/novo", data={"name": "x", "price": "1"}).status_code == 403
    # admin -> 200
    assert admin_client.get("/admin/").status_code == 200


def test_customer_cannot_login_to_admin(client):
    register(client)
    client.post("/logout")
    r = client.post("/admin/login", data={"email": "ana@test.com", "password": "Senha1234"})
    assert r.status_code == 200 and b"inv" in r.data


def test_login_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)
    app = make_app(tmp_path, RATELIMIT_ENABLED=True)
    c = app.test_client()
    codes = [c.post("/login", data={"email": "a@b.com", "password": "x"}).status_code for _ in range(15)]
    assert 429 in codes


def test_security_headers(client):
    r = client.get("/")
    assert r.headers["X-Frame-Options"] == "DENY" and "default-src 'self'" in r.headers["Content-Security-Policy"]
