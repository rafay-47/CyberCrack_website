from datetime import datetime
import uuid

from flask_sqlalchemy import SQLAlchemy
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from werkzeug.security import generate_password_hash, check_password_hash

from flask_login import UserMixin

db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)
    # One user can have multiple saved profiles (uploaded resumes / parsed profiles)
    profiles = db.relationship('Profile', back_populates='user', lazy=True, cascade='all, delete-orphan')


class Profile(db.Model):
    """A saved profile extracted from an uploaded resume.

    Parsed sections (skills, work_experience, education, projects, certifications, languages, links)
    are stored in JSON columns to support structured data with PostgreSQL.
    """
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    resume_filename = db.Column(db.String(300), nullable=True)  # path or filename in uploads
    name = db.Column(db.String(200), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(80), nullable=True)
    headline = db.Column(db.String(250), nullable=True)
    location = db.Column(db.String(250), nullable=True)
    summary = db.Column(db.Text, nullable=True)

    # Structured sections stored as JSON for flexibility (Postgres JSONB recommended)
    skills = db.Column(db.JSON, nullable=True)
    work_experience = db.Column(db.JSON, nullable=True)
    education = db.Column(db.JSON, nullable=True)
    projects = db.Column(db.JSON, nullable=True)
    certifications = db.Column(db.JSON, nullable=True)
    languages = db.Column(db.JSON, nullable=True)
    links = db.Column(db.JSON, nullable=True)
    # Extracted keywords from resume/profile (e.g. via AI parser)
    extracted_keywords = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User', back_populates='profiles')

    def __repr__(self):
        return f"<Profile id={self.id} name={self.name!r} file={self.resume_filename!r}>"

