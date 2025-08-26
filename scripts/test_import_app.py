import sys
from pathlib import Path
print('TEST SCRIPT START')
sys.path.append(str(Path(__file__).resolve().parents[1]))

try:
    print('Importing create_app...')
    from app import create_app
    app = create_app()
    print('create_app imported and app created successfully')
except Exception as e:
    print('ERROR importing app:', e)
    raise
