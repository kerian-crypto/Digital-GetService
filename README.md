# Flask version du site (dossier Update)

## Installation

```bash
cd Update
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

## Lancer

```bash
set FLASK_SECRET_KEY=change-me
set DB_PATH=..\\base_donnees.sqlite
python app.py
```

Application disponible sur `http://127.0.0.1:5000/site/accueil`.

Back-office: `http://127.0.0.1:5000/backoffice/login`

## Production (.env + serveur WSGI)

1. Remplir `Update/.env` (ou copier `Update/.env.example`).
2. Installer les dependances:
```bash
pip install -r requirements.txt
```
3. Linux (Render/Docker): lancer avec gunicorn:
```bash
gunicorn -w 2 --threads 4 --timeout 120 -b 0.0.0.0:5000 app:app
```

4. Windows local: lancer avec waitress:
```bash
waitress-serve --listen=0.0.0.0:5000 app:app
```
