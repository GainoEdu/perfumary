from decimal import Decimal

from conftest import checkout_data, make_product, register
from app.extensions import db
from app.models import Order, Product


def test_home_and_listing(client, app):
    assert client.get("/").status_code == 200
    make_product(app, "Aurora Dourada", brand_id=None)
    r = client.get("/produtos?q=aurora")
    assert r.status_code == 200 and b"Aurora Dourada" in r.data
    assert b"Aurora Dourada" not in client.get("/produtos?q=inexistente").data
    assert client.get("/produto/aurora-dourada").status_code == 200
    assert client.get("/produto/nao-existe").status_code == 404


def test_search_is_injection_safe(client):
    assert client.get("/produtos?q=' OR 1=1 --").status_code == 200
    assert client.get("/produtos?q=%25%25&ordem=drop").status_code == 200


def test_seo_endpoints(client):
    assert b"urlset" in client.get("/sitemap.xml").data
    assert b"Disallow: /admin" in client.get("/robots.txt").data
    assert client.get("/healthz").data == b"ok"
    assert b"--primary" in client.get("/theme.css").data


def test_inactive_product_hidden(client, app):
    pid = make_product(app, "Oculto", active=False)
    assert client.get("/produto/oculto").status_code == 404
    assert client.post(f"/carrinho/adicionar/{pid}", data={"qty": 1}).status_code == 404


def test_cart_add_update_remove_clear(client, app):
    pid = make_product(app, stock=5)
    client.post(f"/carrinho/adicionar/{pid}", data={"qty": 2})
    assert b"R$ 200,00" in client.get("/carrinho").data
    client.post(f"/carrinho/atualizar/{pid}", data={"qty": 3})
    assert b"R$ 300,00" in client.get("/carrinho").data
    client.post(f"/carrinho/remover/{pid}")
    assert b"vazio" in client.get("/carrinho").data
    client.post(f"/carrinho/adicionar/{pid}", data={"qty": 1})
    client.post("/carrinho/limpar")
    assert b"vazio" in client.get("/carrinho").data


def test_cart_quantity_limited_by_stock(client, app):
    pid = make_product(app, stock=3)
    client.post(f"/carrinho/adicionar/{pid}", data={"qty": 99})
    client.post(f"/carrinho/adicionar/{pid}", data={"qty": 99})
    with client.session_transaction() as s:
        assert s["cart"][str(pid)] == 3


def test_price_in_browser_is_ignored(client, app):
    pid = make_product(app, price="150.00", stock=5)
    client.post(f"/carrinho/adicionar/{pid}", data={"qty": 1, "price": "0.01", "unit_price": "0.01"})
    page = client.get("/carrinho").data
    assert b"R$ 150,00" in page and b"0,01" not in page


def test_negative_and_zero_quantities(client, app):
    pid = make_product(app, stock=5)
    client.post(f"/carrinho/adicionar/{pid}", data={"qty": -5})
    with client.session_transaction() as s:
        assert s["cart"][str(pid)] == 1


def test_checkout_requires_login(client, app):
    pid = make_product(app)
    client.post(f"/carrinho/adicionar/{pid}", data={"qty": 1})
    r = client.get("/checkout")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_checkout_creates_order_and_decrements_stock(client, app):
    pid = make_product(app, price="100.00", stock=10)
    register(client)
    client.post(f"/carrinho/adicionar/{pid}", data={"qty": 2})
    r = client.post("/checkout", data=checkout_data())
    assert r.status_code == 302
    with app.app_context():
        o = Order.query.one()
        assert o.status == "Aguardando pagamento"
        assert o.subtotal == Decimal("200.00") and o.shipping == Decimal("25.00") and o.total == Decimal("225.00")
        assert o.items[0].unit_price == Decimal("100.00") and o.items[0].quantity == 2
        assert db.session.get(Product, pid).stock == 8
        number = o.number
    # preço do pedido não muda se o produto mudar depois
    with app.app_context():
        p = db.session.get(Product, pid)
        p.price = Decimal("999.00")
        db.session.commit()
    assert b"R$ 100,00" in client.get(f"/minha-conta/pedidos/{number}").data
    assert b"vazio" in client.get("/carrinho").data


def test_free_shipping_threshold(client, app):
    pid = make_product(app, price="300.00", stock=5)
    register(client)
    client.post(f"/carrinho/adicionar/{pid}", data={"qty": 1})
    client.post("/checkout", data=checkout_data())
    with app.app_context():
        assert Order.query.one().shipping == Decimal("0.00")


def test_checkout_blocks_oversell(client, app):
    pid = make_product(app, stock=2)
    register(client)
    client.post(f"/carrinho/adicionar/{pid}", data={"qty": 2})
    with app.app_context():  # outro cliente compra antes
        p = db.session.get(Product, pid)
        p.stock = 1
        db.session.commit()
    r = client.post("/checkout", data=checkout_data(), follow_redirects=True)
    with app.app_context():
        assert Order.query.count() == 0 and db.session.get(Product, pid).stock == 1


def test_checkout_validation(client, app):
    pid = make_product(app)
    register(client)
    client.post(f"/carrinho/adicionar/{pid}", data={"qty": 1})
    for bad in ({"cpf": "11111111111"}, {"cep": "1"}, {"zip_code": "123"}, {"state": "XX"}, {"email": "x"}):
        client.post("/checkout", data=checkout_data(**bad))
    with app.app_context():
        assert Order.query.count() == 0


def test_order_idor(client, app):
    pid = make_product(app)
    register(client)
    client.post(f"/carrinho/adicionar/{pid}", data={"qty": 1})
    client.post("/checkout", data=checkout_data())
    with app.app_context():
        number = Order.query.one().number
    other = app.test_client()
    register(other, email="bia@test.com")
    assert other.get(f"/minha-conta/pedidos/{number}").status_code == 404
