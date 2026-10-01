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

    with app.app_context():
        db.create_all()

    return app
