from decimal import Decimal
import io

from conftest import checkout_data, make_product, png_file, register
from app.extensions import db
from app.models import Banner, Brand, Order, Product, ProductImage, Setting


def product_form(**over):
    d = {"name": "Perfume Novo", "price": "199,90", "stock": "7", "min_stock": "2", "active": "1", "volume": "75 ml",
         "top_notes": "Limão", "gender": "Unissex"}
    d.update(over)
    return d


def test_dashboard_and_pages_load(admin_client):
    for path in ("/admin/", "/admin/produtos", "/admin/produtos/novo", "/admin/marcas", "/admin/categorias",
                 "/admin/familias", "/admin/estoque", "/admin/pedidos", "/admin/clientes", "/admin/banners",
                 "/admin/banners/novo", "/admin/homepage", "/admin/aparencia", "/admin/configuracoes", "/admin/conta",
                 "/admin/marcas/novo"):
        assert admin_client.get(path).status_code == 200, path


def test_create_brand_category_family(admin_client, app):
    for kind in ("marcas", "categorias", "familias"):
        r = admin_client.post(f"/admin/{kind}/novo", data={"name": f"Nova {kind}", "active": "1"})
        assert r.status_code == 302
    admin_client.post("/admin/marcas/novo", data={"name": "Nova marcas"})  # duplicado
    with app.app_context():
        assert Brand.query.filter_by(name="Nova marcas").count() == 1
        b = Brand.query.filter_by(name="Nova marcas").one()
        assert b.slug == "nova-marcas"


def test_create_product_with_image_and_edit(admin_client, app):
    data = product_form()
    data["images"] = [png_file("a.png"), png_file("b.png")]
    r = admin_client.post("/admin/produtos/novo", data=data, content_type="multipart/form-data")
    assert r.status_code == 302
    with app.app_context():
        p = Product.query.filter_by(name="Perfume Novo").one()
        assert p.price == Decimal("199.90") and p.volume == "75 ml" and len(p.images) == 2
        assert [i.is_main for i in p.images] == [True, False]
        pid, second = p.id, p.images[1].id
    admin_client.post(f"/admin/imagens/{second}/principal")
    admin_client.post(f"/admin/imagens/{second}/subir")
    with app.app_context():
        p = db.session.get(Product, pid)
        assert p.images[0].id == second and p.main_image.id == second
    admin_client.post(f"/admin/imagens/{second}/excluir")
    with app.app_context():
        p = db.session.get(Product, pid)
        assert len(p.images) == 1 and p.images[0].is_main
    r = admin_client.post(f"/admin/produtos/{pid}/editar", data=product_form(name="Renomeado", price="250"))
    assert r.status_code == 302
    with app.app_context():
        assert db.session.get(Product, pid).name == "Renomeado"
    assert admin_client.post(f"/admin/produtos/{pid}/excluir").status_code == 302
    with app.app_context():
        assert db.session.get(Product, pid) is None


def test_media_served(admin_client, client, app):
    data = product_form()
    data["images"] = [png_file()]
    admin_client.post("/admin/produtos/novo", data=data, content_type="multipart/form-data")
    with app.app_context():
        mid = Product.query.filter_by(name="Perfume Novo").one().images[0].media_id
    r = client.get(f"/media/{mid}")
    assert r.status_code == 200 and r.mimetype in ("image/jpeg", "image/png")
    assert client.get("/media/99999").status_code == 404


def test_malicious_upload_rejected(admin_client, app):
    data = product_form()
    data["images"] = [(io.BytesIO(b"<?php system($_GET['x']); ?>"), "shell.png"),
                      (io.BytesIO(b"<svg onload=alert(1)></svg>"), "x.svg")]
    admin_client.post("/admin/produtos/novo", data=data, content_type="multipart/form-data")
    with app.app_context():
        assert ProductImage.query.count() == 0


def test_product_validation(admin_client, app):
    for bad in ({"price": "abc"}, {"price": "-5"}, {"stock": "-1"}, {"name": ""},
                {"promo_active": "1", "promo_price": "500", "price": "100"}):
        admin_client.post("/admin/produtos/novo", data=product_form(**bad))
    with app.app_context():
        assert Product.query.filter_by(name="Perfume Novo").count() == 0
        assert Product.query.filter(Product.name == "").count() == 0


def test_promotion_price(admin_client, app):
    admin_client.post("/admin/produtos/novo", data=product_form(price="200", promo_price="150", promo_active="1"))
    with app.app_context():
        p = Product.query.filter_by(name="Perfume Novo").one()
        assert p.current_price == Decimal("150.00") and p.on_promo and p.discount_percent == 25


def test_mass_assignment_ignored(admin_client, app):
    admin_client.post("/admin/produtos/novo", data=product_form(id="9999", slug="hack", created_at="2000-01-01"))
    with app.app_context():
        p = Product.query.filter_by(name="Perfume Novo").one()
        assert p.id != 9999 and p.slug == "perfume-novo"


def test_stock_update(admin_client, app):
    pid = make_product(app, stock=5)
    admin_client.post(f"/admin/estoque/{pid}", data={"stock": "42", "min_stock": "3"})
    with app.app_context():
        assert db.session.get(Product, pid).stock == 42
    admin_client.post(f"/admin/estoque/{pid}", data={"stock": "-4", "min_stock": "3"})
    with app.app_context():
        assert db.session.get(Product, pid).stock == 42


def test_settings_appearance_and_homepage(admin_client, client, app):
    r = admin_client.post("/admin/aparencia", data={"color_primary": "#ff0000", "color_secondary": "#000000",
                          "color_button": "#222222", "color_button_text": "#ffffff", "color_bg": "#ffffff",
                          "color_text": "#111111"})
    assert r.status_code == 302 and b"#ff0000" in client.get("/theme.css").data
    admin_client.post("/admin/aparencia", data={"color_primary": "red;}body{display:none", "color_secondary": "#000000",
                      "color_button": "#222222", "color_button_text": "#ffffff", "color_bg": "#ffffff", "color_text": "#111111"})
    assert b"display:none" not in client.get("/theme.css").data
    admin_client.post("/admin/configuracoes", data={"store_name": "Loja <b>Teste</b>", "shipping_flat": "10,00",
                      "free_shipping_above": "0", "footer_text": "Rodapé"})
    page = client.get("/").data
    assert b"Loja &lt;b&gt;Teste&lt;/b&gt;" in page and b"<b>Teste</b>" not in page  # XSS escapado
    admin_client.post("/admin/homepage", data={"hero_title": "Novo título", "show_featured": "1"})
    page = client.get("/").data
    assert b"Novo t" in page


def test_homepage_sections_toggle(admin_client, client):
    assert b"Em destaque" in client.get("/").data
    admin_client.post("/admin/homepage", data={"hero_title": "x"})  # tudo desmarcado
    assert b"Em destaque" not in client.get("/").data


def test_banner_crud(admin_client, client, app):
    admin_client.post("/admin/banners/novo", data={"title": "Black Friday", "link": "javascript:alert(1)", "active": "1",
                      "image": png_file()}, content_type="multipart/form-data")
    with app.app_context():
        b = Banner.query.one()
        assert b.link == "/" and b.media_id
        bid = b.id
    assert b"Black Friday" in client.get("/").data
    admin_client.post(f"/admin/banners/{bid}/excluir")
    with app.app_context():
        assert Banner.query.count() == 0


def test_order_management_and_cancel_restocks(admin_client, app):
    pid = make_product(app, stock=10)
    c = app.test_client()
    register(c)
    c.post(f"/carrinho/adicionar/{pid}", data={"qty": 3})
    c.post("/checkout", data=checkout_data())
    with app.app_context():
        oid, number = Order.query.one().id, Order.query.one().number
        assert db.session.get(Product, pid).stock == 7
    assert number.encode() in admin_client.get(f"/admin/pedidos?q={number}").data
    assert admin_client.get("/admin/pedidos?status=Enviado").status_code == 200
    admin_client.post(f"/admin/pedidos/{oid}/status", data={"status": "Enviado"})
    admin_client.post(f"/admin/pedidos/{oid}/status", data={"status": "Cancelado"})
    with app.app_context():
        assert db.session.get(Order, oid).status == "Cancelado" and db.session.get(Product, pid).stock == 10
    admin_client.post(f"/admin/pedidos/{oid}/status", data={"status": "Entregue"})  # não reabre
    admin_client.post(f"/admin/pedidos/{oid}/status", data={"status": "Cancelado"})  # não duplica estoque
    with app.app_context():
        assert db.session.get(Order, oid).status == "Cancelado" and db.session.get(Product, pid).stock == 10
    assert admin_client.post(f"/admin/pedidos/{oid}/status", data={"status": "Inventado"}).status_code == 302


def test_customers_list_and_block(admin_client, app):
    c = app.test_client()
    register(c)
    assert b"ana@test.com" in admin_client.get("/admin/clientes").data
    from app.models import User
    with app.app_context():
        uid = User.query.filter_by(email="ana@test.com").one().id
    admin_client.post(f"/admin/clientes/{uid}/alternar")
    c.post("/logout")
    r = c.post("/login", data={"email": "ana@test.com", "password": "Senha1234"})
    assert r.status_code == 200  # bloqueado


def test_admin_account_password(admin_client, client):
    admin_client.post("/admin/conta", data={"action": "password", "current_password": "Admin1234!",
                                            "new_password": "OutraSenha77", "new_password2": "OutraSenha77"})
    admin_client.post("/admin/logout")
    r = client.post("/admin/login", data={"email": "admin@test.com", "password": "OutraSenha77"})
    assert r.status_code == 302
