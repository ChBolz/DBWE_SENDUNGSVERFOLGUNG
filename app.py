from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, abort, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import (
    LoginManager, login_user, login_required, logout_user, current_user
)
from config import Config

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)

    # --- Flask-Login setup ---
    login_manager.init_app(app)
    login_manager.login_view = "login"     # where to send unauthenticated users
    login_manager.login_message_category = "info"

    # Import models here so metadata is registered
    from models import (
        User, ShipmentHead, PackageHead, ShipmentLine, Item, PackageLine
    )  # noqa: F401

    @login_manager.user_loader
    def load_user(user_id: str):
        # SQLAlchemy 2.x way to get by PK
        return db.session.get(User, int(user_id))

    # -------- Home (private) --------
    @app.route("/")
    @login_required
    def index():
        return render_template("index.html")

    # -------- Auth --------
    @app.get("/login")
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("shipments_list"))
        return render_template("login.html")

    @app.post("/login")
    def login_post():
        from models import User
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.session.execute(
            db.select(User).where(User.username == username)
        ).scalar_one_or_none()

        if not user or not user.check_password(password):
            # keep it simple: render template with a message (no flash needed)
            return render_template("login.html", message="Invalid username or password"), 401

        login_user(user)  # creates session
        next_url = request.args.get("next")
        # very small safelist: only relative paths
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for("shipments_list"))

    @app.get("/register")
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("shipments_list"))
        return render_template("register.html")

    @app.post("/register")
    def register_post():
        from models import User
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        # minimal validation
        if not username or not email or not password:
            return render_template("register.html", message="All fields are required"), 400

        # uniqueness checks
        exists = db.session.execute(
            db.select(User).where((User.username == username) | (User.email == email))
        ).scalar_one_or_none()
        if exists:
            return render_template("register.html", message="Username or email already in use"), 400

        u = User(username=username, email=email)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        login_user(u)
        return redirect(url_for("shipments_list"))

    @app.post("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    # -------- Items (private) --------
    @app.get("/items")
    @login_required
    def list_items():
        from models import Item as ItemModel
        items = db.session.execute(db.select(ItemModel).order_by(ItemModel.id)).scalars().all()
        return render_template("items.html", items=items)

    # ------------ Helpers ------------
    def _get_shipment_or_404(shipment_id: int):
        from models import ShipmentHead
        sh = db.session.get(ShipmentHead, shipment_id)
        if not sh:
            abort(404, "Shipment not found")
        return sh

    # ------------ Shipments (private) ------------
    @app.get("/shipments")
    @login_required
    def shipments_list():
        from models import ShipmentHead as SH
        rows = db.session.execute(
            db.select(SH).order_by(SH.id.desc())
        ).scalars().all()
        return render_template("shipments.html", shipments=rows)

    @app.get("/shipments/new")
    @login_required
    def shipments_new():
        return render_template("shipment_new.html")

    @app.post("/shipments/new")
    @login_required
    def shipments_create():
        from models import ShipmentHead as SH
        sh = SH(created_by=current_user.id)  # status defaults to "open"
        db.session.add(sh)
        db.session.commit()
        return render_template("shipment_created.html", shipment=sh)

    @app.get("/shipments/<int:shipment_id>")
    @login_required
    def shipments_detail(shipment_id):
        from models import ShipmentLine as SL, PackageHead as PH
        sh = _get_shipment_or_404(shipment_id)
        rows = db.session.execute(
            db.select(SL.line_no, PH)
              .join(PH, PH.id == SL.package_no)
              .where(SL.shipment_no == sh.id)
              .order_by(SL.line_no.asc())
        ).all()
        return render_template("shipment_detail.html", sh=sh, rows=rows)

    @app.post("/shipments/<int:shipment_id>/packages/new")
    @login_required
    def shipments_add_package(shipment_id):
        from models import ShipmentLine as SL, PackageHead as PH
        sh = _get_shipment_or_404(shipment_id)
        if sh.status != "open":
            abort(400, "Shipment is not open")

        pkg = PH(status="open", created_by=current_user.id, created_at=datetime.utcnow())
        db.session.add(pkg)
        db.session.flush()
        next_line = db.session.execute(
            db.select(db.func.coalesce(db.func.max(SL.line_no), 0) + 1)
              .where(SL.shipment_no == sh.id)
        ).scalar_one()
        db.session.add(SL(shipment_no=sh.id, line_no=next_line, package_no=pkg.id))
        db.session.commit()
        return redirect(url_for("shipments_detail", shipment_id=sh.id))

    @app.post("/shipments/<int:shipment_id>/ship")
    @login_required
    def shipments_ship(shipment_id):
        from models import ShipmentLine as SL, PackageHead as PH
        sh = _get_shipment_or_404(shipment_id)
        if sh.status != "open":
            abort(400, "Shipment already shipped")
        sn = f"SN{datetime.utcnow():%Y%m%d}-{sh.id}-{datetime.utcnow():%H%M%S}"
        sh.status = "shipped"; sh.shipment_number = sn
        pkg_ids = db.session.execute(
            db.select(SL.package_no).where(SL.shipment_no == sh.id)
        ).scalars().all()
        if pkg_ids:
            db.session.execute(
                db.update(PH).where(PH.id.in_(pkg_ids)).values(shipment_number=sn, status="shipped")
            )
        db.session.commit()
        return redirect(url_for("shipments_detail", shipment_id=sh.id))

    @app.post("/shipments/<int:shipment_id>/packages/<int:package_id>/delete")
    @login_required
    def shipments_delete_package(shipment_id, package_id):
        from models import ShipmentLine as SL, PackageHead as PH
        sh = _get_shipment_or_404(shipment_id)
        if sh.status != "open":
            abort(400, "Shipment is not open")
        link = db.session.execute(
            db.select(SL).where(SL.shipment_no == sh.id, SL.package_no == package_id)
        ).scalar_one_or_none()
        if not link:
            abort(404, "Package not linked to this shipment")
        db.session.delete(link)
        pkg = db.session.get(PH, package_id)
        if pkg:
            db.session.delete(pkg)
        db.session.commit()
        return redirect(url_for("shipments_detail", shipment_id=sh.id))

    # ------------ Packages: detail + items (private) ------------
    @app.get("/packages/<int:package_id>")
    @login_required
    def packages_detail(package_id: int):
        from models import PackageHead as PH, PackageLine as PL, Item as IT, ShipmentLine as SL, ShipmentHead as SH
        pkg = db.session.get(PH, package_id)
        if not pkg:
            abort(404, "Package not found")
        shipment_id = db.session.execute(
            db.select(SL.shipment_no).where(SL.package_no == package_id)
        ).scalar_one_or_none()
        shipment = db.session.get(SH, shipment_id) if shipment_id else None
        lines = db.session.execute(
            db.select(PL, IT).join(IT, IT.id == PL.item_no).where(PL.package_no == package_id).order_by(IT.description.asc())
        ).all()
        all_items = db.session.execute(db.select(IT).order_by(IT.description)).scalars().all()
        locked = (pkg.status != "open") or (shipment and shipment.status != "open")
        return render_template("package_detail.html", pkg=pkg, shipment=shipment, lines=lines, all_items=all_items, locked=locked)

    @app.post("/packages/<int:package_id>/items")
    @login_required
    def packages_add_item(package_id: int):
        from models import PackageHead as PH, PackageLine as PL, Item as IT, ShipmentLine as SL, ShipmentHead as SH, Stock as ST

        pkg = db.session.get(PH, package_id)
        if not pkg:
            abort(404, "Package not found")

        # parent shipment & lock
        shipment_id = db.session.execute(
            db.select(SL.shipment_no).where(SL.package_no == package_id)
        ).scalar_one_or_none()
        shipment = db.session.get(SH, shipment_id) if shipment_id else None
        if pkg.status != "open" or (shipment and shipment.status != "open"):
            abort(400, "Package cannot be modified (shipment/pack locked)")

        # inputs
        try:
            item_id = int(request.form.get("item_id", "0"))
            qty = int(request.form.get("quantity", "0"))
        except ValueError:
            return redirect(url_for("packages_detail", package_id=package_id))

        if qty <= 0:
            return redirect(url_for("packages_detail", package_id=package_id))

        item = db.session.get(IT, item_id)
        if not item:
            return redirect(url_for("packages_detail", package_id=package_id))

        # --- STOCK CHECK ---
        stock_row = db.session.get(ST, item_id)
        on_hand = stock_row.quantity_on_hand if stock_row else 0

        reserved = db.session.execute(
            db.select(db.func.coalesce(db.func.sum(PL.quantity), 0))
            .join(PH, PH.id == PL.package_no)
            .join(SL, SL.package_no == PH.id)
            .join(SH, SH.id == SL.shipment_no)
            .where(SH.status == "open", PL.item_no == item_id)
        ).scalar_one()

        # Will total reservation exceed on-hand if we add qty?
        if reserved + qty > on_hand:
            # Optional: show a friendly message
            return redirect(url_for("packages_detail", package_id=package_id))

        # upsert (package_no, item_no) unique
        existing = db.session.execute(
            db.select(PL).where(PL.package_no == package_id, PL.item_no == item_id)
        ).scalar_one_or_none()

        if existing:
            existing.quantity = existing.quantity + qty
        else:
            next_line = db.session.execute(
                db.select(db.func.coalesce(db.func.max(PL.line_no), 0) + 1)
                .where(PL.package_no == package_id)
            ).scalar_one()
            db.session.add(PL(package_no=package_id, line_no=next_line, item_no=item_id, quantity=qty))

        db.session.commit()
        return redirect(url_for("packages_detail", package_id=package_id))

    @app.post("/packages/<int:package_id>/items/<int:item_id>/delete")
    @login_required
    def packages_delete_item(package_id: int, item_id: int):
        from models import PackageHead as PH, PackageLine as PL, ShipmentLine as SL, ShipmentHead as SH
        pkg = db.session.get(PH, package_id)
        if not pkg:
            abort(404, "Package not found")
        shipment_id = db.session.execute(
            db.select(SL.shipment_no).where(SL.package_no == package_id)
        ).scalar_one_or_none()
        shipment = db.session.get(SH, shipment_id) if shipment_id else None
        if pkg.status != "open" or (shipment and shipment.status != "open"):
            abort(400, "Package cannot be modified (shipment/pack locked)")
        line = db.session.execute(
            db.select(PL).where(PL.package_no == package_id, PL.item_no == item_id)
        ).scalar_one_or_none()
        if not line:
            abort(404, "Line not found")
        db.session.delete(line)
        db.session.commit()
        return redirect(url_for("packages_detail", package_id=package_id))
    
    @app.post("/packages/<int:package_id>/pack")
    @login_required
    def packages_pack(package_id: int):
        from models import PackageHead as PH
        pkg = db.session.get(PH, package_id)
        if not pkg:
            abort(404, "Package not found")
        if pkg.status != "open":
            abort(400, "Package not open")
        pkg.status = "packed"
        db.session.commit()
        return redirect(url_for("packages_detail", package_id=package_id))

    # --- keep your existing API blueprint registration here (unchanged) ---
    # app.register_blueprint(api, url_prefix="/api")

    register_cli(app)
    return app


def register_cli(app):
    @app.cli.command("seed-items")
    def seed_items():
        from models import Item as ItemModel
        if db.session.execute(db.select(ItemModel)).first():
            print("Items already exist — skipping.")
            return
        db.session.add_all([
            ItemModel(description="Karton klein", base_unit="pcs"),
            ItemModel(description="Karton gross", base_unit="pcs"),
            ItemModel(description="Klebeband", base_unit="roll"),
        ])
        db.session.commit()
        print("Seeded 3 items.")

def register_cli(app):
    @app.cli.command("seed-items")
    def seed_items():
        from models import Item as ItemModel
        if db.session.execute(db.select(ItemModel)).first():
            print("Items already exist — skipping.")
            return
        db.session.add_all([
            ItemModel(description="Karton klein", base_unit="pcs"),
            ItemModel(description="Karton gross", base_unit="pcs"),
            ItemModel(description="Klebeband", base_unit="roll"),
        ])
        db.session.commit()
        print("Seeded 3 items.")

    @app.cli.command("seed-stock")
    def seed_stock():
        from models import Item, Stock
        # simple defaults: 100 of each item
        items = db.session.execute(db.select(Item)).scalars().all()
        for it in items:
            if not db.session.get(Stock, it.id):
                db.session.add(Stock(item_id=it.id, quantity_on_hand=100))
        db.session.commit()
        print("Seeded stock with 100 units per item.")


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
