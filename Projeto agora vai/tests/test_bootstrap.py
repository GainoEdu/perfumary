from app.bootstrap import init_database
from app.extensions import db
from app.models import Brand, Category, Product, User


def test_admin_created_with_hash_and_idempotent(app):
    with app.app_context():
        admin = User.query.filter_by(is_admin=True).one()
        assert admin.email == "admin@test.com"
        assert admin.password_hash != "Admin1234!" and admin.check_password("Admin1234!")
        old_hash = admin.password_hash
    init_database(app)  # segunda execução não duplica nem sobrescreve
    with app.app_context():
        assert User.query.filter_by(is_admin=True).count() == 1
        assert User.query.filter_by(is_admin=True).one().password_hash == old_hash


def test_seed_runs_once(app):
    with app.app_context():
        assert Category.query.count() >= 8 and Brand.query.count() >= 8 and Product.query.count() >= 1
        Brand.query.delete()
        db.session.commit()
    init_database(app)
    with app.app_context():
        assert Brand.query.count() == 0  # o que o admin apagou não volta


def test_random_password_when_not_provided(tmp_path, monkeypatch):
    from conftest import make_app
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("ADMIN_EMAIL", "x@test.com")
    app = make_app(tmp_path)
    with app.app_context():
        assert User.query.filter_by(email="x@test.com", is_admin=True).count() == 1
