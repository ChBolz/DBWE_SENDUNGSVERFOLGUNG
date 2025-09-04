from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from config import Config

db = SQLAlchemy()
migrate = Migrate()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)

    # Import models *inside* the factory so Alembic sees them, but avoid circulars
    from models import (
        User, ShipmentHead, PackageHead, ShipmentLine, Item, PackageLine
    )  # noqa: F401

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.get("/login")
    def login():
        return render_template("login.html")

    @app.post("/login")
    def login_post():
        username = request.form.get("username", "")
        return f"Login not implemented yet. You posted username='{username}'.", 501

    @app.get("/register")
    def register():
        return render_template("register.html")

    @app.post("/register")
    def register_post():
        username = request.form.get("username", "")
        email = request.form.get("email", "")
        return f"Register not implemented yet. You posted username='{username}', email='{email}'.", 501

    @app.get("/items")
    def list_items():
        # Import here to avoid module-level circular imports
        from models import Item
        items = db.session.execute(db.select(Item).order_by(Item.id)).scalars().all()
        return render_template("items.html", items=items)

   # helper: ensure a demo user exists (until real auth is added)
    def _ensure_demo_user():
        u = db.session.execute(db.select(User).where(User.username == "demo")).scalar_one_or_none()
        if not u:
            u = User(username="demo", email="demo@example.com", password_hash="not-used-yet")
            db.session.add(u)
            db.session.commit()
        return u

    @app.get("/shipments")
    def shipments_list():
        rows = db.session.execute(
            db.select(ShipmentHead).order_by(ShipmentHead.id.desc())
        ).scalars().all()
        return render_template("shipments.html", shipments=rows)

    @app.get("/shipments/new")
    def shipments_new():
        return render_template("shipment_new.html")

    @app.post("/shipments/new")
    def shipments_create():
        user = _ensure_demo_user()
        sh = ShipmentHead(created_by=user.id)  # status defaults to "open"
        db.session.add(sh)
        db.session.commit()
        # simple redirect back to the list
        return render_template("shipment_created.html", shipment=sh)

    register_cli(app)
    return app


def register_cli(app):
    @app.cli.command("seed-items")
    def seed_items():
        # Import inside the command to avoid circulars
        from models import Item
        if db.session.execute(db.select(Item)).first():
            print("Items already exist — skipping.")
            return
        db.session.add_all([
            Item(description="Karton klein", base_unit="pcs"),
            Item(description="Karton gross", base_unit="pcs"),
            Item(description="Klebeband", base_unit="roll"),
        ])
        db.session.commit()
        print("Seeded 3 items.")


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
