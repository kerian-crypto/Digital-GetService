from __future__ import annotations

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

service_person_services = db.Table(
    "service_person_services",
    db.Column("person_id", db.Integer, db.ForeignKey("service_people.id"), primary_key=True),
    db.Column("service_id", db.Integer, db.ForeignKey("services_catalog.id"), primary_key=True),
)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.Text, nullable=False)
    email = db.Column(db.Text, nullable=False, unique=True)
    password_hash = db.Column(db.Text, nullable=False)
    role = db.Column(db.Text, nullable=False, default="client")
    is_active = db.Column(db.Integer, nullable=False, default=1)
    phone = db.Column(db.Text)
    person_type = db.Column(db.Text, default="particulier")
    preferred_lang = db.Column(db.Text, default="fr")
    created_at = db.Column(db.Text)
    updated_at = db.Column(db.Text)
    last_login_at = db.Column(db.Text)


class ServicesCatalog(db.Model):
    __tablename__ = "services_catalog"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.Text, nullable=False, default="active")
    created_at = db.Column(db.Text)
    updated_at = db.Column(db.Text)


class ServicePeople(db.Model):
    __tablename__ = "service_people"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.Text, nullable=False)
    email = db.Column(db.Text)
    phone = db.Column(db.Text)
    specialty = db.Column(db.Text)
    photo_path = db.Column(db.Text)
    is_active = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.Text)
    services = db.relationship("ServicesCatalog", secondary=service_person_services, lazy="select")


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.Text)
    read_at = db.Column(db.Text)


class Conversation(db.Model):
    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True)
    user_one_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    user_two_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.Text)
    updated_at = db.Column(db.Text)


class Header(db.Model):
    __tablename__ = "header"

    id = db.Column(db.Integer, primary_key=True)
    logo = db.Column(db.Text)
    nom = db.Column(db.Text)
    slogan = db.Column(db.Text)


class DomaineAccueil(db.Model):
    __tablename__ = "domaine_accueil"

    id = db.Column(db.Integer, primary_key=True)
    icon = db.Column(db.Text)
    nom = db.Column(db.Text)
    description = db.Column(db.Text)
    is_suspended = db.Column(db.Integer, default=0)


class EquipePropos(db.Model):
    __tablename__ = "equipe_propos"

    id = db.Column(db.Integer, primary_key=True)
    icon = db.Column(db.Text)
    nom = db.Column(db.Text)
    description = db.Column(db.Text)
    is_suspended = db.Column(db.Integer, default=0)


class ServicesService(db.Model):
    __tablename__ = "services_service"

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.Text)
    description = db.Column(db.Text)
    criteres_services = db.Column(db.Text)
    libelleImage = db.Column(db.Text)
    is_suspended = db.Column(db.Integer, default=0)


class Realisation(db.Model):
    __tablename__ = "realisation_realisation"

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.Text)
    description = db.Column(db.Text)
    lien_button = db.Column(db.Text)
    criteres_services = db.Column(db.Text)
    libelleImage = db.Column(db.Text)
    categorie = db.Column(db.Text)
    is_suspended = db.Column(db.Integer, default=0)


class MembreNotreEquipe(db.Model):
    __tablename__ = "membre_notreequipe"

    id = db.Column(db.Integer, primary_key=True)
    libelleImage = db.Column(db.Text)
    nom = db.Column(db.Text)
    role = db.Column(db.Text)
    is_suspended = db.Column(db.Integer, default=0)


class ReseauFooter(db.Model):
    __tablename__ = "reseau_footer"

    id = db.Column(db.Integer, primary_key=True)
    icon = db.Column(db.Text)
    lien = db.Column(db.Text)


class ServicesFooter(db.Model):
    __tablename__ = "services_footer"

    id = db.Column(db.Integer, primary_key=True)
    criteres = db.Column(db.Text)


class ContactFooter(db.Model):
    __tablename__ = "contact_footer"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.Text)
    telephone = db.Column(db.Text)
