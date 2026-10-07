import io
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlparse

from flask import g, request
from markupsafe import Markup, escape
from PIL import Image

from .extensions import db
from .models import Media, Setting
from .settings_def import FIELDS, MAXLEN

Image.MAX_IMAGE_PIXELS = 40_000_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
UFS = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
       "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"]


# ---------- textos ----------
def slugify(text):
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower() or "item"


def unique_slug(model, text, exclude_id=None):
    base = slugify(text)[:150]
    slug, i = base, 2
    while True:
        q = model.query.filter(model.slug == slug)
        if exclude_id:
            q = q.filter(model.id != exclude_id)
        if not q.first():
            return slug
        slug = f"{base}-{i}"
        i += 1


def nl2br(text):
    return Markup("<br>").join(escape(line) for line in (text or "").splitlines())


def brl(value):
    try:
        v = Decimal(value or 0)
    except InvalidOperation:
        v = Decimal(0)
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def only_digits(s):
    return re.sub(r"\D", "", s or "")


def is_safe_url(target):
    if not target or target.startswith("//") or "\\" in target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc


def safe_link(value):
    """Links digitados pelo admin: aceita caminho interno ou http(s)."""
    v = (value or "").strip()
    if v.startswith("/") and not v.startswith("//"):
        return v
    if v.lower().startswith(("http://", "https://")):
        return v
    return "/"


# ---------- números ----------
def parse_money(s):
    s = (s or "").strip().replace("R$", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if not d.is_finite() or d < 0 or d > Decimal("9999999.99"):
        return None
    return d.quantize(Decimal("0.01"))


def parse_int(s, default=None, minimum=None, maximum=None):
    try:
        v = int(str(s).strip())
    except (ValueError, TypeError):
        return default
    if minimum is not None and v < minimum:
        return default
    if maximum is not None and v > maximum:
        return default
    return v


def valid_cpf(cpf):
    d = only_digits(cpf)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        s = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != int(d[n]):
            return False
    return True


def password_error(pw):
    if len(pw or "") < 8:
        return "A senha deve ter pelo menos 8 caracteres."
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return "A senha deve conter letras e números."
    return None


# ---------- imagens ----------
class InvalidImage(Exception):
    pass


def save_image(file_storage, max_side=1600):
    """Valida e RE-CODIFICA a imagem (remove qualquer conteúdo malicioso) e guarda no banco."""
    raw = file_storage.read()
    if not raw:
        raise InvalidImage("Arquivo vazio.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise InvalidImage("Imagem maior que 8 MB.")
    try:
        probe = Image.open(io.BytesIO(raw))
        if probe.format not in ALLOWED_FORMATS:
            raise InvalidImage("Formato não permitido. Use JPG, PNG ou WEBP.")
        probe.verify()
        img = Image.open(io.BytesIO(raw))
        img.load()
    except InvalidImage:
        raise
    except Exception:
        raise InvalidImage("Arquivo de imagem inválido.")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    if "A" in img.getbands() or "transparency" in img.info:
        img.convert("RGBA").save(out, "PNG", optimize=True)
        mime = "image/png"
    else:
        img.convert("RGB").save(out, "JPEG", quality=86, optimize=True, progressive=True)
        mime = "image/jpeg"
    media = Media(data=out.getvalue(), mimetype=mime)
    db.session.add(media)
    db.session.flush()
    return media


def delete_media(media_id):
    if media_id:
        m = db.session.get(Media, media_id)
        if m:
            db.session.delete(m)


# ---------- configurações ----------
def get_settings():
    if "_settings" not in g:
        try:
            rows = {r.key: r.value for r in Setting.query.all()}
        except Exception:
            db.session.rollback()
            rows = {}
        g._settings = {k: (rows[k] if rows.get(k) is not None else v[2]) for k, v in FIELDS.items()}
    return g._settings


def set_setting(key, value):
    row = db.session.get(Setting, key)
    if row:
        row.value = value
    else:
        db.session.add(Setting(key=key, value=value))
    g.pop("_settings", None)


def save_settings_group(keys, form, files):
    """Salva somente chaves da lista branca `keys`. Retorna lista de erros."""
    errors = []
    for key in keys:
        label, typ, default, _ = FIELDS[key]
        if typ == "bool":
            set_setting(key, "1" if form.get(key) else "0")
        elif typ == "image":
            f = files.get(key)
            if f and f.filename:
                try:
                    old = get_settings().get(key)
                    media = save_image(f)
                    set_setting(key, str(media.id))
                    if old and old.isdigit():
                        delete_media(int(old))
                except InvalidImage as e:
                    errors.append(f"{label}: {e}")
            elif form.get(key + "__remove"):
                old = get_settings().get(key)
                if old and old.isdigit():
                    delete_media(int(old))
                set_setting(key, "")
        elif typ == "color":
            v = form.get(key, "").strip()
            if COLOR_RE.match(v):
                set_setting(key, v.lower())
            else:
                errors.append(f"{label}: cor inválida.")
        elif typ == "money":
            v = parse_money(form.get(key))
            if v is None:
                errors.append(f"{label}: valor inválido.")
            else:
                set_setting(key, str(v))
        else:
            v = form.get(key, "").strip()[:MAXLEN.get(typ, 200)]
            if typ == "email" and v and not EMAIL_RE.match(v):
                errors.append(f"{label}: e-mail inválido.")
            elif typ == "url" and v and not v.lower().startswith(("http://", "https://")):
                errors.append(f"{label}: use um link começando com https://")
            else:
                set_setting(key, v)
    return errors
