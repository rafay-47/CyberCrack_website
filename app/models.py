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
    """A saved profile extracted from an uploaded resume or manually entered.

    Stores both parsed resume data and manually entered profile information
    to match the extension's profile structure.
    """
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    resume_filename = db.Column(db.String(300), nullable=True)  # path or filename in uploads
    cover_letter_filename = db.Column(db.String(300), nullable=True)  # path for cover letter file
    title = db.Column(db.String(200), nullable=True)
    name = db.Column(db.String(200), nullable=True)
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(80), nullable=True)
    headline = db.Column(db.String(250), nullable=True)
    location = db.Column(db.String(250), nullable=True)
    address = db.Column(db.String(250), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(100), nullable=True)
    zip_code = db.Column(db.String(20), nullable=True)
    linkedin = db.Column(db.String(200), nullable=True)
    github = db.Column(db.String(200), nullable=True)
    website = db.Column(db.String(200), nullable=True)
    summary = db.Column(db.Text, nullable=True)

    # Demographic information
    ethnicity = db.Column(db.String(100), nullable=True)
    gender = db.Column(db.String(50), nullable=True)
    lgbtq = db.Column(db.String(10), nullable=True)  # Yes/No
    work_authorization = db.Column(db.String(100), nullable=True)
    visa_sponsorship = db.Column(db.String(10), nullable=True)  # Yes/No
    disability = db.Column(db.String(10), nullable=True)  # Yes/No
    veteran = db.Column(db.String(10), nullable=True)  # Yes/No

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

