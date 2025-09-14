"""Flask-App für einfaches Shipment-/Packaging-Tracking.

Hinweise für Leser:
- App-Factory-Pattern mit global initialisierten Flask-Extensions.
- Routen nutzen schlichtes Server-Side-Rendering; kein CSRF-Token-Setup (für Prod ergänzen).
- Status-Lifecycle: Shipment: open -> shipped; Package: open -> packed -> (implizit) shipped.
- Bestandsprüfung ist logisch korrekt, aber ohne transaktionale Sperren (Race Conditions möglich).
"""

from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, abort, jsonify, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import (
    LoginManager, login_user, login_required, logout_user, current_user
)
from flask import Blueprint
from config import Config

# Globale Extensions – echte Instanzierung in create_app()
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

def create_app():
    """Erzeugt und konfiguriert die Flask-App (DB, Migrations, Auth, Blueprints)."""
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)

    # Flask-Login: einfache Session-basierte Auth
    login_manager.init_app(app)
    login_manager.login_view = "login"  # Redirect-Ziel bei @login_required
    login_manager.login_message_category = "info"

    # Modelle importieren, damit Metadata für Alembic bekannt ist
    from models import (
        User, ShipmentHead, PackageHead, ShipmentLine, Item, PackageLine, Stock
    )  # noqa: F401

    @login_manager.user_loader
    def load_user(user_id: str):
        """Session-Rehydrierung eines Users via Primärschlüssel."""
        return db.session.get(User, int(user_id))

    # -------- Public --------
    @app.route("/")
    def index():
        """Startseite (öffentlich)."""
        return render_template("index.html")

    # -------- Auth --------
    @app.get("/login")
    def login():
        """Login-Formular; angemeldete Nutzer direkt zur Übersicht."""
        if current_user.is_authenticated:
            return redirect(url_for("shipments_list"))
        return render_template("login.html")

    @app.post("/login")
    def login_post():
        """Form-Login mit konstanter Fehlermeldung (keine User-Enumeration)."""
        from models import User
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.session.execute(
            db.select(User).where(User.username == username)
        ).scalar_one_or_none()

        if not user or not user.check_password(password):
            # 401 signalisiert Auth-Fehler; Response ist absichtlich generisch
            return render_template("login.html", message="Invalid username or password"), 401

        login_user(user)
        # Nur interne relative Next-URLs zulassen (einfacher Open-Redirect-Schutz)
        next_url = request.args.get("next")
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for("shipments_list"))

    @app.get("/register")
    def register():
        """Registrierungsformular; bestehende Sessions werden umgeleitet."""
        if current_user.is_authenticated:
            return redirect(url_for("shipments_list"))
        return render_template("register.html")

    @app.post("/register")
    def register_post():
        """Einfache Selbst-Registrierung ohne E-Mail-Verifikation (nur Demo)."""
        from models import User
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not username or not email or not password:
            return render_template("register.html", message="All fields are required"), 400

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
        """Beendet die Session und führt auf die Startseite zurück."""
        logout_user()
        return redirect(url_for("index"))

    # ------------ Helpers ------------
    def _get_shipment_or_404(shipment_id: int):
        """Lädt ein Shipment oder bricht mit 404 ab (zentralisierte Lookup-Logik)."""
        from models import ShipmentHead
        sh = db.session.get(ShipmentHead, shipment_id)
        if not sh:
            abort(404, "Shipment not found")
        return sh

    # -------- Items (private) --------
    @app.get("/items")
    @login_required
    def list_items():
        """Item-Stammdaten (nur read-only Übersicht)."""
        from models import Item as ItemModel
        items = db.session.execute(db.select(ItemModel).order_by(ItemModel.id)).scalars().all()
        return render_template("items.html", items=items)

    # ------------ Shipments (private) ------------
    @app.get("/shipments")
    @login_required
    def shipments_list():
        """Liste aller Shipments (neuste zuerst)."""
        from models import ShipmentHead as SH
        rows = db.session.execute(
            db.select(SH).order_by(SH.id.desc())
        ).scalars().all()
        return render_template("shipments.html", shipments=rows)

    @app.get("/shipments/new")
    @login_required
    def shipments_new():
        """Formular zur Erstellung eines Shipments."""
        return render_template("shipment_new.html")

    @app.post("/shipments/new")
    @login_required
    def shipments_create():
        """Erzeugt ein neues Shipment im Status 'open' (erstellt vom aktuellen Nutzer)."""
        from models import ShipmentHead as SH
        sh = SH(created_by=current_user.id)  # Status-Default via Modell
        db.session.add(sh)
        db.session.commit()
        return render_template("shipment_created.html", shipment=sh)

    @app.get("/shipments/<int:shipment_id>")
    @login_required
    def shipments_detail(shipment_id):
        """Details inkl. zugeordneter Packages (über Lines verknüpft)."""
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
        """Fügt ein neues (leeres) Package dem Shipment hinzu.

        Achtung: line_no wird via MAX+1 bestimmt -> bei parallelen Adds potentielles Rennen.
        """
        from models import ShipmentLine as SL, PackageHead as PH
        sh = _get_shipment_or_404(shipment_id)
        if sh.status != "open":
            abort(400, "Shipment is not open")

        # Neues Package erzeugen und direkt mit Shipment verknüpfen
        pkg = PH(status="open", created_by=current_user.id, created_at=datetime.utcnow())
        db.session.add(pkg)
        db.session.flush()  # ID des Packages sicherstellen

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
        """Transition 'open' -> 'shipped'; vergibt Shipment-Nummer und spiegelt Status auf Packages.

        Hinweis: Zeitpunkt in Nummer codiert; keine Idempotenz bei Mehrfachaufruf.
        """
        from models import ShipmentLine as SL, PackageHead as PH
        sh = _get_shipment_or_404(shipment_id)
        if sh.status != "open":
            abort(400, "Shipment already shipped")

        sn = f"SN{datetime.utcnow():%Y%m%d}-{sh.id}-{datetime.utcnow():%H%M%S}"
        sh.status = "shipped"
        sh.shipment_number = sn

        # Zugeordnete Packages massenaktualisieren
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
        """Entfernt die Verknüpfung und löscht das Package (nur solange Shipment 'open')."""
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
        """Package-Detailseite inkl. enthaltenen Items und Lock-Status."""
        from models import PackageHead as PH, PackageLine as PL, Item as IT, ShipmentLine as SL, ShipmentHead as SH
        pkg = db.session.get(PH, package_id)
        if not pkg:
            abort(404, "Package not found")

        # Zugehöriges Shipment (falls vorhanden) zur Lock-Berechnung laden
        shipment_id = db.session.execute(
            db.select(SL.shipment_no).where(SL.package_no == package_id)
        ).scalar_one_or_none()
        shipment = db.session.get(SH, shipment_id) if shipment_id else None

        lines = db.session.execute(
            db.select(PL, IT).join(IT, IT.id == PL.item_no).where(PL.package_no == package_id).order_by(IT.description.asc())
        ).all()
        all_items = db.session.execute(db.select(IT).order_by(IT.description)).scalars().all()

        # UI-Lock, wenn Package oder Shipment nicht 'open' ist
        locked = (pkg.status != "open") or (shipment and shipment.status != "open")
        return render_template("package_detail.html", pkg=pkg, shipment=shipment, lines=lines, all_items=all_items, locked=locked)

    @app.post("/packages/<int:package_id>/items")
    @login_required
    def packages_add_item(package_id: int):
        """Fügt ein Item in Menge qty in ein Package ein (mit Bestands-/Reservierungsprüfung).

        Randfälle: ungültige IDs, qty<=0, nicht vorhandenes Item/Package -> leiser Redirect.
        Race: Reservierung basiert auf SUM(...) über 'open' Shipments; zwischen Check und Commit möglich.
        """
        from models import PackageHead as PH, PackageLine as PL, Item as IT, ShipmentLine as SL, ShipmentHead as SH, Stock as ST

        pkg = db.session.get(PH, package_id)
        if not pkg:
            abort(404, "Package not found")

        # Parent-Shipment prüfen -> schreibtauglicher Zustand?
        shipment_id = db.session.execute(
            db.select(SL.shipment_no).where(SL.package_no == package_id)
        ).scalar_one_or_none()
        shipment = db.session.get(SH, shipment_id) if shipment_id else None
        if pkg.status != "open" or (shipment and shipment.status != "open"):
            abort(400, "Package cannot be modified (shipment/pack locked)")

        # Eingaben parsen/validieren
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

        # --- Bestandsprüfung (on hand vs. bereits reserviert in offenen Shipments) ---
        stock_row = db.session.get(ST, item_id)
        on_hand = stock_row.quantity_on_hand if stock_row else 0

        reserved = db.session.execute(
            db.select(db.func.coalesce(db.func.sum(PL.quantity), 0))
            .join(PH, PH.id == PL.package_no)
            .join(SL, SL.package_no == PH.id)
            .join(SH, SH.id == SL.shipment_no)
            .where(SH.status == "open", PL.item_no == item_id)
        ).scalar_one()

        if reserved + qty > on_hand:
            # Kein Fehlertext, nur Rückkehr zur Detailseite (UI kann Status kommunizieren)
            return redirect(url_for("packages_detail", package_id=package_id))

        # Upsert der Position im Package
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
        """Entfernt eine Item-Zeile aus einem Package (nur im offenen Zustand)."""
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
        """Transition Package 'open' -> 'packed' (Vorstufe zu 'shipped')."""
        from models import PackageHead as PH
        pkg = db.session.get(PH, package_id)
        if not pkg:
            abort(404, "Package not found")
        if pkg.status != "open":
            abort(400, "Package not open")
        pkg.status = "packed"
        db.session.commit()
        return redirect(url_for("packages_detail", package_id=package_id))

    # ---------------------- API BLUEPRINT ----------------------
    api = Blueprint("api", __name__, url_prefix="/api")

    def _require_api_key():
        """Einfacher API-Key-Check (Header/Query). Für Prod: Ratenbegrenzung & stärkere Auth erwägen."""
        key = request.headers.get("X-API-KEY") or request.args.get("api_key")
        if not key or key != current_app.config.get("API_KEY", "dev-api-key"):
            return jsonify(error="Unauthorized"), 401

    @api.get("/health")
    def api_health():
        """Lightweight-Healthcheck inkl. trivialem DB-Ping."""
        maybe_err = _require_api_key()
        if maybe_err:
            return maybe_err
        db.session.execute(db.select(db.literal(1))).scalar_one()
        return jsonify(status="ok")

    @api.get("/shipments")
    def api_shipments():
        """Aggregierte Shipment-Liste inkl. Package-Anzahl (LEFT JOIN + GROUP BY)."""
        maybe_err = _require_api_key()
        if maybe_err:
            return maybe_err
        from models import ShipmentHead as SH, ShipmentLine as SL
        rows = db.session.execute(
            db.select(
                SH.id, SH.status, SH.shipment_number, SH.created_by, SH.created_at,
                db.func.count(SL.package_no).label("package_count"),
            ).join(SL, SL.shipment_no == SH.id, isouter=True)
             .group_by(SH.id).order_by(SH.id.desc())
        ).all()
        data = [
            {
                "id": r.id,
                "status": r.status,
                "shipment_number": r.shipment_number,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "package_count": int(r.package_count or 0),
            }
            for r in rows
        ]
        return jsonify(data)

    @api.get("/shipments/<int:shipment_id>")
    def api_shipment_detail(shipment_id: int):
        """Detail eines Shipments inkl. zugehöriger Packages (ohne Package-Inhalte)."""
        maybe_err = _require_api_key()
        if maybe_err:
            return maybe_err
        from models import ShipmentHead as SH, ShipmentLine as SL
        sh = db.session.get(SH, shipment_id)
        if not sh:
            return jsonify(error="Not found"), 404
        pkg_rows = db.session.execute(
            db.select(SL.line_no, SL.package_no)
              .where(SL.shipment_no == sh.id)
              .order_by(SL.line_no.asc())
        ).all()
        return jsonify(
            {
                "id": sh.id,
                "status": sh.status,
                "shipment_number": sh.shipment_number,
                "created_by": sh.created_by,
                "created_at": sh.created_at.isoformat() if sh.created_at else None,
                "packages": [{"line_no": ln, "package_id": pid} for (ln, pid) in pkg_rows],
            }
        )

    @api.get("/packages/<int:package_id>")
    def api_package_detail(package_id: int):
        """Package-Detail inkl. Positionsliste (sortiert nach line_no)."""
        maybe_err = _require_api_key()
        if maybe_err:
            return maybe_err
        from models import PackageHead as PH, PackageLine as PL, Item as IT
        pkg = db.session.get(PH, package_id)
        if not pkg:
            return jsonify(error="Not found"), 404
        lines = db.session.execute(
            db.select(PL, IT)
              .join(IT, IT.id == PL.item_no)
              .where(PL.package_no == package_id)
              .order_by(PL.line_no.asc())
        ).all()
        return jsonify(
            {
                "id": pkg.id,
                "status": pkg.status,
                "shipment_number": pkg.shipment_number,
                "created_by": pkg.created_by,
                "created_at": pkg.created_at.isoformat() if pkg.created_at else None,
                "lines": [
                    {
                        "line_no": pl.line_no,
                        "item_id": it.id,
                        "description": it.description,
                        "base_unit": it.base_unit,
                        "quantity": pl.quantity,
                    }
                    for (pl, it) in lines
                ],
            }
        )

    # API registrieren
    app.register_blueprint(api)

    # CLI-Commands anhängen
    register_cli(app)
    return app


def register_cli(app):
    """CLI-Kommandos für Demo-Stammdaten/Bestand."""
    @app.cli.command("seed-items")
    def seed_items():
        """Legt drei Beispiel-Items an (idempotent)."""
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
        """Baut initialen Bestand von 100 je Item auf (idempotent über PK)."""
        from models import Item, Stock
        items = db.session.execute(db.select(Item)).scalars().all()
        for it in items:
            if not db.session.get(Stock, it.id):
                db.session.add(Stock(item_id=it.id, quantity_on_hand=100))
        db.session.commit()
        print("Seeded stock with 100 units per item.")


if __name__ == "__main__":
    # Entwicklungsstartpunkt; debug=True nicht für Produktion geeignet.
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
