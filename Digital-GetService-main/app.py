from __future__ import annotations

import json
import os
import secrets
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import wraps
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any

from flask import Flask, abort, current_app, flash, g, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session
from flask_sock import Sock
from dotenv import load_dotenv
from sqlalchemy import func, text, or_, and_
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import requests
import redis

try:
    from .models import (
        ContactFooter,
        Conversation,
        DomaineAccueil,
        EquipePropos,
        Header,
        MembreNotreEquipe,
        Message,
        Realisation,
        ReseauFooter,
        ServicePeople,
        ServicesCatalog,
        ServicesFooter,
        ServicesService,
        User,
        db,
    )
except ImportError:
    from models import (
        ContactFooter,
        Conversation,
        DomaineAccueil,
        EquipePropos,
        Header,
        MembreNotreEquipe,
        Message,
        Realisation,
        ReseauFooter,
        ServicePeople,
        ServicesCatalog,
        ServicesFooter,
        ServicesService,
        User,
        db,
    )

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
IMAGE_DIR = BASE_DIR / "static" / "images"
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

SITE_NAME = "Digital Get Services"
SITE_PAGE_SET = {
    "accueil",
    "propos",
    "services",
    "realisation",
    "notreEquipe",
    "formulaire",
    "login",
    "register",
    "compte",
    "profil",
}

load_dotenv(BASE_DIR / ".env")

limiter = Limiter(key_func=get_remote_address)
sock = Sock()
session_ext = Session()
CHAT_SOCKETS: list[dict[str, Any]] = []


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for token in value.split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def assert_flask_werkzeug_compatibility() -> None:
    flask_ver = _version_tuple(pkg_version("flask"))
    werkzeug_ver = _version_tuple(pkg_version("werkzeug"))
    if flask_ver >= (3, 1, 0) and werkzeug_ver < (3, 1, 0):
        raise RuntimeError(
            "Incompatible versions detected: Flask >= 3.1 requires Werkzeug >= 3.1. "
            f"Current versions: Flask {pkg_version('flask')}, Werkzeug {pkg_version('werkzeug')}."
        )


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "change-me-dev-secret")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_DATABASE_URI"] = resolve_database_uri()
    app.config["MAIL_ENABLED"] = os.getenv("MAIL_ENABLED", "1") != "0"
    app.config["MAIL_HOST"] = os.getenv("MAIL_SMTP_HOST", "")
    app.config["MAIL_PORT"] = int(os.getenv("MAIL_SMTP_PORT", "25"))
    app.config["MAIL_FROM"] = os.getenv("MAIL_FROM_EMAIL", "no-reply@localhost")
    app.config["MAIL_USERNAME"] = os.getenv("MAIL_SMTP_USERNAME", "")
    app.config["MAIL_PASSWORD"] = os.getenv("MAIL_SMTP_PASSWORD", "")
    app.config["MAIL_USE_TLS"] = os.getenv("MAIL_SMTP_USE_TLS", "1") == "1"
    app.config["MAIL_USE_SSL"] = os.getenv("MAIL_SMTP_USE_SSL", "0") == "1"
    app.config["CONTACT_EMAIL"] = os.getenv("CONTACT_EMAIL", "fedcomfood@gmail.com")
    redis_url = os.getenv("REDIS_URL", "").strip()
    ratelimit_storage = os.getenv("RATELIMIT_STORAGE_URI", "").strip()
    if not ratelimit_storage:
        ratelimit_storage = redis_url
    app.config["RATELIMIT_STORAGE_URI"] = ratelimit_storage or "memory://"
    app.config["RATELIMIT_STRATEGY"] = os.getenv("RATELIMIT_STRATEGY", "fixed-window")
    app.config["HCAPTCHA_SITE_KEY"] = os.getenv("HCAPTCHA_SITE_KEY", "")
    app.config["HCAPTCHA_SECRET_KEY"] = os.getenv("HCAPTCHA_SECRET_KEY", "")
    app.config["HCAPTCHA_ENABLED"] = bool(app.config["HCAPTCHA_SITE_KEY"] and app.config["HCAPTCHA_SECRET_KEY"])
    max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "5"))
    app.config["MAX_CONTENT_LENGTH"] = max_upload_mb * 1024 * 1024
    app.config["CHAT_WS_URL"] = os.getenv("CHAT_WS_URL", "")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
    session_type = os.getenv("SESSION_TYPE", "").strip()
    if not session_type:
        session_type = "redis" if redis_url else "filesystem"
    if session_type == "redis" and not redis_url:
        session_type = "filesystem"
    app.config["SESSION_TYPE"] = session_type
    app.config["SESSION_PERMANENT"] = False
    app.config["SESSION_USE_SIGNER"] = True
    app.config["SESSION_KEY_PREFIX"] = os.getenv("SESSION_KEY_PREFIX", "dgs:session:")
    if session_type == "redis":
        app.config["SESSION_REDIS"] = redis.from_url(redis_url)
    else:
        app.config["SESSION_FILE_DIR"] = str(BASE_DIR / ".flask_session")
        Path(app.config["SESSION_FILE_DIR"]).mkdir(parents=True, exist_ok=True)

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    limiter.init_app(app)
    sock.init_app(app)
    session_ext.init_app(app)
    with app.app_context():
        db.create_all()
        ensure_schema_compatibility()
        seed_default_admin()

    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        return {
            "site_name": SITE_NAME,
            "user": current_user(),
            "header_data": Header.query.first(),
            "nav_items": [
                ("accueil", "Accueil"),
                ("propos", "A propos"),
                ("services", "Services"),
                ("realisation", "Realisations"),
                ("notreEquipe", "Notre equipe"),
                ("formulaire", "Contact"),
            ],
            "footer_socials": ReseauFooter.query.all(),
            "footer_services": ServicesFooter.query.all(),
            "footer_contact": ContactFooter.query.first(),
            "csrf_token": get_or_create_csrf_token(),
            "active_page": getattr(g, "active_page", ""),
            "current_year": datetime.now().year,
            "hcaptcha_site_key": current_app.config.get("HCAPTCHA_SITE_KEY", ""),
            "hcaptcha_enabled": current_app.config.get("HCAPTCHA_ENABLED", False),
        }

    limited_login = limiter.limit("8 per minute")(handle_login)
    limited_register = limiter.limit("4 per minute")(handle_register)

    @app.route("/")
    def root() -> Any:
        return redirect(url_for("site_page", page="accueil"))

    @app.route("/site")
    def site_root() -> Any:
        return redirect(url_for("site_page", page="accueil"))

    @app.route("/site/<page>", methods=["GET", "POST"])
    def site_page(page: str) -> Any:
        g.active_page = page
        if page not in SITE_PAGE_SET:
            abort(404)

        if page in {"compte", "profil"} and current_user() is None:
            return redirect(url_for("site_page", page="login"))

        if page == "login":
            return limited_login()
        if page == "register":
            return limited_register()
        if page in {"compte", "profil"}:
            return handle_profile()
        if page == "formulaire":
            return render_template("site/formulaire.html")

        return render_template(f"site/{page}.html", **build_site_context(page))

    @app.post("/site/contact")
    @limiter.limit("5 per minute")
    def contact_submit() -> Any:
        if not verify_csrf_token(request.form.get("csrf_token", "")):
            flash("Token CSRF invalide.", "danger")
            return redirect(url_for("site_page", page="formulaire"))

        if request.form.get("website"):
            flash("Votre message a ete envoye avec succes.", "success")
            return redirect(url_for("site_page", page="formulaire"))

        if current_app.config.get("HCAPTCHA_ENABLED"):
            captcha_token = request.form.get("h-captcha-response", "")
            if not verify_hcaptcha(captcha_token, request.remote_addr or ""):
                flash("Verification anti-spam invalide.", "danger")
                return redirect(url_for("site_page", page="formulaire"))

        required_fields = ["nom", "prenom", "tel", "email", "entreprise", "message"]
        values = {k: request.form.get(k, "").strip() for k in required_fields}
        if any(not values[k] for k in required_fields):
            flash("Tous les champs sont obligatoires.", "danger")
            return redirect(url_for("site_page", page="formulaire"))

        subject = f"Nouveau message de {values['nom']} {values['prenom']}"
        text_body = (
            f"Nom : {values['nom']}\n"
            f"Prenom : {values['prenom']}\n"
            f"Telephone : {values['tel']}\n"
            f"Email : {values['email']}\n"
            f"Entreprise : {values['entreprise']}\n"
            f"Message : {values['message']}\n"
        )
        html_body = (
            f"<h2>Nouveau message de contact</h2>"
            f"<p><strong>Nom :</strong> {values['nom']}</p>"
            f"<p><strong>Prenom :</strong> {values['prenom']}</p>"
            f"<p><strong>Telephone :</strong> {values['tel']}</p>"
            f"<p><strong>Email :</strong> {values['email']}</p>"
            f"<p><strong>Entreprise :</strong> {values['entreprise']}</p>"
            f"<p><strong>Message :</strong><br>{values['message']}</p>"
        )

        if send_mail(current_app.config["CONTACT_EMAIL"], subject, text_body, html_body, values["email"]):
            flash("Votre message a ete envoye avec succes.", "success")
        else:
            flash("Erreur lors de l'envoi du message.", "danger")
        return redirect(url_for("site_page", page="formulaire"))

    @app.route("/site/logout")
    def site_logout() -> Any:
        session.pop("site_user_id", None)
        return redirect(url_for("site_page", page="login"))

    @app.route("/backoffice/login", methods=["GET", "POST"])
    @limiter.limit("5 per minute")
    def backoffice_login() -> Any:
        g.active_page = "backoffice_login"
        user = current_user()
        if user and user.role == "admin":
            return redirect(url_for("backoffice_index"))

        if request.method == "POST":
            if not verify_csrf_token(request.form.get("csrf_token", "")):
                flash("Session invalide. Rechargez la page.", "danger")
                return redirect(url_for("backoffice_login"))
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            candidate = User.query.filter_by(email=email).first()
            if not candidate or candidate.role != "admin" or int(candidate.is_active or 0) != 1:
                flash("Identifiants invalides.", "danger")
                return redirect(url_for("backoffice_login"))
            if not check_password_hash(candidate.password_hash, password):
                flash("Identifiants invalides.", "danger")
                return redirect(url_for("backoffice_login"))
            session["site_user_id"] = candidate.id
            return redirect(url_for("backoffice_index"))

        return render_template("admin/login.html")

    @app.route("/backoffice/logout")
    def backoffice_logout() -> Any:
        session.pop("site_user_id", None)
        return redirect(url_for("backoffice_login"))

    @app.route("/backoffice")
    @admin_required
    def backoffice_index() -> Any:
        g.active_page = "admin_index"
        latest_users = User.query.order_by(User.id.desc()).limit(5).all()
        latest_messages = (
            db.session.query(Message, User.full_name.label("sender_name"))
            .join(User, User.id == Message.sender_id)
            .order_by(Message.id.desc())
            .limit(5)
            .all()
        )
        return render_template(
            "admin/index.html",
            user_count=User.query.count(),
            service_count=ServicesCatalog.query.count(),
            people_count=ServicePeople.query.count(),
            message_count=Message.query.count(),
            latest_users=latest_users,
            latest_messages=latest_messages,
        )

    @app.route("/backoffice/users", methods=["GET", "POST"])
    @admin_required
    def backoffice_users() -> Any:
        g.active_page = "admin_users"
        if request.method == "POST":
            if not verify_csrf_token(request.form.get("csrf_token", "")):
                flash("Token CSRF invalide.", "danger")
                return redirect(url_for("backoffice_users"))
            action = request.form.get("action", "")
            if action == "create":
                full_name = request.form.get("full_name", "").strip()
                email = request.form.get("email", "").strip().lower()
                password = request.form.get("password", "")
                role = request.form.get("role", "client")
                if not full_name or not email or not password:
                    flash("Nom, email et mot de passe sont obligatoires.", "danger")
                elif role not in {"admin", "agent", "client"}:
                    flash("Role invalide.", "danger")
                elif User.query.filter_by(email=email).first():
                    flash("Email deja utilise.", "danger")
                else:
                    db.session.add(
                        User(
                            full_name=full_name,
                            email=email,
                            password_hash=generate_password_hash(password),
                            role=role,
                            is_active=1,
                            created_at=now_iso(),
                        )
                    )
                    db.session.commit()
                    flash("Utilisateur cree.", "success")

            if action == "toggle_active":
                user_id = int(request.form.get("id", "0"))
                target = User.query.get(user_id)
                me = current_user()
                if target and me and target.id == me.id:
                    flash("Vous ne pouvez pas desactiver votre compte.", "danger")
                elif target:
                    target.is_active = 0 if int(target.is_active or 0) == 1 else 1
                    db.session.commit()
                    flash("Statut utilisateur mis a jour.", "success")

            if action == "reset_password":
                user_id = int(request.form.get("id", "0"))
                new_password = request.form.get("new_password", "")
                target = User.query.get(user_id)
                if not target:
                    flash("Utilisateur introuvable.", "danger")
                elif len(new_password) < 8:
                    flash("Le mot de passe doit contenir au moins 8 caracteres.", "danger")
                else:
                    target.password_hash = generate_password_hash(new_password)
                    db.session.commit()
                    flash("Mot de passe reinitialise.", "success")

            if action == "change_role":
                user_id = int(request.form.get("id", "0"))
                new_role = request.form.get("role", "client")
                target = User.query.get(user_id)
                if not target:
                    flash("Utilisateur introuvable.", "danger")
                elif new_role not in {"admin", "agent", "client"}:
                    flash("Role invalide.", "danger")
                else:
                    target.role = new_role
                    db.session.commit()
                    flash("Role utilisateur mis a jour.", "success")
            return redirect(url_for("backoffice_users"))

        users = User.query.order_by(User.id.desc()).all()
        return render_template("admin/users.html", users=users)

    @app.route("/backoffice/services", methods=["GET", "POST"])
    @admin_required
    def backoffice_services() -> Any:
        g.active_page = "admin_services"
        if request.method == "POST":
            if not verify_csrf_token(request.form.get("csrf_token", "")):
                flash("Token CSRF invalide.", "danger")
                return redirect(url_for("backoffice_services"))
            action = request.form.get("action", "")
            if action == "create_catalog":
                name = request.form.get("name", "").strip()
                description = request.form.get("description", "").strip()
                status = request.form.get("status", "active")
                if not name:
                    flash("Le nom du service est obligatoire.", "danger")
                elif status not in {"active", "inactive"}:
                    flash("Statut invalide.", "danger")
                else:
                    db.session.add(ServicesCatalog(name=name, description=description, status=status))
                    db.session.commit()
                    flash("Service ajoute.", "success")

            if action == "update_catalog":
                service_id = int(request.form.get("id", "0"))
                target = ServicesCatalog.query.get(service_id)
                if target:
                    target.name = request.form.get("name", "").strip()
                    target.description = request.form.get("description", "").strip()
                    target.status = request.form.get("status", "active")
                    db.session.commit()
                    flash("Service mis a jour.", "success")

            if action == "delete_catalog":
                service_id = int(request.form.get("id", "0"))
                target = ServicesCatalog.query.get(service_id)
                if target:
                    db.session.delete(target)
                    db.session.commit()
                    flash("Service supprime.", "success")

            if action == "create_legacy":
                nom = request.form.get("nom", "").strip()
                description = request.form.get("description", "").strip()
                criteres_services = request.form.get("criteres_services", "").strip()
                photo = request.files.get("image")

                if not nom:
                    flash("Le nom du service visuel est obligatoire.", "danger")
                else:
                    image_name = save_image_upload(photo, prefix="service")
                    if photo and photo.filename and not image_name:
                        flash("Image invalide (jpg, jpeg, png, webp).", "danger")
                    else:
                        db.session.add(
                            ServicesService(
                                nom=nom,
                                description=description,
                                criteres_services=criteres_services,
                                libelleImage=image_name,
                                is_suspended=0,
                            )
                        )
                        db.session.commit()
                        flash("Service visuel ajoute.", "success")

            if action == "update_legacy":
                legacy_id = int(request.form.get("legacy_id", "0"))
                target = ServicesService.query.get(legacy_id)
                if target:
                    target.nom = request.form.get("nom", "").strip()
                    target.description = request.form.get("description", "").strip()
                    target.criteres_services = request.form.get("criteres_services", "").strip()
                    photo = request.files.get("image")
                    image_name = save_image_upload(photo, prefix="service")
                    if photo and photo.filename and not image_name:
                        flash("Image invalide (jpg, jpeg, png, webp).", "danger")
                    else:
                        if image_name:
                            delete_static_image(target.libelleImage)
                            target.libelleImage = image_name
                        db.session.commit()
                        flash("Service visuel mis a jour.", "success")

            if action == "delete_legacy":
                legacy_id = int(request.form.get("legacy_id", "0"))
                target = ServicesService.query.get(legacy_id)
                if target:
                    delete_static_image(target.libelleImage)
                    db.session.delete(target)
                    db.session.commit()
                    flash("Service visuel supprime.", "success")
            return redirect(url_for("backoffice_services"))

        catalog_services = ServicesCatalog.query.order_by(ServicesCatalog.id.desc()).all()
        legacy_services = ServicesService.query.order_by(ServicesService.id.desc()).all()
        return render_template("admin/services.html", services=catalog_services, legacy_services=legacy_services)

    @app.route("/backoffice/people", methods=["GET", "POST"])
    @admin_required
    def backoffice_people() -> Any:
        g.active_page = "admin_people"
        if request.method == "POST":
            if not verify_csrf_token(request.form.get("csrf_token", "")):
                flash("Token CSRF invalide.", "danger")
                return redirect(url_for("backoffice_people"))
            action = request.form.get("action", "")
            if action == "create":
                full_name = request.form.get("full_name", "").strip()
                email = request.form.get("email", "").strip()
                phone = request.form.get("phone", "").strip()
                specialty = request.form.get("specialty", "").strip()
                selected_ids = [int(v) for v in request.form.getlist("service_ids[]") if v.isdigit()]
                if not full_name:
                    flash("Nom complet obligatoire.", "danger")
                    return redirect(url_for("backoffice_people"))
                photo_path = None
                photo = request.files.get("photo")
                if photo and photo.filename:
                    photo_path = save_image_upload(photo, prefix="sp", subdir="images/service_people")
                    if not photo_path:
                        flash("Format image invalide.", "danger")
                        return redirect(url_for("backoffice_people"))

                person = ServicePeople(full_name=full_name, email=email, phone=phone, specialty=specialty, photo_path=photo_path, is_active=1)
                if selected_ids:
                    person.services = ServicesCatalog.query.filter(ServicesCatalog.id.in_(selected_ids)).all()
                db.session.add(person)
                db.session.commit()
                flash("Personne service ajoutee.", "success")

            if action == "toggle_active":
                person_id = int(request.form.get("id", "0"))
                person = ServicePeople.query.get(person_id)
                if person:
                    person.is_active = 0 if int(person.is_active or 0) == 1 else 1
                    db.session.commit()
                    flash("Statut modifie.", "success")

            if action == "delete":
                person_id = int(request.form.get("id", "0"))
                person = ServicePeople.query.get(person_id)
                if person:
                    delete_static_image(person.photo_path)
                    db.session.delete(person)
                    db.session.commit()
                    flash("Personne service supprimee.", "success")
            return redirect(url_for("backoffice_people"))

        all_services = ServicesCatalog.query.filter_by(status="active").order_by(ServicesCatalog.name.asc()).all()
        people = ServicePeople.query.order_by(ServicePeople.id.desc()).all()
        return render_template("admin/people.html", all_services=all_services, people=people)

    @app.route("/backoffice/projects", methods=["GET", "POST"])
    @admin_required
    def backoffice_projects() -> Any:
        g.active_page = "admin_projects"
        if request.method == "POST":
            if not verify_csrf_token(request.form.get("csrf_token", "")):
                flash("Token CSRF invalide.", "danger")
                return redirect(url_for("backoffice_projects"))
            action = request.form.get("action", "")

            if action == "create":
                nom = request.form.get("nom", "").strip()
                description = request.form.get("description", "").strip()
                lien_button = request.form.get("lien_button", "").strip()
                criteres_services = request.form.get("criteres_services", "").strip()
                categorie = request.form.get("categorie", "").strip()
                photo = request.files.get("image")
                if not nom:
                    flash("Le nom du projet est obligatoire.", "danger")
                else:
                    image_name = save_image_upload(photo, prefix="project")
                    if photo and photo.filename and not image_name:
                        flash("Image invalide (jpg, jpeg, png, webp).", "danger")
                    else:
                        db.session.add(
                            Realisation(
                                nom=nom,
                                description=description,
                                lien_button=lien_button,
                                criteres_services=criteres_services,
                                categorie=categorie,
                                libelleImage=image_name,
                                is_suspended=0,
                            )
                        )
                        db.session.commit()
                        flash("Projet ajoute.", "success")

            if action == "update":
                project_id = int(request.form.get("id", "0"))
                target = Realisation.query.get(project_id)
                if target:
                    target.nom = request.form.get("nom", "").strip()
                    target.description = request.form.get("description", "").strip()
                    target.lien_button = request.form.get("lien_button", "").strip()
                    target.criteres_services = request.form.get("criteres_services", "").strip()
                    target.categorie = request.form.get("categorie", "").strip()
                    photo = request.files.get("image")
                    image_name = save_image_upload(photo, prefix="project")
                    if photo and photo.filename and not image_name:
                        flash("Image invalide (jpg, jpeg, png, webp).", "danger")
                    else:
                        if image_name:
                            delete_static_image(target.libelleImage)
                            target.libelleImage = image_name
                        db.session.commit()
                        flash("Projet mis a jour.", "success")

            if action == "delete":
                project_id = int(request.form.get("id", "0"))
                target = Realisation.query.get(project_id)
                if target:
                    delete_static_image(target.libelleImage)
                    db.session.delete(target)
                    db.session.commit()
                    flash("Projet supprime.", "success")
            return redirect(url_for("backoffice_projects"))

        projects = Realisation.query.order_by(Realisation.id.desc()).all()
        return render_template("admin/projects.html", projects=projects)

    @app.route("/backoffice/members", methods=["GET", "POST"])
    @admin_required
    def backoffice_members() -> Any:
        g.active_page = "admin_members"
        if request.method == "POST":
            if not verify_csrf_token(request.form.get("csrf_token", "")):
                flash("Token CSRF invalide.", "danger")
                return redirect(url_for("backoffice_members"))
            action = request.form.get("action", "")

            if action == "create":
                nom = request.form.get("nom", "").strip()
                role = request.form.get("role", "").strip()
                photo = request.files.get("image")
                if not nom:
                    flash("Le nom du membre est obligatoire.", "danger")
                else:
                    image_name = save_image_upload(photo, prefix="member")
                    if photo and photo.filename and not image_name:
                        flash("Image invalide (jpg, jpeg, png, webp).", "danger")
                    else:
                        db.session.add(MembreNotreEquipe(nom=nom, role=role, libelleImage=image_name, is_suspended=0))
                        db.session.commit()
                        flash("Membre ajoute.", "success")

            if action == "update":
                member_id = int(request.form.get("id", "0"))
                target = MembreNotreEquipe.query.get(member_id)
                if target:
                    target.nom = request.form.get("nom", "").strip()
                    target.role = request.form.get("role", "").strip()
                    photo = request.files.get("image")
                    image_name = save_image_upload(photo, prefix="member")
                    if photo and photo.filename and not image_name:
                        flash("Image invalide (jpg, jpeg, png, webp).", "danger")
                    else:
                        if image_name:
                            delete_static_image(target.libelleImage)
                            target.libelleImage = image_name
                        db.session.commit()
                        flash("Membre mis a jour.", "success")

            if action == "delete":
                member_id = int(request.form.get("id", "0"))
                target = MembreNotreEquipe.query.get(member_id)
                if target:
                    delete_static_image(target.libelleImage)
                    db.session.delete(target)
                    db.session.commit()
                    flash("Membre supprime.", "success")
            return redirect(url_for("backoffice_members"))

        members = MembreNotreEquipe.query.order_by(MembreNotreEquipe.id.desc()).all()
        return render_template("admin/members.html", members=members)

    @app.route("/backoffice/site-content", methods=["GET", "POST"])
    @admin_required
    def backoffice_site_content() -> Any:
        g.active_page = "admin_site"
        if request.method == "POST":
            if not verify_csrf_token(request.form.get("csrf_token", "")):
                flash("Token CSRF invalide.", "danger")
                return redirect(url_for("backoffice_site_content"))
            action = request.form.get("action", "")

            if action == "update_header":
                nom = request.form.get("nom", "").strip()
                slogan = request.form.get("slogan", "").strip()
                logo = request.files.get("logo")
                header = Header.query.first()
                if not header:
                    header = Header()
                header.nom = nom
                header.slogan = slogan
                image_name = save_image_upload(logo, prefix="logo")
                if logo and logo.filename and not image_name:
                    flash("Image invalide (jpg, jpeg, png, webp).", "danger")
                    return redirect(url_for("backoffice_site_content"))
                if image_name:
                    delete_static_image(header.logo)
                    header.logo = image_name
                db.session.add(header)
                db.session.commit()
                flash("Header mis a jour.", "success")

            if action == "create_social":
                icon = request.form.get("icon", "").strip()
                lien = request.form.get("lien", "").strip()
                if not icon or not lien:
                    flash("Icone et lien sont obligatoires.", "danger")
                else:
                    db.session.add(ReseauFooter(icon=icon, lien=lien))
                    db.session.commit()
                    flash("Reseau ajoute.", "success")

            if action == "update_social":
                item_id = int(request.form.get("id", "0"))
                target = ReseauFooter.query.get(item_id)
                if target:
                    target.icon = request.form.get("icon", "").strip()
                    target.lien = request.form.get("lien", "").strip()
                    db.session.commit()
                    flash("Reseau mis a jour.", "success")

            if action == "delete_social":
                item_id = int(request.form.get("id", "0"))
                target = ReseauFooter.query.get(item_id)
                if target:
                    db.session.delete(target)
                    db.session.commit()
                    flash("Reseau supprime.", "success")

            if action == "create_footer_service":
                criteres = request.form.get("criteres", "").strip()
                if not criteres:
                    flash("Le libelle est obligatoire.", "danger")
                else:
                    db.session.add(ServicesFooter(criteres=criteres))
                    db.session.commit()
                    flash("Service footer ajoute.", "success")

            if action == "update_footer_service":
                item_id = int(request.form.get("id", "0"))
                target = ServicesFooter.query.get(item_id)
                if target:
                    target.criteres = request.form.get("criteres", "").strip()
                    db.session.commit()
                    flash("Service footer mis a jour.", "success")

            if action == "delete_footer_service":
                item_id = int(request.form.get("id", "0"))
                target = ServicesFooter.query.get(item_id)
                if target:
                    db.session.delete(target)
                    db.session.commit()
                    flash("Service footer supprime.", "success")

            if action == "update_contact":
                email = request.form.get("email", "").strip()
                telephone = request.form.get("telephone", "").strip()
                contact = ContactFooter.query.first()
                if not contact:
                    contact = ContactFooter()
                contact.email = email
                contact.telephone = telephone
                db.session.add(contact)
                db.session.commit()
                flash("Contact footer mis a jour.", "success")

            return redirect(url_for("backoffice_site_content"))

        header = Header.query.first()
        socials = ReseauFooter.query.order_by(ReseauFooter.id.desc()).all()
        footer_services = ServicesFooter.query.order_by(ServicesFooter.id.desc()).all()
        footer_contact = ContactFooter.query.first()
        return render_template(
            "admin/site_content.html",
            header=header,
            socials=socials,
            footer_services=footer_services,
            footer_contact=footer_contact,
        )

    @app.route("/backoffice/domaines", methods=["GET", "POST"])
    @admin_required
    def backoffice_domaines() -> Any:
        g.active_page = "admin_domaines"
        if request.method == "POST":
            if not verify_csrf_token(request.form.get("csrf_token", "")):
                flash("Token CSRF invalide.", "danger")
                return redirect(url_for("backoffice_domaines"))
            action = request.form.get("action", "")

            if action == "create":
                nom = request.form.get("nom", "").strip()
                description = request.form.get("description", "").strip()
                icon = request.form.get("icon", "").strip()
                if not nom:
                    flash("Le nom est obligatoire.", "danger")
                else:
                    db.session.add(DomaineAccueil(nom=nom, description=description, icon=icon, is_suspended=0))
                    db.session.commit()
                    flash("Domaine ajoute.", "success")

            if action == "update":
                item_id = int(request.form.get("id", "0"))
                target = DomaineAccueil.query.get(item_id)
                if target:
                    target.nom = request.form.get("nom", "").strip()
                    target.description = request.form.get("description", "").strip()
                    target.icon = request.form.get("icon", "").strip()
                    db.session.commit()
                    flash("Domaine mis a jour.", "success")

            if action == "toggle":
                item_id = int(request.form.get("id", "0"))
                target = DomaineAccueil.query.get(item_id)
                if target:
                    target.is_suspended = 0 if int(target.is_suspended or 0) == 1 else 1
                    db.session.commit()
                    flash("Statut du domaine modifie.", "success")

            if action == "delete":
                item_id = int(request.form.get("id", "0"))
                target = DomaineAccueil.query.get(item_id)
                if target:
                    db.session.delete(target)
                    db.session.commit()
                    flash("Domaine supprime.", "success")

            return redirect(url_for("backoffice_domaines"))

        domaines = DomaineAccueil.query.order_by(DomaineAccueil.id.desc()).all()
        return render_template("admin/domaines.html", domaines=domaines)

    @app.route("/backoffice/equipe-propos", methods=["GET", "POST"])
    @admin_required
    def backoffice_equipe_propos() -> Any:
        g.active_page = "admin_equipe_propos"
        if request.method == "POST":
            if not verify_csrf_token(request.form.get("csrf_token", "")):
                flash("Token CSRF invalide.", "danger")
                return redirect(url_for("backoffice_equipe_propos"))
            action = request.form.get("action", "")

            if action == "create":
                nom = request.form.get("nom", "").strip()
                description = request.form.get("description", "").strip()
                icon = request.form.get("icon", "").strip()
                if not nom:
                    flash("Le nom est obligatoire.", "danger")
                else:
                    db.session.add(EquipePropos(nom=nom, description=description, icon=icon, is_suspended=0))
                    db.session.commit()
                    flash("Membre propos ajoute.", "success")

            if action == "update":
                item_id = int(request.form.get("id", "0"))
                target = EquipePropos.query.get(item_id)
                if target:
                    target.nom = request.form.get("nom", "").strip()
                    target.description = request.form.get("description", "").strip()
                    target.icon = request.form.get("icon", "").strip()
                    db.session.commit()
                    flash("Membre propos mis a jour.", "success")

            if action == "toggle":
                item_id = int(request.form.get("id", "0"))
                target = EquipePropos.query.get(item_id)
                if target:
                    target.is_suspended = 0 if int(target.is_suspended or 0) == 1 else 1
                    db.session.commit()
                    flash("Statut modifie.", "success")

            if action == "delete":
                item_id = int(request.form.get("id", "0"))
                target = EquipePropos.query.get(item_id)
                if target:
                    db.session.delete(target)
                    db.session.commit()
                    flash("Membre propos supprime.", "success")

            return redirect(url_for("backoffice_equipe_propos"))

        membres = EquipePropos.query.order_by(EquipePropos.id.desc()).all()
        return render_template("admin/equipe_propos.html", membres=membres)

    @app.route("/backoffice/mailing", methods=["GET", "POST"])
    @admin_required
    def backoffice_mailing() -> Any:
        g.active_page = "admin_mailing"
        stats = None
        if request.method == "POST":
            if not verify_csrf_token(request.form.get("csrf_token", "")):
                flash("Token CSRF invalide.", "danger")
                return redirect(url_for("backoffice_mailing"))
            subject = request.form.get("subject", "").strip()
            message = request.form.get("message", "").strip()
            if not subject or not message:
                flash("Sujet et message sont obligatoires.", "danger")
            else:
                recipients = User.query.filter(User.is_active == 1, User.email.isnot(None), User.email != "").order_by(User.id.asc()).all()
                sent = 0
                failed = 0
                for recipient in recipients:
                    html = (
                        f"<html><body><p>Bonjour {recipient.full_name},</p>"
                        f"<p>{message.replace(chr(10), '<br>')}</p>"
                        f"<p>Cordialement,<br>{SITE_NAME}</p></body></html>"
                    )
                    text = f"Bonjour {recipient.full_name},\n\n{message}\n\nCordialement,\n{SITE_NAME}"
                    if send_mail(recipient.email, subject, text, html):
                        sent += 1
                    else:
                        failed += 1
                stats = {"total": len(recipients), "sent": sent, "failed": failed}
                flash("Campagne email terminee.", "success")
        return render_template("admin/mailing.html", stats=stats)

    @app.route("/backoffice/chat")
    @admin_required
    def backoffice_chat() -> Any:
        g.active_page = "admin_chat"
        user = current_user()
        ws_token = session.get("chat_ws_token")
        if not ws_token:
            ws_token = secrets.token_urlsafe(16)
            session["chat_ws_token"] = ws_token
        ws_url = current_app.config.get("CHAT_WS_URL", "")
        if not ws_url:
            scheme = "wss" if request.is_secure else "ws"
            ws_url = f"{scheme}://{request.host}/backoffice/ws"
        return render_template(
            "admin/chat.html",
            current_user_id=user.id if user else 0,
            api_base="/backoffice/api",
            ws_url=ws_url,
            ws_token=ws_token,
        )

    @app.get("/backoffice/api/chat_users")
    @admin_required
    def backoffice_chat_users() -> Any:
        user = current_user()
        if user is None:
            return {"users": []}
        users = (
            User.query.filter(User.id != user.id, User.is_active == 1)
            .order_by(User.full_name.asc())
            .all()
        )
        return {
            "users": [
                {"id": u.id, "full_name": u.full_name, "email": u.email, "role": u.role}
                for u in users
            ]
        }

    @app.get("/backoffice/api/chat_fetch")
    @admin_required
    def backoffice_chat_fetch() -> Any:
        user = current_user()
        if user is None:
            return {"error": "unauthorized"}, 401
        try:
            target_id = int(request.args.get("target_id", "0"))
        except ValueError:
            return {"error": "invalid_target"}, 400
        if target_id <= 0:
            return {"error": "invalid_target"}, 400
        target_user = User.query.get(target_id)
        if not target_user:
            return {"error": "not_found"}, 404

        conversation = find_conversation(user.id, target_user.id)
        messages_payload: list[dict[str, Any]] = []
        if conversation:
            messages = (
                db.session.query(Message, User.full_name.label("sender_name"))
                .join(User, User.id == Message.sender_id)
                .filter(Message.conversation_id == conversation.id)
                .order_by(Message.id.asc())
                .all()
            )
            messages_payload = [
                {
                    "id": row.Message.id,
                    "sender_id": row.Message.sender_id,
                    "content": row.Message.content,
                    "created_at": row.Message.created_at or "",
                    "sender_name": row.sender_name,
                }
                for row in messages
            ]
        return {
            "target_user": {"id": target_user.id, "full_name": target_user.full_name},
            "messages": messages_payload,
        }

    @app.post("/backoffice/api/chat_send")
    @admin_required
    def backoffice_chat_send() -> Any:
        user = current_user()
        if user is None:
            return {"error": "unauthorized"}, 401
        if not verify_csrf_token(request.headers.get("X-CSRF-Token", "")):
            return {"error": "csrf_invalid"}, 400
        payload = request.get_json(silent=True) or {}
        try:
            target_id = int(payload.get("target_id", 0))
        except (TypeError, ValueError):
            return {"error": "invalid_target"}, 400
        message = str(payload.get("message", "")).strip()
        if target_id <= 0 or not message:
            return {"error": "invalid_payload"}, 400
        target_user = User.query.get(target_id)
        if not target_user:
            return {"error": "not_found"}, 404

        conversation = get_or_create_conversation(user.id, target_user.id)
        new_message = Message(
            conversation_id=conversation.id,
            sender_id=user.id,
            content=message,
            created_at=now_iso(),
        )
        conversation.updated_at = now_iso()
        db.session.add(new_message)
        db.session.commit()
        return {
            "message_id": new_message.id,
            "conversation_id": conversation.id,
            "target_id": target_user.id,
        }

    @app.errorhandler(404)
    def not_found(_: Any) -> Any:
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def payload_too_large(_: Any) -> Any:
        flash("Fichier trop volumineux.", "danger")
        fallback = request.referrer or url_for("site_page", page="accueil")
        return redirect(fallback)

    @app.errorhandler(429)
    def rate_limit_exceeded(_: Any) -> Any:
        if request.path.startswith("/backoffice/api/"):
            return {"error": "rate_limited"}, 429
        flash("Trop de tentatives. Reessayez plus tard.", "danger")
        fallback = request.referrer or url_for("site_page", page="accueil")
        return redirect(fallback)

    return app


def resolve_database_uri() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        if database_url.startswith("postgres://"):
            return database_url.replace("postgres://", "postgresql://", 1)
        return database_url
    db_path = os.getenv("DB_PATH", str(PROJECT_ROOT / "base_donnees.sqlite"))
    return f"sqlite:///{Path(db_path).resolve()}"


def ensure_schema_compatibility() -> None:
    engine = db.engine
    if engine.dialect.name != "sqlite":
        return

    required_columns: dict[str, dict[str, str]] = {
        "domaine_accueil": {
            "is_suspended": "INTEGER NOT NULL DEFAULT 0",
        },
        "equipe_propos": {
            "is_suspended": "INTEGER NOT NULL DEFAULT 0",
        },
        "services_service": {
            "is_suspended": "INTEGER NOT NULL DEFAULT 0",
        },
        "realisation_realisation": {
            "categorie": "TEXT",
            "is_suspended": "INTEGER NOT NULL DEFAULT 0",
        },
        "membre_notreequipe": {
            "is_suspended": "INTEGER NOT NULL DEFAULT 0",
        },
        "users": {
            "phone": "TEXT",
            "person_type": "TEXT NOT NULL DEFAULT 'particulier'",
            "preferred_lang": "TEXT NOT NULL DEFAULT 'fr'",
            "last_login_at": "TEXT",
            "created_at": "TEXT",
            "updated_at": "TEXT",
        },
        "services_catalog": {
            "created_at": "TEXT",
            "updated_at": "TEXT",
        },
        "service_people": {
            "photo_path": "TEXT",
        },
    }

    with engine.begin() as conn:
        for table_name, columns in required_columns.items():
            exists = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name = :name"),
                {"name": table_name},
            ).fetchone()
            if not exists:
                continue

            rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            existing_columns = {row[1] for row in rows}

            for column_name, column_sql in columns.items():
                if column_name in existing_columns:
                    continue
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"))


def current_user() -> User | None:
    user_id = session.get("site_user_id")
    if not user_id:
        return None
    user = User.query.get(int(user_id))
    if not user or int(user.is_active or 0) != 1:
        return None
    return user


def login_required(fn: Any) -> Any:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if current_user() is None:
            return redirect(url_for("site_page", page="login"))
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn: Any) -> Any:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        user = current_user()
        if user is None or user.role != "admin":
            return redirect(url_for("backoffice_login"))
        return fn(*args, **kwargs)

    return wrapper


def get_or_create_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["csrf_token"] = token
    return token


def verify_csrf_token(token: str) -> bool:
    return bool(token) and token == session.get("csrf_token")


def verify_hcaptcha(token: str, remote_ip: str) -> bool:
    secret = current_app.config.get("HCAPTCHA_SECRET_KEY", "")
    if not secret:
        return True
    if not token:
        return False
    try:
        response = requests.post(
            "https://hcaptcha.com/siteverify",
            data={"secret": secret, "response": token, "remoteip": remote_ip},
            timeout=6,
        )
        payload = response.json()
        return bool(payload.get("success"))
    except Exception:
        return False


def handle_login() -> Any:
    if current_user() is not None:
        return redirect(url_for("site_page", page="compte"))
    if request.method == "POST":
        if not verify_csrf_token(request.form.get("csrf_token", "")):
            flash("Token CSRF invalide.", "danger")
            return redirect(url_for("site_page", page="login"))
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or int(user.is_active or 0) != 1 or not check_password_hash(user.password_hash, password):
            flash("Identifiants invalides.", "danger")
            return redirect(url_for("site_page", page="login"))
        session["site_user_id"] = user.id
        if user.role == "admin":
            return redirect(url_for("backoffice_index"))
        return redirect(url_for("site_page", page="compte"))
    return render_template("auth/login.html")


def handle_register() -> Any:
    if current_user() is not None:
        return redirect(url_for("site_page", page="compte"))
    if request.method == "POST":
        if not verify_csrf_token(request.form.get("csrf_token", "")):
            flash("Token CSRF invalide.", "danger")
            return redirect(url_for("site_page", page="register"))
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip().lower()
        person_type = request.form.get("person_type", "particulier").strip()
        preferred_lang = request.form.get("preferred_lang", "fr").strip()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        if not all([full_name, phone, email, password]):
            flash("Tous les champs obligatoires doivent etre renseignes.", "danger")
        elif password != password_confirm:
            flash("Les mots de passe ne correspondent pas.", "danger")
        elif len(password) < 8:
            flash("Mot de passe trop court (min 8).", "danger")
        elif User.query.filter_by(email=email).first():
            flash("Cet email est deja utilise.", "danger")
        else:
            user = User(
                full_name=full_name,
                phone=phone,
                email=email,
                person_type=person_type,
                preferred_lang=preferred_lang,
                password_hash=generate_password_hash(password),
                role="client",
                is_active=1,
                created_at=now_iso(),
            )
            db.session.add(user)
            db.session.commit()
            flash("Compte cree. Vous pouvez vous connecter.", "success")
            return redirect(url_for("site_page", page="login"))
    return render_template("auth/register.html")


@login_required
def handle_profile() -> Any:
    user = current_user()
    if user is None:
        return redirect(url_for("site_page", page="login"))
    if request.method == "POST":
        if not verify_csrf_token(request.form.get("csrf_token", "")):
            flash("Token CSRF invalide.", "danger")
            return redirect(url_for("site_page", page="compte"))
        action = request.form.get("action", "")
        if action == "update_profile":
            full_name = request.form.get("full_name", "").strip()
            email = request.form.get("email", "").strip().lower()
            phone = request.form.get("phone", "").strip()
            person_type = request.form.get("person_type", "particulier").strip()
            preferred_lang = request.form.get("preferred_lang", "fr").strip()
            if not all([full_name, email, phone]):
                flash("Tous les champs obligatoires doivent etre renseignes.", "danger")
            elif "@" not in email:
                flash("Email invalide.", "danger")
            elif User.query.filter(User.email == email, User.id != user.id).first():
                flash("Cet email est deja utilise.", "danger")
            else:
                user.full_name = full_name
                user.email = email
                user.phone = phone
                user.person_type = person_type
                user.preferred_lang = preferred_lang
                user.updated_at = now_iso()
                db.session.commit()
                flash("Profil mis a jour avec succes.", "success")
        if action == "change_password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_new_password = request.form.get("confirm_new_password", "")
            if not check_password_hash(user.password_hash, current_password):
                flash("Mot de passe actuel incorrect.", "danger")
            elif len(new_password) < 8:
                flash("Nouveau mot de passe trop court (min 8).", "danger")
            elif new_password != confirm_new_password:
                flash("Les nouveaux mots de passe ne correspondent pas.", "danger")
            else:
                user.password_hash = generate_password_hash(new_password)
                user.updated_at = now_iso()
                db.session.commit()
                flash("Mot de passe mis a jour.", "success")
        return redirect(url_for("site_page", page="compte"))
    return render_template("auth/compte.html", profile_user=user)


def build_site_context(page: str) -> dict[str, Any]:
    if page == "accueil":
        return {
            "domaines": DomaineAccueil.query.filter(
                or_(DomaineAccueil.is_suspended.is_(None), DomaineAccueil.is_suspended == 0)
            ).order_by(DomaineAccueil.id.desc()).all()
        }
    if page == "propos":
        return {
            "membres": EquipePropos.query.filter(
                or_(EquipePropos.is_suspended.is_(None), EquipePropos.is_suspended == 0)
            ).order_by(EquipePropos.id.desc()).all()
        }
    if page == "services":
        return {
            "services_catalog": ServicesCatalog.query.filter_by(status="active").order_by(ServicesCatalog.id.desc()).all(),
            "legacy_services": ServicesService.query.filter(
                or_(ServicesService.is_suspended.is_(None), ServicesService.is_suspended == 0)
            ).order_by(ServicesService.id.desc()).all(),
        }
    if page == "realisation":
        return {
            "realisations": Realisation.query.filter(
                or_(Realisation.is_suspended.is_(None), Realisation.is_suspended == 0)
            ).order_by(Realisation.id.desc()).all()
        }
    if page == "notreEquipe":
        people = (
            db.session.query(
                ServicePeople,
                func.group_concat(ServicesCatalog.name, ", ").label("service_names"),
            )
            .outerjoin(ServicePeople.services)
            .filter(ServicePeople.is_active == 1)
            .group_by(ServicePeople.id)
            .order_by(ServicePeople.id.desc())
            .all()
        )
        people_rows = []
        for person, service_names in people:
            person.service_names = service_names
            people_rows.append(person)
        return {
            "service_people": people_rows,
            "membres": MembreNotreEquipe.query.filter(
                or_(MembreNotreEquipe.is_suspended.is_(None), MembreNotreEquipe.is_suspended == 0)
            ).order_by(MembreNotreEquipe.id.desc()).all(),
        }
    return {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_conversation(user_one_id: int, user_two_id: int) -> Conversation | None:
    return Conversation.query.filter(
        or_(
            and_(Conversation.user_one_id == user_one_id, Conversation.user_two_id == user_two_id),
            and_(Conversation.user_one_id == user_two_id, Conversation.user_two_id == user_one_id),
        )
    ).first()


def get_or_create_conversation(user_one_id: int, user_two_id: int) -> Conversation:
    conversation = find_conversation(user_one_id, user_two_id)
    if conversation:
        return conversation
    conversation = Conversation(
        user_one_id=user_one_id,
        user_two_id=user_two_id,
        created_at=now_iso(),
        updated_at=now_iso(),
    )
    db.session.add(conversation)
    db.session.commit()
    return conversation


def broadcast_chat(payload: dict[str, Any]) -> None:
    message = json.dumps(payload)
    stale: list[dict[str, Any]] = []
    for conn in CHAT_SOCKETS:
        try:
            conn["ws"].send(message)
        except Exception:
            stale.append(conn)
    for conn in stale:
        if conn in CHAT_SOCKETS:
            CHAT_SOCKETS.remove(conn)


@sock.route("/backoffice/ws")
def backoffice_ws(ws: Any) -> None:
    user = current_user()
    token = request.args.get("token", "")
    session_token = session.get("chat_ws_token", "")
    if not user or user.role != "admin" or not token or token != session_token:
        try:
            ws.close()
        finally:
            return

    connection = {"ws": ws, "user_id": user.id}
    CHAT_SOCKETS.append(connection)
    try:
        while True:
            data = ws.receive()
            if data is None:
                break
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "chat:new_message":
                broadcast_chat(payload)
    finally:
        if connection in CHAT_SOCKETS:
            CHAT_SOCKETS.remove(connection)


def save_image_upload(file_storage: Any, prefix: str, subdir: str | None = None) -> str | None:
    if not file_storage or not file_storage.filename:
        return None

    extension = Path(file_storage.filename).suffix.lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        return None

    filename = secure_filename(f"{prefix}_{secrets.token_hex(8)}{extension}")
    if subdir:
        target_dir = (BASE_DIR / "static" / subdir).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = target_dir / filename
        file_storage.save(destination)
        return f"{subdir}/{filename}".replace("\\", "/")

    destination = IMAGE_DIR / filename
    file_storage.save(destination)
    return filename


def delete_static_image(reference: str | None) -> None:
    if not reference:
        return

    # Handles both "images/..." and bare filenames stored in legacy tables.
    if "/" in reference or "\\" in reference:
        candidate = (BASE_DIR / "static" / reference).resolve()
    else:
        candidate = (IMAGE_DIR / reference).resolve()

    static_root = (BASE_DIR / "static").resolve()
    if str(candidate).startswith(str(static_root)) and candidate.is_file():
        candidate.unlink(missing_ok=True)


def send_mail(to_email: str, subject: str, text_body: str, html_body: str, reply_to: str = "") -> bool:
    if not current_app.config["MAIL_ENABLED"]:
        return True
    host = current_app.config["MAIL_HOST"]
    if not host:
        return True
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = current_app.config["MAIL_FROM"]
    msg["To"] = to_email
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        smtp_class = smtplib.SMTP_SSL if current_app.config["MAIL_USE_SSL"] else smtplib.SMTP
        with smtp_class(host, current_app.config["MAIL_PORT"], timeout=8) as smtp:
            if current_app.config["MAIL_USE_TLS"] and not current_app.config["MAIL_USE_SSL"]:
                smtp.starttls()
            if current_app.config["MAIL_USERNAME"]:
                smtp.login(current_app.config["MAIL_USERNAME"], current_app.config["MAIL_PASSWORD"])
            smtp.sendmail(msg["From"], [to_email], msg.as_string())
        return True
    except Exception:
        return False


def seed_default_admin() -> None:
    if User.query.count() > 0:
        return
    email = os.getenv("ADMIN_BOOTSTRAP_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_BOOTSTRAP_PASSWORD", "")
    if not email or not password or len(password) < 8:
        return
    full_name = os.getenv("ADMIN_BOOTSTRAP_NAME", "Administrateur")
    admin = User(
        full_name=full_name,
        email=email,
        password_hash=generate_password_hash(password),
        role="admin",
        is_active=1,
        person_type="chef_entreprise",
        preferred_lang="fr",
        created_at=now_iso(),
    )
    db.session.add(admin)
    db.session.commit()


assert_flask_werkzeug_compatibility()
app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
