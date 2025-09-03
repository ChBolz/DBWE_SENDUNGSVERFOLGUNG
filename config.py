import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev")
    # Default to local SQLite while we’re developing
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///app.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
