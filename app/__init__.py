from flask import Flask
from config import Config
from app.models import db
from flask_migrate import Migrate
from flask_login import LoginManager
import uuid

# expose migrate instance at module level for flask CLI to import
migrate = Migrate()
# login manager
login_manager = LoginManager()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize database
    db.init_app(app)
    # Initialize migrations
    migrate.init_app(app, db)
    # Initialize login manager
    login_manager.init_app(app)
    login_manager.login_view = 'main.login'
    # user loader (deferred import to avoid circular)
    from app.models import User
    @login_manager.user_loader
    def load_user(user_id):
        # models use UUID primary keys; convert incoming id to uuid.UUID
        try:
            uid = uuid.UUID(user_id)
        except (ValueError, TypeError):
            return None
        return User.query.get(uid)

    from app.routes import main_blueprint
    app.register_blueprint(main_blueprint)

    # Note: table creation/migrations should be handled externally (Flask-Migrate / Alembic)

    return app