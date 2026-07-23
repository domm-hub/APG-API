import os
from datetime import datetime

from itsdangerous import URLSafeTimedSerializer
from peewee import (
    PostgresqlDatabase, Model, CharField, TextField,
    DateTimeField, BooleanField, ForeignKeyField, IntegerField,
)

# Core Environment Initializations
DB_URL = os.environ.get('DATABASE_URL')
db = PostgresqlDatabase(DB_URL)

SMTP_FROM = "adam.afify13@gmail.com"

# Token helpers — initialized in init_app() after Flask app exists
token_serializer = None
TOKEN_EXPIRY = 86400 * 7  # 7 days
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "scrypt:32768:8:1$cbOQrgRcvYvBZvJJ$a4c09673c7a4a1f16f5c40555d6da7e34d6231c57fbd32e43af045b8a8e05db3b9ce3a2ee9372d91dd35cf74b97ed60f76d5809d02db26e74343643a55199db8")


def init_app(app):
    global token_serializer
    token_serializer = URLSafeTimedSerializer(app.secret_key, salt="auth")


def make_token(email):
    return token_serializer.dumps(email)


def read_token(token):
    return token_serializer.loads(token, max_age=TOKEN_EXPIRY)


# Database Table Layout
class User(Model):
    firstName = CharField()
    lastName = CharField()
    username = CharField(unique=True, max_length=50)
    password_hash = CharField(max_length=255)
    verified = BooleanField(default=False)
    verification_code = CharField(max_length=10)
    is_admin = BooleanField(default=False)
    resend_count = IntegerField(default=0)

    class Meta:
        database = db


class RequestModel(Model):
    email = CharField(max_length=50)
    creator = ForeignKeyField(User, backref="requests", null=True)
    prompt = TextField()
    status = CharField(max_length=20, default="pending")
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        database = db
