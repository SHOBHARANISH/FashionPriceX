import os
import smtplib
import uuid
from datetime import datetime
from email.message import EmailMessage
from functools import wraps

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from flask_mysqldb import MySQL
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import config


app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["MYSQL_HOST"] = config.MYSQL_HOST
app.config["MYSQL_USER"] = config.MYSQL_USER
app.config["MYSQL_PASSWORD"] = config.MYSQL_PASSWORD
app.config["MYSQL_DB"] = config.MYSQL_DB
app.config["MYSQL_CURSORCLASS"] = config.MYSQL_CURSORCLASS
app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH

mysql = MySQL(app)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


ROLE_ENDPOINTS = {
    "customer": "customer_dashboard",
    "product_builder": "builder_dashboard",
    "delivery_person": "delivery_dashboard",
}

CATEGORY_OPTIONS = [
    "Shirts",
    "T-Shirts",
    "Jeans",
    "Jackets",
    "Dresses",
    "Ethnic Wear",
    "Footwear",
    "Accessories",
]

PAYMENT_METHODS = {
    "phonepe": "PhonePe",
    "cash_on_delivery": "Cash on Delivery",
    "credit_card": "Credit Card",
    "debit_card": "Debit Card",
    "upi": "UPI",
    "net_banking": "Net Banking",
}

IMAGE_CHOICES = [
    "default.png",
    "shirt.jpg",
    "jeans.jpg",
    "jacket.jpg",
    "dress.jpg",
    "shoe.jpg",
]

_schema_checked = False


def query_db(query, params=None, fetchone=False, commit=False):
    cursor = mysql.connection.cursor()
    cursor.execute(query, params or ())
    if commit:
        mysql.connection.commit()
        lastrowid = cursor.lastrowid
        cursor.close()
        return lastrowid
    result = cursor.fetchone() if fetchone else cursor.fetchall()
    cursor.close()
    return result


def ensure_column(table_name, column_name, column_definition):
    existing = query_db(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (table_name, column_name),
        fetchone=True,
    )
    if not existing:
        query_db(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}", commit=True)


def ensure_schema_updates():
    global _schema_checked
    if _schema_checked:
        return
    ensure_column("users", "email", "VARCHAR(160) NULL UNIQUE AFTER username")
    ensure_column("orders", "payment_method", "VARCHAR(40) NOT NULL DEFAULT 'cash_on_delivery' AFTER total_amount")
    ensure_column("orders", "payment_status", "VARCHAR(40) NOT NULL DEFAULT 'pending' AFTER payment_method")
    _schema_checked = True


@app.before_request
def run_schema_updates():
    ensure_schema_updates()


def create_notification(user_id, order_id, title, message):
    query_db(
        """
        INSERT INTO notifications (user_id, order_id, title, message)
        VALUES (%s, %s, %s, %s)
        """,
        (user_id, order_id, title, message),
        commit=True,
    )


def send_order_confirmation_email(customer, order, items):
    if not customer or not customer.get("email"):
        return False, "No registered email address found for this customer."

    item_lines = "\n".join(
        f"- {item['name']} x{item['quantity']} = Rs. {item['line_total']:.2f}"
        for item in items
    )
    payment_label = PAYMENT_METHODS.get(order["payment_method"], order["payment_method"])
    message = EmailMessage()
    message["Subject"] = f"FashionPriceX order confirmation - {order['order_number']}"
    message["From"] = f"{config.MAIL_SENDER_NAME} <{config.MAIL_USERNAME}>"
    message["To"] = customer["email"]
    message.set_content(
        f"""Hello {customer['full_name']},

Your FashionPriceX order has been confirmed.

Order number: {order['order_number']}
Payment method: {payment_label}
Payment status: {order['payment_status'].replace('_', ' ').title()}
Total: Rs. {float(order['total_amount']):.2f}

Items:
{item_lines}

Delivery address:
{order['shipping_address']}

Thank you for shopping with FashionPriceX.
"""
    )

    try:
        with smtplib.SMTP(config.MAIL_SERVER, config.MAIL_PORT, timeout=15) as smtp:
            if config.MAIL_USE_TLS:
                smtp.starttls()
            smtp.login(config.MAIL_USERNAME, config.MAIL_PASSWORD)
            smtp.send_message(message)
        return True, None
    except Exception as exc:
        return False, str(exc)


def get_user_notifications(user_id, limit=8):
    return query_db(
        """
        SELECT id, title, message, is_read, created_at
        FROM notifications
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (user_id, limit),
    )


def get_user_by_id(user_id):
    return query_db("SELECT * FROM users WHERE id = %s", (user_id,), fetchone=True)


def current_user():
    if not session.get("user_id"):
        return None
    return {
        "id": session.get("user_id"),
        "full_name": session.get("full_name"),
        "username": session.get("username"),
        "email": session.get("email"),
        "phone": session.get("phone"),
        "role": session.get("role"),
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if session.get("role") not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_IMAGE_EXTENSIONS


def save_product_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    filename = secure_filename(file_storage.filename)
    if not allowed_file(filename):
        return None
    extension = filename.rsplit(".", 1)[1].lower()
    generated_name = f"{uuid.uuid4().hex}.{extension}"
    file_storage.save(os.path.join(app.config["UPLOAD_FOLDER"], generated_name))
    return generated_name


def image_url(filename):
    filename = filename or "default.png"
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if not os.path.exists(file_path):
        filename = "default.png"
    return url_for("static", filename=f"images/products/{filename}")


def get_cart():
    cart = session.get("cart", {})
    return {int(product_id): int(quantity) for product_id, quantity in cart.items()}


def save_cart(cart):
    session["cart"] = {str(product_id): int(quantity) for product_id, quantity in cart.items() if quantity > 0}
    session.modified = True


def get_cart_count():
    return sum(get_cart().values())


def get_cart_items():
    cart = get_cart()
    if not cart:
        return [], 0.0

    product_ids = list(cart.keys())
    placeholders = ", ".join(["%s"] * len(product_ids))
    products = query_db(
        f"""
        SELECT id, name, category, price, stock, description, image
        FROM products
        WHERE is_active = 1 AND id IN ({placeholders})
        """,
        tuple(product_ids),
    )
    product_map = {product["id"]: product for product in products}

    items = []
    subtotal = 0.0
    for product_id, quantity in cart.items():
        product = product_map.get(product_id)
        if not product:
            continue
        quantity = min(quantity, max(product["stock"], 0))
        if quantity <= 0:
            continue
        line_total = float(product["price"]) * quantity
        subtotal += line_total
        items.append(
            {
                "product_id": product_id,
                "name": product["name"],
                "category": product["category"],
                "price": float(product["price"]),
                "stock": product["stock"],
                "description": product["description"],
                "image": product["image"],
                "image_url": image_url(product["image"]),
                "quantity": quantity,
                "line_total": round(line_total, 2),
            }
        )
    return items, round(subtotal, 2)


def redirect_to_dashboard(role):
    endpoint = ROLE_ENDPOINTS.get(role, "login")
    return redirect(url_for(endpoint))


@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "cart_count": get_cart_count() if session.get("role") == "customer" else 0,
    }


@app.route("/")
def index():
    if session.get("role"):
        return redirect_to_dashboard(session["role"])
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("role"):
        return redirect_to_dashboard(session["role"])

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = query_db("SELECT * FROM users WHERE username = %s", (username,), fetchone=True)

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["full_name"] = user["full_name"]
            session["username"] = user["username"]
            session["email"] = user.get("email")
            session["phone"] = user["phone"]
            session["role"] = user["role"]
            session.setdefault("cart", {})
            flash(f"Welcome back, {user['full_name']}!", "success")
            return redirect_to_dashboard(user["role"])

        flash("Invalid username or password.", "error")

    return render_template("auth/login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip() or None
        password = request.form.get("password", "")
        role = request.form.get("role", "").strip()
        phone = request.form.get("phone", "").strip() or None
        address = request.form.get("address", "").strip() or None
        latitude = request.form.get("latitude", "").strip() or None
        longitude = request.form.get("longitude", "").strip() or None

        if role not in ROLE_ENDPOINTS:
            flash("Please choose a valid role.", "error")
            return render_template("auth/register.html")

        if role == "customer" and (not phone or not email):
            flash("Customers must register with a phone number and email address.", "error")
            return render_template("auth/register.html")

        existing_user = query_db(
            """
            SELECT id FROM users
            WHERE username = %s
               OR (%s IS NOT NULL AND email = %s)
               OR (%s IS NOT NULL AND phone = %s)
            """,
            (username, email, email, phone, phone),
            fetchone=True,
        )
        if existing_user:
            flash("Username, email, or phone number already exists.", "error")
            return render_template("auth/register.html")

        query_db(
            """
            INSERT INTO users (full_name, username, email, phone, password_hash, role, address, latitude, longitude)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                full_name,
                username,
                email,
                phone,
                generate_password_hash(password),
                role,
                address,
                latitude if latitude else None,
                longitude if longitude else None,
            ),
            commit=True,
        )

        flash("Registration complete. You can log in now.", "success")
        return redirect(url_for("login"))

    return render_template("auth/register.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/customer/dashboard")
@role_required("customer")
def customer_dashboard():
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()

    filters = ["p.is_active = 1"]
    params = []

    if search:
        filters.append("(p.name LIKE %s OR p.description LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    if category:
        filters.append("p.category = %s")
        params.append(category)

    products = query_db(
        f"""
        SELECT p.*, u.full_name AS builder_name
        FROM products p
        LEFT JOIN users u ON u.id = p.builder_id
        WHERE {' AND '.join(filters)}
        ORDER BY p.created_at DESC, p.id DESC
        """,
        tuple(params),
    )
    categories = query_db("SELECT DISTINCT category FROM products WHERE is_active = 1 ORDER BY category")
    orders = query_db(
        """
        SELECT o.*, dp.full_name AS delivery_name,
               GROUP_CONCAT(CONCAT(oi.product_name, ' x', oi.quantity) SEPARATOR ', ') AS items_summary
        FROM orders o
        LEFT JOIN users dp ON dp.id = o.delivery_person_id
        LEFT JOIN order_items oi ON oi.order_id = o.id
        WHERE o.customer_id = %s
        GROUP BY o.id
        ORDER BY o.created_at DESC
        LIMIT 4
        """,
        (session["user_id"],),
    )
    notifications = get_user_notifications(session["user_id"])

    return render_template(
        "customer/dashboard.html",
        products=products,
        categories=categories,
        selected_category=category,
        search=search,
        recent_orders=orders,
        notifications=notifications,
    )


@app.route("/customer/product/<int:product_id>")
@role_required("customer")
def customer_product_detail(product_id):
    product = query_db(
        """
        SELECT p.*, u.full_name AS builder_name
        FROM products p
        LEFT JOIN users u ON u.id = p.builder_id
        WHERE p.id = %s AND p.is_active = 1
        """,
        (product_id,),
        fetchone=True,
    )
    if not product:
        abort(404)

    related_products = query_db(
        """
        SELECT id, name, category, price, image
        FROM products
        WHERE is_active = 1 AND category = %s AND id != %s
        ORDER BY created_at DESC
        LIMIT 3
        """,
        (product["category"], product_id),
    )
    return render_template("customer/product_detail.html", product=product, related_products=related_products)


@app.route("/customer/cart")
@role_required("customer")
def customer_cart():
    cart_items, subtotal = get_cart_items()
    customer = get_user_by_id(session["user_id"])
    delivery_fee = 99.0 if subtotal and subtotal < 2000 else 0.0
    grand_total = round(subtotal + delivery_fee, 2)
    return render_template(
        "customer/cart.html",
        cart_items=cart_items,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        grand_total=grand_total,
        customer=customer,
    )


@app.route("/customer/cart/add/<int:product_id>", methods=["POST"])
@role_required("customer")
def add_to_cart(product_id):
    product = query_db(
        "SELECT id, stock, is_active FROM products WHERE id = %s",
        (product_id,),
        fetchone=True,
    )
    if not product or not product["is_active"]:
        flash("This product is unavailable.", "error")
        return redirect(url_for("customer_dashboard"))
    if product["stock"] <= 0:
        flash("This product is currently out of stock.", "error")
        return redirect(request.referrer or url_for("customer_dashboard"))

    cart = get_cart()
    cart[product_id] = min(cart.get(product_id, 0) + 1, product["stock"])
    save_cart(cart)
    flash("Item added to cart.", "success")
    return redirect(request.referrer or url_for("customer_cart"))


@app.route("/customer/cart/update/<int:product_id>", methods=["POST"])
@role_required("customer")
def update_cart(product_id):
    quantity = max(int(request.form.get("quantity", 1)), 0)
    product = query_db("SELECT id, stock FROM products WHERE id = %s", (product_id,), fetchone=True)
    cart = get_cart()
    if quantity <= 0:
        cart.pop(product_id, None)
    elif product:
        if product["stock"] <= 0:
            cart.pop(product_id, None)
        else:
            cart[product_id] = min(quantity, product["stock"])
    save_cart(cart)
    flash("Cart updated.", "success")
    return redirect(url_for("customer_cart"))


@app.route("/customer/cart/remove/<int:product_id>", methods=["POST"])
@role_required("customer")
def remove_from_cart(product_id):
    cart = get_cart()
    cart.pop(product_id, None)
    save_cart(cart)
    flash("Item removed from cart.", "success")
    return redirect(url_for("customer_cart"))


@app.route("/customer/payment", methods=["GET", "POST"])
@role_required("customer")
def customer_payment():
    cart_items, subtotal = get_cart_items()
    if not cart_items:
        flash("Your cart is empty.", "error")
        return redirect(url_for("customer_cart"))

    for item in cart_items:
        if item["quantity"] > item["stock"]:
            flash(f"Not enough stock for {item['name']}. Please update your cart.", "error")
            return redirect(url_for("customer_cart"))

    delivery_fee = 99.0 if subtotal < 2000 else 0.0
    total_amount = round(subtotal + delivery_fee, 2)

    if request.method == "POST":
        shipping_name = request.form.get("shipping_name", "").strip()
        shipping_phone = request.form.get("shipping_phone", "").strip()
        email = request.form.get("email", "").strip()
        shipping_address = request.form.get("shipping_address", "").strip()
        latitude = request.form.get("latitude", "").strip() or None
        longitude = request.form.get("longitude", "").strip() or None
        notes = request.form.get("notes", "").strip() or None

        if not shipping_name or not shipping_phone or not email or not shipping_address:
            flash("Please complete the shipping details and email address.", "error")
            return redirect(url_for("customer_cart"))

        session["pending_checkout"] = {
            "shipping_name": shipping_name,
            "shipping_phone": shipping_phone,
            "email": email,
            "shipping_address": shipping_address,
            "latitude": latitude,
            "longitude": longitude,
            "notes": notes,
        }
        session.modified = True

    checkout = session.get("pending_checkout")
    if not checkout:
        flash("Please enter delivery details before payment.", "error")
        return redirect(url_for("customer_cart"))

    return render_template(
        "customer/payment.html",
        cart_items=cart_items,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        total_amount=total_amount,
        checkout=checkout,
        payment_methods=PAYMENT_METHODS,
    )


@app.route("/customer/checkout", methods=["POST"])
@role_required("customer")
def place_order():
    cart_items, subtotal = get_cart_items()
    if not cart_items:
        flash("Your cart is empty.", "error")
        return redirect(url_for("customer_cart"))

    for item in cart_items:
        if item["quantity"] > item["stock"]:
            flash(f"Not enough stock for {item['name']}. Please update your cart.", "error")
            return redirect(url_for("customer_cart"))

    checkout = session.get("pending_checkout")
    if not checkout:
        flash("Please complete delivery details before payment.", "error")
        return redirect(url_for("customer_cart"))

    shipping_name = checkout["shipping_name"]
    shipping_phone = checkout["shipping_phone"]
    email = checkout["email"]
    shipping_address = checkout["shipping_address"]
    latitude = checkout.get("latitude")
    longitude = checkout.get("longitude")
    notes = checkout.get("notes")
    payment_method = request.form.get("payment_method", "cash_on_delivery").strip()

    if payment_method not in PAYMENT_METHODS:
        flash("Please choose a valid payment method.", "error")
        return redirect(url_for("customer_cart"))

    delivery_fee = 99.0 if subtotal < 2000 else 0.0
    total_amount = round(subtotal + delivery_fee, 2)
    payment_status = "pending_on_delivery" if payment_method == "cash_on_delivery" else "payment_selected"
    order_number = f"CM-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

    order_id = query_db(
        """
        INSERT INTO orders (
            order_number, customer_id, status, shipping_name, shipping_phone, shipping_address,
            latitude, longitude, subtotal, delivery_fee, total_amount, payment_method, payment_status, notes
        )
        VALUES (%s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            order_number,
            session["user_id"],
            shipping_name,
            shipping_phone,
            shipping_address,
            latitude,
            longitude,
            subtotal,
            delivery_fee,
            total_amount,
            payment_method,
            payment_status,
            notes,
        ),
        commit=True,
    )

    for item in cart_items:
        query_db(
            """
            INSERT INTO order_items (order_id, product_id, product_name, unit_price, quantity, line_total)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                order_id,
                item["product_id"],
                item["name"],
                item["price"],
                item["quantity"],
                item["line_total"],
            ),
            commit=True,
        )
        query_db(
            "UPDATE products SET stock = stock - %s WHERE id = %s",
            (item["quantity"], item["product_id"]),
            commit=True,
        )

    query_db(
        """
        UPDATE users
        SET email = %s, phone = %s, address = %s, latitude = %s, longitude = %s
        WHERE id = %s
        """,
        (email, shipping_phone, shipping_address, latitude, longitude, session["user_id"]),
        commit=True,
    )
    session["email"] = email

    create_notification(
        session["user_id"],
        order_id,
        "Order confirmed",
        f"Your order {order_number} has been placed with {PAYMENT_METHODS[payment_method]}. We also tried to send an email confirmation.",
    )

    customer = get_user_by_id(session["user_id"])
    customer["email"] = email
    email_order = {
        "order_number": order_number,
        "payment_method": payment_method,
        "payment_status": payment_status,
        "total_amount": total_amount,
        "shipping_address": shipping_address,
    }
    email_sent, email_error = send_order_confirmation_email(customer, email_order, cart_items)

    delivery_people = query_db("SELECT id FROM users WHERE role = 'delivery_person'")
    for person in delivery_people:
        create_notification(
            person["id"],
            order_id,
            "Demo SMS: Delivery request available",
            f"New order {order_number} is ready for pickup review. Open your delivery dashboard to accept or reject it.",
        )

    save_cart({})
    session.pop("pending_checkout", None)
    session.modified = True
    if email_sent:
        flash(f"Order {order_number} placed successfully. Confirmation email sent.", "success")
    else:
        flash(f"Order {order_number} placed successfully, but email failed: {email_error}", "error")
    return redirect(url_for("customer_orders"))


@app.route("/customer/orders")
@role_required("customer")
def customer_orders():
    orders = query_db(
        """
        SELECT o.*, dp.full_name AS delivery_name,
               GROUP_CONCAT(CONCAT(oi.product_name, ' x', oi.quantity) SEPARATOR ', ') AS items_summary
        FROM orders o
        LEFT JOIN users dp ON dp.id = o.delivery_person_id
        LEFT JOIN order_items oi ON oi.order_id = o.id
        WHERE o.customer_id = %s
        GROUP BY o.id
        ORDER BY o.created_at DESC
        """,
        (session["user_id"],),
    )
    notifications = get_user_notifications(session["user_id"], limit=12)
    return render_template("customer/orders.html", orders=orders, notifications=notifications)

@app.route("/customer/orders/<int:order_id>/delete", methods=["POST"])
@role_required("customer")
def customer_delete_order(order_id):

    order = query_db(
        "SELECT * FROM orders WHERE id=%s AND customer_id=%s",
        (order_id, session["user_id"]),
        fetchone=True,
    )

    if not order:
        abort(404)

    if order["status"] not in ("pending", "rejected"):
        flash("Only Pending or Rejected orders can be deleted.", "error")
        return redirect(url_for("customer_orders"))

    # Restore stock
    items = query_db(
        "SELECT product_id, quantity FROM order_items WHERE order_id=%s",
        (order_id,),
    )

    for item in items:
        query_db(
            "UPDATE products SET stock = stock + %s WHERE id=%s",
            (item["quantity"], item["product_id"]),
            commit=True,
        )

    # Delete notifications
    query_db(
        "DELETE FROM notifications WHERE order_id=%s",
        (order_id,),
        commit=True,
    )

    # Delete order items
    query_db(
        "DELETE FROM order_items WHERE order_id=%s",
        (order_id,),
        commit=True,
    )

    # Delete order
    query_db(
        "DELETE FROM orders WHERE id=%s AND customer_id=%s",
        (order_id, session["user_id"]),
        commit=True,
    )

    flash(f"Order {order['order_number']} deleted successfully.", "success")

    return redirect(url_for("customer_orders"))

@app.route("/product-builder/dashboard")
@role_required("product_builder")
def builder_dashboard():
    products = query_db(
        """
        SELECT *
        FROM products
        WHERE builder_id = %s
        ORDER BY updated_at DESC, id DESC
        """,
        (session["user_id"],),
    )
    metrics = {
        "product_count": len(products),
        "active_count": sum(1 for product in products if product["is_active"]),
        "low_stock_count": sum(1 for product in products if product["stock"] <= 5),
        "inventory_value": round(sum(float(product["price"]) * product["stock"] for product in products), 2),
    }
    return render_template(
        "product_builder/dashboard.html",
        products=products,
        metrics=metrics,
    )


@app.route("/product-builder/products/new", methods=["GET", "POST"])
@role_required("product_builder")
def builder_create_product():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        price = request.form.get("price", "").strip()
        stock = request.form.get("stock", "").strip()
        description = request.form.get("description", "").strip()
        selected_image = request.form.get("selected_image", "default.png")
        is_active = 1 if request.form.get("is_active") == "on" else 0
        uploaded_image = save_product_image(request.files.get("image"))
        image_name = uploaded_image or selected_image or "default.png"

        query_db(
            """
            INSERT INTO products (builder_id, name, category, price, stock, description, image, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (session["user_id"], name, category, price, stock, description, image_name, is_active),
            commit=True,
        )
        flash("Product created successfully.", "success")
        return redirect(url_for("builder_dashboard"))

    return render_template(
        "product_builder/product_form.html",
        product=None,
        categories=CATEGORY_OPTIONS,
        image_choices=IMAGE_CHOICES,
        form_title="Add a new clothing product",
    )


@app.route("/product-builder/products/<int:product_id>/edit", methods=["GET", "POST"])
@role_required("product_builder")
def builder_edit_product(product_id):
    product = query_db(
        "SELECT * FROM products WHERE id = %s AND builder_id = %s",
        (product_id, session["user_id"]),
        fetchone=True,
    )
    if not product:
        abort(404)

    if request.method == "POST":
        selected_image = request.form.get("selected_image", product["image"])
        uploaded_image = save_product_image(request.files.get("image"))
        image_name = uploaded_image or selected_image or product["image"]
        is_active = 1 if request.form.get("is_active") == "on" else 0

        query_db(
            """
            UPDATE products
            SET name = %s, category = %s, price = %s, stock = %s, description = %s, image = %s, is_active = %s
            WHERE id = %s AND builder_id = %s
            """,
            (
                request.form.get("name", "").strip(),
                request.form.get("category", "").strip(),
                request.form.get("price", "").strip(),
                request.form.get("stock", "").strip(),
                request.form.get("description", "").strip(),
                image_name,
                is_active,
                product_id,
                session["user_id"],
            ),
            commit=True,
        )
        flash("Product updated successfully.", "success")
        return redirect(url_for("builder_dashboard"))

    return render_template(
        "product_builder/product_form.html",
        product=product,
        categories=CATEGORY_OPTIONS,
        image_choices=IMAGE_CHOICES,
        form_title="Edit clothing product",
    )


@app.route("/product-builder/products/<int:product_id>/delete", methods=["POST"])
@role_required("product_builder")
def builder_delete_product(product_id):
    existing_order = query_db(
        """
        SELECT oi.id
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE p.id = %s AND p.builder_id = %s
        LIMIT 1
        """,
        (product_id, session["user_id"]),
        fetchone=True,
    )
    if existing_order:
        query_db(
            "UPDATE products SET is_active = 0 WHERE id = %s AND builder_id = %s",
            (product_id, session["user_id"]),
            commit=True,
        )
        flash("Product archived because it already exists in order history.", "success")
    else:
        query_db(
            "DELETE FROM products WHERE id = %s AND builder_id = %s",
            (product_id, session["user_id"]),
            commit=True,
        )
        flash("Product deleted.", "success")
    return redirect(url_for("builder_dashboard"))


def get_delivery_orders(where_clause, params):
    return query_db(
        f"""
        SELECT o.*, c.full_name AS customer_name, c.phone AS customer_phone,
               GROUP_CONCAT(CONCAT(oi.product_name, ' x', oi.quantity) SEPARATOR ', ') AS items_summary
        FROM orders o
        JOIN users c ON c.id = o.customer_id
        LEFT JOIN order_items oi ON oi.order_id = o.id
        WHERE {where_clause}
        GROUP BY o.id
        ORDER BY o.created_at DESC
        """,
        params,
    )


@app.route("/delivery/dashboard")
@role_required("delivery_person")
def delivery_dashboard():
    available_orders = get_delivery_orders("o.status = 'pending' AND o.delivery_person_id IS NULL", ())
    assigned_orders = get_delivery_orders(
        "o.delivery_person_id = %s OR (o.delivery_person_id = %s AND o.status = 'rejected')",
        (session["user_id"], session["user_id"]),
    )
    notifications = get_user_notifications(session["user_id"], limit=12)
    return render_template(
        "delivery_person/dashboard.html",
        available_orders=available_orders,
        assigned_orders=assigned_orders,
        notifications=notifications,
    )


def get_order_for_delivery(order_id):
    return query_db("SELECT * FROM orders WHERE id = %s", (order_id,), fetchone=True)


@app.route("/delivery/orders/<int:order_id>/accept", methods=["POST"])
@role_required("delivery_person")
def delivery_accept(order_id):
    order = get_order_for_delivery(order_id)
    if not order or order["status"] != "pending" or order["delivery_person_id"] is not None:
        flash("This order cannot be accepted.", "error")
        return redirect(url_for("delivery_dashboard"))

    query_db(
        """
        UPDATE orders
        SET status = 'accepted', delivery_person_id = %s
        WHERE id = %s
        """,
        (session["user_id"], order_id),
        commit=True,
    )
    create_notification(
        order["customer_id"],
        order_id,
        "Demo SMS: Delivery accepted",
        f"Good news. Your order {order['order_number']} has been accepted by a delivery partner and is now moving forward.",
    )
    create_notification(
        session["user_id"],
        order_id,
        "Demo SMS: Delivery accepted",
        f"You accepted order {order['order_number']}. Use the dashboard map link to navigate to the customer address.",
    )
    flash("Order accepted.", "success")
    return redirect(url_for("delivery_dashboard"))


@app.route("/delivery/orders/<int:order_id>/reject", methods=["POST"])
@role_required("delivery_person")
def delivery_reject(order_id):
    order = get_order_for_delivery(order_id)
    if not order or order["status"] not in ("pending", "accepted"):
        flash("This order cannot be rejected.", "error")
        return redirect(url_for("delivery_dashboard"))
    if order["delivery_person_id"] not in (None, session["user_id"]):
        flash("This order belongs to another delivery partner.", "error")
        return redirect(url_for("delivery_dashboard"))

    query_db(
        """
        UPDATE orders
        SET status = 'rejected', delivery_person_id = %s
        WHERE id = %s
        """,
        (session["user_id"], order_id),
        commit=True,
    )
    create_notification(
        order["customer_id"],
        order_id,
        "Demo SMS: Delivery status updated",
        f"Order {order['order_number']} was rejected by a delivery partner. The request remains visible in the system for demo flow tracking.",
    )
    create_notification(
        session["user_id"],
        order_id,
        "Demo SMS: Delivery rejected",
        f"You rejected order {order['order_number']}. It is marked as rejected in the demo workflow.",
    )
    flash("Order rejected.", "success")
    return redirect(url_for("delivery_dashboard"))


@app.route("/delivery/orders/<int:order_id>/deliver", methods=["POST"])
@role_required("delivery_person")
def delivery_deliver(order_id):
    order = get_order_for_delivery(order_id)
    if not order or order["status"] != "accepted" or order["delivery_person_id"] != session["user_id"]:
        flash("This order cannot be marked as delivered.", "error")
        return redirect(url_for("delivery_dashboard"))

    query_db(
        """
        UPDATE orders
        SET status = 'delivered', delivered_at = NOW()
        WHERE id = %s
        """,
        (order_id,),
        commit=True,
    )
    create_notification(
        order["customer_id"],
        order_id,
        "Demo SMS: Delivered successfully",
        f"Your order {order['order_number']} has been delivered successfully. Thank you for shopping with ClothMart.",
    )
    create_notification(
        session["user_id"],
        order_id,
        "Demo SMS: Delivery completed",
        f"Order {order['order_number']} has been marked delivered. The customer received a demo SMS confirmation.",
    )
    flash("Order marked as delivered.", "success")
    return redirect(url_for("delivery_dashboard"))


@app.errorhandler(403)
def forbidden(_error):
    return "Access denied", 403


if __name__ == "__main__":
    app.run(debug=True, port=5050)
