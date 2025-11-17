from flask import Flask
from config import Config
from app.models import db
from flask_migrate import Migrate
from flask_login import LoginManager
import uuid
import os
from sqlalchemy import text
import logging
from flask_cors import CORS

# expose migrate instance at module level for flask CLI to import
migrate = Migrate()
# login manager
login_manager = LoginManager()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Add CORS support for Chrome extension and web clients
    CORS(app, 
         origins=["chrome-extension://*", "http://localhost:*", "https://localhost:*"],
         supports_credentials=True,
         allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
         methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

    # Ensure logging is configured early so app.logger emits to stdout/stderr
    try:
        log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
        # If the app has no handlers, attach a StreamHandler to stderr/stdout
        if not app.logger.handlers:
            handler = logging.StreamHandler()
            handler.setLevel(log_level)
            fmt = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
            handler.setFormatter(fmt)
            app.logger.addHandler(handler)
        app.logger.setLevel(getattr(logging, log_level, logging.INFO))
        # Also set root logger level to allow libs to emit
        logging.getLogger().setLevel(getattr(logging, log_level, logging.INFO))
        # BasicConfig to ensure handlers exist for scripts that rely on root logger
        logging.basicConfig()
        app.logger.debug('Logging configured (level=%s)', log_level)
    except Exception:
        # If logging config fails, fallback silently but avoid crashing app startup
        pass

    # Initialize database
    db.init_app(app)
    # Log database initialization details (mask credentials)
    try:
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI') or ''
        # Mask credentials in URI for logging: replace user:pass@ with ****
        masked_uri = db_uri
        if '://' in db_uri and '@' in db_uri:
            prefix, rest = db_uri.split('://', 1)
            if '@' in rest:
                creds, hostpart = rest.split('@', 1)
                masked_uri = f"{prefix}://***:***@{hostpart}"
        app.logger.info('Database initialized (URI=%s)', masked_uri)
        app.logger.info('SQLALCHEMY_ENGINE_OPTIONS=%s', app.config.get('SQLALCHEMY_ENGINE_OPTIONS'))
    except Exception:
        app.logger.exception('Failed to log database init info')

    # Optional: perform a quick test connection during app startup when explicitly enabled
    try:
        if str(os.environ.get('DB_CONN_CHECK', 'false')).lower() == 'true':
            with app.app_context():
                try:
                    app.logger.info('Performing startup DB connectivity test...')
                    with db.engine.connect() as conn:
                        # lightweight probe
                        conn.execute(text('SELECT 1'))
                    app.logger.info('Startup DB connectivity test succeeded')
                except Exception as conn_exc:
                    app.logger.error('Startup DB connectivity test failed', exc_info=conn_exc)
    except Exception:
        app.logger.exception('Unexpected error while running DB startup check')
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

    from app.routes import main_blueprint, init_cleanup_scheduler
    app.register_blueprint(main_blueprint)

    # Initialize cleanup scheduler for temporary files
    try:
        with app.app_context():
            init_cleanup_scheduler()
    except Exception as cleanup_init_error:
        app.logger.warning(f'Failed to initialize cleanup scheduler: {cleanup_init_error}')

    # Note: table creation/migrations should be handled externally (Flask-Migrate / Alembic)

    return app