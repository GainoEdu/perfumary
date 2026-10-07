import logging
import os

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from .extensions import csrf, db, limiter, login_manager, migrate


def create_app(test_config=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    if app.config["IS_PRODUCTION"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(os.path.dirname(app.root_path), "migrations"))
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.session_protection = "strong"
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faça login para continuar."

    from .models import User
    from .utils import brl, get_settings, nl2br, safe_link

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (ValueError, TypeError):
            return None

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import flash
        flash("Faça login para continuar.", "info")
        if request.path.startswith("/admin"):
            return redirect(url_for("admin.login", next=request.path))
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))

    app.jinja_env.filters["brl"] = brl
    app.jinja_env.filters["nl2br"] = nl2br
    app.jinja_env.filters["safe_link"] = safe_link

    @app.template_global()
    def page_url(n):
        args = dict(request.view_args or {})
        args.update(request.args.to_dict())
        args["page"] = n
        return url_for(request.endpoint, **args)

    @app.context_processor
    def inject_globals():
        from .models import Brand, Category
        from .cart import cart_count
        s = get_settings()
        try:
            nav_categories = Category.query.filter_by(active=True).order_by(Category.name).limit(8).all()
        except Exception:
            db.session.rollback()
            nav_categories = []
        return {"s": s, "cart_count": cart_count(), "nav_categories": nav_categories}

    from .shop import bp as shop_bp
    from .auth import bp as auth_bp
    from .cart import bp as cart_bp
    from .admin import bp as admin_bp
    for bp in (shop_bp, auth_bp, cart_bp, admin_bp):
        app.register_blueprint(bp)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
        )
        if app.config["IS_PRODUCTION"]:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.path.startswith(("/admin", "/minha-conta", "/carrinho", "/checkout", "/login", "/cadastro")):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def error_page(code, title, message):
        return render_template("error.html", code=code, title=title, message=message), code

    @app.errorhandler(403)
    def e403(e):
        return error_page(403, "Acesso negado", "Você não tem permissão para acessar esta página.")

    @app.errorhandler(404)
    def e404(e):
        return error_page(404, "Página não encontrada", "O endereço acessado não existe.")

    @app.errorhandler(413)
    def e413(e):
        return error_page(413, "Arquivo muito grande", "O envio excede o tamanho permitido.")

    @app.errorhandler(429)
    def e429(e):
        return error_page(429, "Muitas tentativas", "Aguarde um momento e tente novamente.")

    @app.errorhandler(400)
    def e400(e):
        return error_page(400, "Requisição inválida", "Sua sessão pode ter expirado. Volte e tente novamente.")

    @app.errorhandler(500)
    def e500(e):
        db.session.rollback()
        return error_page(500, "Erro interno", "Algo deu errado. Tente novamente em instantes.")

    return app
