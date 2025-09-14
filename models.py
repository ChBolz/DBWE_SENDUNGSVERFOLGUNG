"""ORM-Modelle für Nutzer, Shipments, Packages, Items und Bestand.

Design-Notizen:
- Status-Felder nutzen ein gemeinsames DB-Enum 'package_status' (Postgres: Typ existiert global).
- line_no in *Line*-Tabellen ist anwendungsseitig verwaltet (Composite-PK statt autoincrement).
- Referentielle Integrität via ForeignKeys; Löschkaskaden überwiegend über ORM-Relationships.
- Zeitstempel in UTC.
"""

from datetime import datetime
from typing import Optional

from flask_sqlalchemy import SQLAlchemy  # Hinweis: scheint ungenutzt; ggf. entfernen.
from sqlalchemy import UniqueConstraint, CheckConstraint, Enum, ForeignKey
from sqlalchemy.orm import relationship, Mapped, mapped_column
from app import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


class User(db.Model, UserMixin):
    """App-User inkl. Login-Integration (Flask-Login) und Passwort-Hashing."""
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # Bidirektionale Beziehungen (Owner-Pattern); ORM-seitig mit Orphan-Delete.
    shipments = relationship("ShipmentHead", back_populates="creator", cascade="all,delete-orphan")
    packages = relationship("PackageHead", back_populates="creator", cascade="all,delete-orphan")

    # Passwort-Helfer (Werkzeug kümmert sich um Salt/Algorithmus).
    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)


class ShipmentHead(db.Model):
    """Shipment-Header (1:n zu ShipmentLine; vergibt bei Versand eine Geschäftsnummer)."""
    __tablename__ = "shipment_head"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(
        Enum("open", "packed", "shipped", name="package_status"),  # geteilter Enum-Typ
        default="open",
        nullable=False,
    )
    # Geschäftsnummer: erst bei Versand gesetzt; muss dann eindeutig sein.
    shipment_number: Mapped[Optional[str]] = mapped_column(db.String(50), unique=True, nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow, nullable=False)

    creator = relationship("User", back_populates="shipments")

    # Association-Objekt für Packages (Zeilen enthalten die Zuordnung + line_no).
    lines = relationship("ShipmentLine", back_populates="shipment", cascade="all,delete-orphan")

    # Bequemer, schreibgeschützter Zugriff auf zugehörige Packages.
    packages = relationship(
        "PackageHead",
        secondary="shipment_line",
        primaryjoin="ShipmentHead.id==ShipmentLine.shipment_no",
        secondaryjoin="PackageHead.id==ShipmentLine.package_no",
        viewonly=True,
    )


class PackageHead(db.Model):
    """Package-Header (1:n zu PackageLine; optional 1:1 Link zu Shipment via ShipmentLine)."""
    __tablename__ = "package_head"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(
        Enum("open", "packed", "shipped", name="package_status"),  # gleicher Enum-Typ wie oben
        default="open",
        nullable=False,
    )
    # Geschäftsnummer wird beim Versand aus Shipment gespiegelt (kein FK, reine Kopie).
    shipment_number: Mapped[Optional[str]] = mapped_column(db.String(50), nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow, nullable=False)

    creator = relationship("User", back_populates="packages")

    # Ein Package darf höchstens in einem Shipment vorkommen (durch UNIQUE in ShipmentLine erzwungen).
    shipment_link = relationship("ShipmentLine", back_populates="package", uselist=False)

    # Positionen (Items) im Package.
    lines = relationship("PackageLine", back_populates="package", cascade="all,delete-orphan")


class ShipmentLine(db.Model):
    """Zuordnung Package -> Shipment mit positionsweiser Nummerierung."""
    __tablename__ = "shipment_line"

    # Composite-PK: (shipment_no, line_no); line_no wird extern verwaltet.
    shipment_no: Mapped[int] = mapped_column(ForeignKey("shipment_head.id"), primary_key=True)  # noqa: F821 if static check
    line_no: Mapped[int] = mapped_column(primary_key=True)

    # UNIQUE stellt sicher: ein Package kann nur in genau einem Shipment verlinkt sein.
    package_no: Mapped[int] = mapped_column(ForeignKey("package_head.id"), nullable=False, unique=True)

    shipment = relationship("ShipmentHead", back_populates="lines")
    package = relationship("PackageHead", back_populates="shipment_link")


class Item(db.Model):
    """Artikelstammdaten (Beschreibung, Basiseinheit)."""
    __tablename__ = "item"

    id: Mapped[int] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(db.String(255), nullable=False)
    base_unit: Mapped[Optional[str]] = mapped_column(db.String(32), nullable=True)

    lines = relationship("PackageLine", back_populates="item")


class Stock(db.Model):
    """Einfacher Lagerbestand je Item (1:1 zu Item)."""
    __tablename__ = "stock"

    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"), primary_key=True)
    quantity_on_hand: Mapped[int] = mapped_column(db.Integer, nullable=False)

    item = relationship("Item")


class PackageLine(db.Model):
    """Position in einem Package (Item, Menge, positionsweise Nummer)."""
    __tablename__ = "package_line"

    # Composite-PK: (package_no, line_no); line_no wird extern vergeben.
    package_no: Mapped[int] = mapped_column(ForeignKey("package_head.id"), primary_key=True)
    line_no: Mapped[int] = mapped_column(primary_key=True)

    item_no: Mapped[int] = mapped_column(ForeignKey("item.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(db.Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_packageline_qty_pos"),          # keine Null-/Negativmengen
        UniqueConstraint("package_no", "item_no", name="uq_packageline_pkg_item"),  # Deduplizierung pro Package
    )

    package = relationship("PackageHead", back_populates="lines")
    item = relationship("Item", back_populates="lines")
