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

    # ------------ Packages: detail + add/remove items ------------
    @app.get("/packages/<int:package_id>")
    def packages_detail(package_id: int):
        from models import PackageHead as PH, PackageLine as PL, Item as IT, ShipmentLine as SL, ShipmentHead as SH

        pkg = db.session.get(PH, package_id)
        if not pkg:
            abort(404, "Package not found")

        # find parent shipment (each package belongs to one shipment via ShipmentLine.unique(package_no))
        shipment_id = db.session.execute(
            db.select(SL.shipment_no).where(SL.package_no == package_id)
        ).scalar_one_or_none()
        shipment = db.session.get(SH, shipment_id) if shipment_id else None

        # lines in this package with item details
        lines = db.session.execute(
            db.select(PL, IT)
              .join(IT, IT.id == PL.item_no)
              .where(PL.package_no == package_id)
              .order_by(IT.description.asc())
        ).all()  # list of (PackageLine, Item)

        # all items to choose from (simple select for now)
        all_items = db.session.execute(db.select(IT).order_by(IT.description)).scalars().all()

        # locked when shipment shipped or package not open
        locked = (pkg.status != "open") or (shipment and shipment.status != "open")

        return render_template(
            "package_detail.html",
            pkg=pkg,
            shipment=shipment,
            lines=lines,
            all_items=all_items,
            locked=locked,
        )

    @app.post("/packages/<int:package_id>/items")
    def packages_add_item(package_id: int):
        from models import PackageHead as PH, PackageLine as PL, Item as IT, ShipmentLine as SL, ShipmentHead as SH

        pkg = db.session.get(PH, package_id)
        if not pkg:
            abort(404, "Package not found")

        # parent shipment and lock check
        shipment_id = db.session.execute(
            db.select(SL.shipment_no).where(SL.package_no == package_id)
        ).scalar_one_or_none()
        shipment = db.session.get(SH, shipment_id) if shipment_id else None

        if pkg.status != "open" or (shipment and shipment.status != "open"):
            abort(400, "Package cannot be modified (shipment/pack locked)")

        # read form inputs
        try:
            item_id = int(request.form.get("item_id", "0"))
            qty = int(request.form.get("quantity", "0"))
        except ValueError:
            abort(400, "Invalid quantity")

        if qty <= 0:
            abort(400, "Quantity must be positive")

        item = db.session.get(IT, item_id)
        if not item:
            abort(400, "Item not found")

        # enforce uniqueness (package_no, item_no): update quantity if exists, else insert with next line_no
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
        # redirect back to package page
        return redirect(url_for("packages_detail", package_id=package_id))

    @app.post("/packages/<int:package_id>/items/<int:item_id>/delete")
    def packages_delete_item(package_id: int, item_id: int):
        from models import PackageHead as PH, PackageLine as PL, ShipmentLine as SL, ShipmentHead as SH

        pkg = db.session.get(PH, package_id)
        if not pkg:
            abort(404, "Package not found")

        # parent shipment and lock check
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

    # ------------ Read-only REST API (API key protected) ------------
    from flask import Blueprint, jsonify

    api = Blueprint("api", __name__)

    def _require_api_key():
        key = request.headers.get("X-API-KEY") or request.args.get("api_key")
        if key != app.config.get("API_KEY"):
            abort(401, "Invalid or missing API key")

    def _dt(o):
        return o.isoformat() if o else None

    @api.get("/health")
    def api_health():
        _require_api_key()
        # quick DB roundtrip
        db.session.execute(db.text("SELECT 1"))
        return jsonify({"status": "ok"})

    @api.get("/shipments")
    def api_shipments():
        _require_api_key()
        from models import ShipmentHead as SH, ShipmentLine as SL

        # package counts per shipment
        counts = dict(
            db.session.execute(
                db.select(SL.shipment_no, db.func.count(SL.package_no))
                  .group_by(SL.shipment_no)
            ).all()
        )

        rows = db.session.execute(
            db.select(SH).order_by(SH.id.desc())
        ).scalars().all()

        data = [{
            "id": s.id,
            "status": s.status,
            "shipment_number": s.shipment_number,
            "created_at": _dt(s.created_at),
            "package_count": counts.get(s.id, 0),
        } for s in rows]

        return jsonify(data)

    @api.get("/shipments/<int:shipment_id>")
    def api_shipment_detail(shipment_id: int):
        _require_api_key()
        from models import ShipmentHead as SH, ShipmentLine as SL, PackageHead as PH

        s = db.session.get(SH, shipment_id)
        if not s:
            abort(404, "Shipment not found")

        packages = db.session.execute(
            db.select(SL.line_no, PH)
              .join(PH, PH.id == SL.package_no)
              .where(SL.shipment_no == s.id)
              .order_by(SL.line_no.asc())
        ).all()

        return jsonify({
            "id": s.id,
            "status": s.status,
            "shipment_number": s.shipment_number,
            "created_at": _dt(s.created_at),
            "packages": [
                {
                    "line_no": ln,
                    "id": p.id,
                    "status": p.status,
                    "shipment_number": p.shipment_number,
                    "created_at": _dt(p.created_at),
                } for (ln, p) in packages
            ],
        })

    @api.get("/packages/<int:package_id>")
    def api_package_detail(package_id: int):
        _require_api_key()
        from models import PackageHead as PH, PackageLine as PL, Item as IT, ShipmentLine as SL

        p = db.session.get(PH, package_id)
        if not p:
            abort(404, "Package not found")

        # parent shipment id (via ShipmentLine.unique(package_no))
        shipment_id = db.session.execute(
            db.select(SL.shipment_no).where(SL.package_no == package_id)
        ).scalar_one_or_none()

        lines = db.session.execute(
            db.select(PL, IT)
              .join(IT, IT.id == PL.item_no)
              .where(PL.package_no == package_id)
              .order_by(PL.line_no.asc())
        ).all()

        return jsonify({
            "id": p.id,
            "status": p.status,
            "shipment_id": shipment_id,
            "shipment_number": p.shipment_number,
            "created_at": _dt(p.created_at),
            "items": [
                {
                    "line_no": pl.line_no,
                    "item_id": it.id,
                    "description": it.description,
                    "quantity": pl.quantity,
                } for (pl, it) in lines
            ],
        })

    # register the blueprint
    app.register_blueprint(api, url_prefix="/api")

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
