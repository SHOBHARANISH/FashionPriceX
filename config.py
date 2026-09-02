import os


BASE_DIR = os.path.abspath(os.path.dirname(__file__))

SECRET_KEY = os.environ.get("SECRET_KEY", "clothing-marketplace-secret-key")

MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "Shobha@123")
MYSQL_DB = os.environ.get("MYSQL_DB", "clothing_marketplace")
MYSQL_CURSORCLASS = "DictCursor"

UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "images", "products")
MAX_CONTENT_LENGTH = 4 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "shobz2426@gmail.com")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "kdaj vnrd mbgh jvef")
MAIL_SENDER_NAME = os.environ.get("MAIL_SENDER_NAME", "FashionPriceX")
