from datetime import datetime, timezone
from decimal import Decimal

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc)


ORDER_STATUSES = [
    "Aguardando pagamento",
    "Pagamento aprovado",
    "Em preparação",
    "Enviado",
    "Entregue",
    "Cancelado",
]
REVENUE_STATUSES = ORDER_STATUSES[1:5]


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    phone = db.Column(db.String(30))
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    @property
    def is_active(self):
        return bool(self.active)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Media(db.Model):
    """Imagens ficam no PostgreSQL (o disco do Render é efêmero)."""
    __tablename__ = "media"
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.LargeBinary, nullable=False)
    mimetype = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)


class Taxonomy(db.Model):
    __abstract__ = True
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    slug = db.Column(db.String(160), nullable=False, unique=True, index=True)
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, nullable=False, default=True)


class Brand(Taxonomy):
    __tablename__ = "brands"
    logo_media_id = db.Column(db.Integer, db.ForeignKey("media.id", ondelete="SET NULL"))


class Category(Taxonomy):
    __tablename__ = "categories"


class Family(Taxonomy):
    __tablename__ = "olfactory_families"


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(220), nullable=False, unique=True, index=True)
    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id", ondelete="SET NULL"), index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id", ondelete="SET NULL"), index=True)
    family_id = db.Column(db.Integer, db.ForeignKey("olfactory_families.id", ondelete="SET NULL"), index=True)
    short_description = db.Column(db.String(300))
    description = db.Column(db.Text)
    sku = db.Column(db.String(60), unique=True)
    barcode = db.Column(db.String(60))
    manufacturer = db.Column(db.String(120))
    origin_country = db.Column(db.String(80))
    launch_year = db.Column(db.Integer)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    promo_price = db.Column(db.Numeric(10, 2))
    promo_active = db.Column(db.Boolean, nullable=False, default=False)
    volume = db.Column(db.String(40))
    top_notes = db.Column(db.Text)
    heart_notes = db.Column(db.Text)
    base_notes = db.Column(db.Text)
    longevity = db.Column(db.String(80))
    projection = db.Column(db.String(80))
    occasion = db.Column(db.String(120))
    gender = db.Column(db.String(40))
    stock = db.Column(db.Integer, nullable=False, default=0)
    min_stock = db.Column(db.Integer, nullable=False, default=5)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    featured = db.Column(db.Boolean, nullable=False, default=False)
    bestseller = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)

    brand = db.relationship("Brand")
    category = db.relationship("Category")
    family = db.relationship("Family")
    images = db.relationship(
        "ProductImage", back_populates="product", cascade="all, delete-orphan",
        order_by="ProductImage.position", passive_deletes=True,
    )

    @property
    def on_promo(self):
        return bool(self.promo_active and self.promo_price is not None and self.promo_price < self.price)

    @property
    def current_price(self):
        return self.promo_price if self.on_promo else self.price

    @property
    def discount_percent(self):
        if not self.on_promo:
            return 0
        return int((Decimal(1) - self.promo_price / self.price) * 100)

    @property
    def main_image(self):
        for img in self.images:
            if img.is_main:
                return img
        return self.images[0] if self.images else None

    @property
    def low_stock(self):
        return self.stock <= (self.min_stock or 0)


class ProductImage(db.Model):
    __tablename__ = "product_images"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    media_id = db.Column(db.Integer, db.ForeignKey("media.id", ondelete="CASCADE"), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    is_main = db.Column(db.Boolean, nullable=False, default=False)
    product = db.relationship("Product", back_populates="images")
    media = db.relationship("Media")


class Banner(db.Model):
    __tablename__ = "banners"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    subtitle = db.Column(db.String(300))
    button_text = db.Column(db.String(60))
    link = db.Column(db.String(300))
    media_id = db.Column(db.Integer, db.ForeignKey("media.id", ondelete="SET NULL"))
    position = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)


class Setting(db.Model):
    __tablename__ = "settings"
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text)


class Order(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(30), nullable=False, unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    customer_name = db.Column(db.String(120), nullable=False)
    cpf = db.Column(db.String(14), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    zip_code = db.Column(db.String(9), nullable=False)
    state = db.Column(db.String(2), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    neighborhood = db.Column(db.String(100), nullable=False)
    street = db.Column(db.String(150), nullable=False)
    street_number = db.Column(db.String(20), nullable=False)
    complement = db.Column(db.String(100))
    subtotal = db.Column(db.Numeric(10, 2), nullable=False)
    shipping = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    discount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(30), nullable=False, default=ORDER_STATUSES[0], index=True)
    payment_method = db.Column(db.String(30), default="manual")
    payment_reference = db.Column(db.String(120))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = db.relationship("User")
    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(db.Model):
    __tablename__ = "order_items"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="SET NULL"))
    name = db.Column(db.String(200), nullable=False)
    sku = db.Column(db.String(60))
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)  # preço no momento da compra
    quantity = db.Column(db.Integer, nullable=False)
    line_total = db.Column(db.Numeric(10, 2), nullable=False)
    order = db.relationship("Order", back_populates="items")
