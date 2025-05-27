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
    