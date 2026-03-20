from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv('DB_PATH', str(BASE_DIR.parent / 'base_donnees.sqlite')))
SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'change-me-dev-secret')
