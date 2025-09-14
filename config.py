"""Zentrale App-Konfiguration (12-Factor, env-getrieben).

Hinweise:
- Defaults sind bewusst entwicklerfreundlich; für Produktion **immer** Umgebungsvariablen setzen.
- SECRET_KEY und API_KEY sind Platzhalter und nicht für Prod geeignet.
"""

import os

class Config:
    # Schlüssel für Signaturen (Sessions, CSRF etc.); in Prod per ENV setzen/rotieren.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev")

    # DB-DSN aus ENV (z. B. postgresql+psycopg://user:pass@host/db); lokal fallback auf SQLite.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///app.db"
    )

    # Deaktiviert das veraltete/teure Änderungs-Tracking-Signal von SQLAlchemy.
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Einfacher shared secret für die interne API; nur Demo — in Prod härten/ersetzen.
    API_KEY = os.environ.get("API_KEY", "dev-api-key")
