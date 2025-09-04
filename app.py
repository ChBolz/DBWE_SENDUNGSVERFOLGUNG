from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, abort
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
        from models import Item as ItemModel
        items = db.session.execute(db.select(ItemModel).order_by(ItemModel.id)).scalars().all()
        return render_template("items.html", items=items)

    # ------------ Helpers ------------
    def _ensure_demo_user():
        u = db.session.execute(db.select(User).where(User.username == "demo")).scalar_one_or_none()
        if not u:
            u = User(username="demo", email="demo@example.com", password_hash="not-used-yet")
            db.session.add(u)
            db.session.commit()
        return u

    def _get_shipment_or_404(shipment_id: int):
        sh = db.session.get(ShipmentHead, shipment_id)
        if not sh:
            abort(404, "Shipment not found")
        return sh

    # ------------ Shipments ------------
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
        return render_template("shipment_created.html", shipment=sh)

    @app.get("/shipments/<int:shipment_id>")
    def shipments_detail(shipment_id):
        from models import ShipmentLine as SL, PackageHead as PH
        sh = _get_shipment_or_404(shipment_id)
        # packages linked via ShipmentLine
        rows = db.session.execute(
            db.select(SL.line_no, PH)
              .join(PH, PH.id == SL.package_no)
              .where(SL.shipment_no == sh.id)
              .order_by(SL.line_no.asc())
        ).all()  # list[(line_no, PackageHead)]
        return render_template("shipment_detail.html", sh=sh, rows=rows)

    @app.post("/shipments/<int:shipment_id>/packages/new")
    def shipments_add_package(shipment_id):
        from models import ShipmentLine as SL, PackageHead as PH
        sh = _get_shipment_or_404(shipment_id)
        if sh.status != "open":
            abort(400, "Shipment is not open")

        user = _ensure_demo_user()

        # 1) create a new empty package
        pkg = PH(status="open", created_by=user.id, created_at=datetime.utcnow())
        db.session.add(pkg)
        db.session.flush()  # get pkg.id

        # 2) link it to the shipment with next line number
        next_line = db.session.execute(
            db.select(db.func.coalesce(db.func.max(SL.line_no), 0) + 1)
              .where(SL.shipment_no == sh.id)
        ).scalar_one()

        link = SL(shipment_no=sh.id, line_no=next_line, package_no=pkg.id)
        db.session.add(link)
        db.session.commit()

        return redirect(url_for("shipments_detail", shipment_id=sh.id))

    @app.post("/shipments/<int:shipment_id>/ship")
    def shipments_ship(shipment_id):
        from models import ShipmentLine as SL, PackageHead as PH
        sh = _get_shipment_or_404(shipment_id)
        if sh.status != "open":
            abort(400, "Shipment already shipped")

        # generate a shipment number (simple, unique-enough)
        sn = f"SN{datetime.utcnow():%Y%m%d}-{sh.id}-{datetime.utcnow():%H%M%S}"
        sh.status = "shipped"
        sh.shipment_number = sn

        # copy number to all packages in this shipment and mark them shipped
        pkg_ids = db.session.execute(
            db.select(SL.package_no).where(SL.shipment_no == sh.id)
        ).scalars().all()

        if pkg_ids:
            db.session.execute(
                db.update(PH)
                  .where(PH.id.in_(pkg_ids))
                  .values(shipment_number=sn, status="shipped")
            )

        db.session.commit()
        return redirect(url_for("shipments_detail", shipment_id=sh.id))

    @app.post("/shipments/<int:shipment_id>/packages/<int:package_id>/delete")
    def shipments_delete_package(shipment_id, package_id):
        from models import ShipmentLine as SL, PackageHead as PH
        sh = _get_shipment_or_404(shipment_id)
        if sh.status != "open":
            abort(400, "Shipment is not open")

        # find the link; ensure this package belongs to this shipment
        link = db.session.execute(
            db.select(SL).where(
                SL.shipment_no == sh.id,
                SL.package_no == package_id
            )
        ).scalar_one_or_none()
        if not link:
            abort(404, "Package not linked to this shipment")

        # delete link first, then the package (to avoid FK issues)
        db.session.delete(link)
        pkg = db.session.get(PH, package_id)
        if pkg:
            db.session.delete(pkg)

        db.session.commit()
        return redirect(url_for("shipments_detail", shipment_id=sh.id))

    register_cli(app)
    return app


def register_cli(app):
    @app.cli.command("seed-items")
    def seed_items():
        # Import inside the command to avoid circulars
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


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
