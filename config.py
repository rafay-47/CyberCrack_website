import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'your_secret_key_here')
    DOWNLOAD_FOLDER = Path(__file__).parent / 'app/static/downloads'
    ALLOWED_EXTENSIONS = {'exe'}
    PAYMENT_PROVIDER = os.environ.get('PAYMENT_PROVIDER', 'Stripe')
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    # Database: prefer DATABASE_URL, otherwise build from individual env vars
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if not DATABASE_URL:
        # try individual components
        db_user = os.environ.get('user') or os.environ.get('DB_USER')
        db_pass = os.environ.get('password') or os.environ.get('DB_PASSWORD')
        db_host = os.environ.get('host') or os.environ.get('DB_HOST')
        db_port = os.environ.get('port') or os.environ.get('DB_PORT') or '5432'
        db_name = os.environ.get('dbname') or os.environ.get('DB_NAME')
        if db_user and db_pass and db_host and db_name:
            # ensure sslmode for Supabase
            DATABASE_URL = f'postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}?sslmode=require'
        else:
            raise RuntimeError('DATABASE_URL environment variable is required, or set user/password/host/port/dbname in environment')
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Ensure the engine pre-pings connections to avoid "server closed the connection unexpectedly"
    # This causes SQLAlchemy to test connections from the pool before using them and reconnect if stale.
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True
    }
    