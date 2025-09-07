from datetime import datetime
from typing import Optional

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, CheckConstraint, Enum, ForeignKey
from sqlalchemy.orm import relationship, Mapped, mapped_column
from app import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


# -----------------------
# User
# -----------------------
class User(db.Model, UserMixin):
    __tablename__ = "user"

    # (classic style columns are fine to mix with Mapped/mapped_column)
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    # relationships to match back_populates on ShipmentHead/PackageHead
    shipments = relationship("ShipmentHead", back_populates="creator", cascade="all,delete-orphan")
    packages = relationship("PackageHead", back_populates="creator", cascade="all,delete-orphan")

    # password helpers
    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)


# -----------------------
# ShipmentHead
# -----------------------
class ShipmentHead(db.Model):
    __tablename__ = "shipment_head"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(
        Enum("open", "shipped", name="shipment_status"), default="open", nullable=False
    )
    # business shipment number (assigned on ship); unique and nullable until set
    shipment_number: Mapped[Optional[str]] = mapped_column(db.String(50), unique=True, nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow, nullable=False)

    # back to User.shipments
    creator = relationship("User", back_populates="shipments")

    # association-object pattern: shipment has many lines; each line points to a package
    lines = relationship("ShipmentLine", back_populates="shipment", cascade="all,delete-orphan")

    # convenience: list packages via lines (viewonly)
    packages = relationship(
        "PackageHead",
        secondary="shipment_line",
        primaryjoin="ShipmentHead.id==ShipmentLine.shipment_no",
        secondaryjoin="PackageHead.id==ShipmentLine.package_no",
        viewonly=True,
    )


# -----------------------
# PackageHead
# -----------------------
class PackageHead(db.Model):
    __tablename__ = "package_head"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(
        Enum("open", "shipped", name="package_status"), default="open", nullable=False
    )
    # Business shipment number gets copied here on ship (not a FK)
    shipment_number: Mapped[Optional[str]] = mapped_column(db.String(50), nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow, nullable=False)

    # back to User.packages
    creator = relationship("User", back_populates="packages")

    # a package can appear in at most one shipment (enforced in ShipmentLine via UNIQUE)
    shipment_link = relationship("ShipmentLine", back_populates="package", uselist=False)

    # package has many lines (items)
    lines = relationship("PackageLine", back_populates="package", cascade="all,delete-orphan")


# -----------------------
# ShipmentLine (composite PK)
# -----------------------
class ShipmentLine(db.Model):
    __tablename__ = "shipment_line"
    # Composite PK: (shipment_no, line_no)
    shipment_no: Mapped[int] = mapped_column(ForeignKey("shipment_head.id"), primary_key=True)
    line_no: Mapped[int] = mapped_column(primary_key=True)
    package_no: Mapped[int] = mapped_column(ForeignKey("package_head.id"), nullable=False, unique=True)

    shipment = relationship("ShipmentHead", back_populates="lines")
    package = relationship("PackageHead", back_populates="shipment_link")


# -----------------------
# Item
# -----------------------
class Item(db.Model):
    __tablename__ = "item"

    id: Mapped[int] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(db.String(255), nullable=False)
    base_unit: Mapped[Optional[str]] = mapped_column(db.String(32), nullable=True)

    lines = relationship("PackageLine", back_populates="item")


# -----------------------
# PackageLine (composite PK)
# -----------------------
class PackageLine(db.Model):
    __tablename__ = "package_line"
    # Composite PK: (package_no, line_no)
    package_no: Mapped[int] = mapped_column(ForeignKey("package_head.id"), primary_key=True)
    line_no: Mapped[int] = mapped_column(primary_key=True)
    item_no: Mapped[int] = mapped_column(ForeignKey("item.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(db.Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_packageline_qty_pos"),
        UniqueConstraint("package_no", "item_no", name="uq_packageline_pkg_item"),  # prevent duplicates
    )

    package = relationship("PackageHead", back_populates="lines")
    item = relationship("Item", back_populates="lines")
