from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import config

db = SQLAlchemy()


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = config.SQLALCHEMY_DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    from app.routes.main import bp
    app.register_blueprint(bp)

    @app.template_filter("timestamp_to_dt")
    def timestamp_to_dt(ts):
        from datetime import datetime
        try:
            return datetime.fromtimestamp(int(ts)).strftime("%H:%M:%S")
        except (ValueError, TypeError):
            return ts

    with app.app_context():
        db.create_all()
        _ensure_column(db.engine, "jobs", "status", "VARCHAR(20) NOT NULL DEFAULT 'pending'")
        _ensure_column(db.engine, "jobs", "cut_bleed", "FLOAT")
        _ensure_column(db.engine, "jobs", "cut_radius", "FLOAT DEFAULT 0.0")

    return app


def _ensure_column(engine, table, column, ddl):
    import sqlalchemy
    insp = sqlalchemy.inspect(engine)
    if table in insp.get_table_names() and column not in [c["name"] for c in insp.get_columns(table)]:
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))
