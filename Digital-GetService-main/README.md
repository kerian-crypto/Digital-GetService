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
set ADMIN_BOOTSTRAP_EMAIL=admin@exemple.com
set ADMIN_BOOTSTRAP_PASSWORD=ChangeMe123!
set MAX_UPLOAD_MB=5
set HCAPTCHA_SITE_KEY=your-site-key
set HCAPTCHA_SECRET_KEY=your-secret-key
set REDIS_URL=redis://localhost:6379/0
set RATELIMIT_STORAGE_URI=
set SESSION_TYPE=redis
set SESSION_KEY_PREFIX=dgs:session:
python app.py
```

Application disponible sur `http://127.0.0.1:5000/site/accueil`.

Back-office: `http://127.0.0.1:5000/backoffice/login`

## Redis (rate-limit + sessions)

Lancer Redis localement:
```bash
docker compose up -d
```

Par defaut, `REDIS_URL` est utilise pour le rate-limit et les sessions.

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

Note: pour activer les WebSockets en production, preferez gunicorn + gevent:
```bash
gunicorn -k gevent -w 1 -b 0.0.0.0:5000 app:app
```

4. Windows local: lancer avec waitress:
```bash
waitress-serve --listen=0.0.0.0:5000 app:app
```
