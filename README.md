# ClothMart - Flask + MySQL Clothing Marketplace

ClothMart is a clothing-only e-commerce demo built with Python, Flask, HTML, CSS, JavaScript, and MySQL. It includes three connected roles inside one application:

- `product_builder` for product CRUD
- `customer` for shopping and order placement
- `delivery_person` for order acceptance, rejection, and delivery completion

The UI is modern and marketplace-inspired, while keeping the codebase compact and understandable.

## Features

- Flask session-based authentication
- Role-based route guards
- Password hashing with Werkzeug
- MySQL integration through `Flask-MySQLdb`
- Customer registration with phone number support
- Customer cart and checkout flow
- Order, order item, and notification tracking
- Demo in-app SMS style notifications for:
  - order placed
  - order accepted
  - order rejected
  - order delivered
- Delivery dashboard with customer address, GPS coordinates, and Leaflet/OpenStreetMap visibility
- Product Builder dashboard for clothing CRUD with bundled images or uploaded images

## Project Structure

```text
clothing_marketplace_app/
├── app.py
├── config.py
├── requirements.txt
├── README.md
├── database/
│   └── schema.sql
├── static/
│   ├── css/
│   │   └── style.css
│   ├── images/
│   │   ├── products/
│   │   └── ui/
│   └── js/
│       └── main.js
└── templates/
    ├── auth/
    ├── customer/
    ├── delivery_person/
    └── product_builder/
```

## Setup Instructions

1. Create a MySQL database user if needed.
2. Import the schema:

   ```sql
   SOURCE database/schema.sql;
   ```

3. Edit MySQL credentials if necessary in `config.py`, or set environment variables:

   - `MYSQL_HOST`
   - `MYSQL_USER`
   - `MYSQL_PASSWORD`
   - `MYSQL_DB`
   - `SECRET_KEY`

4. Create and activate a virtual environment.

5. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

6. Run the Flask app:

   ```bash
   python app.py
   ```

7. Open:

   ```text
   http://127.0.0.1:5000
   ```

## How to Test the Full Workflow

1. Register one account for each role:
   - customer
   - product_builder
   - delivery_person

2. Log in as `product_builder` and create clothing products.

3. Log in as `customer`, add items to cart, and place an order with shipping address and optional GPS coordinates.

4. Log in as `delivery_person`, accept or reject the order, and use the map links for location visibility.

5. Mark accepted orders as delivered to generate the delivered-success demo SMS notification for the customer.

## Notes

- Notifications are stored in the database and shown in dashboards as demo SMS messages.
- Delivery rejection is modeled as a demo status in the application and is preserved in order history.
- Bundled clothing images are included under `static/images`.
- This application is intended as a compact demo project rather than a production-hardened marketplace.
