import os
import secrets
from datetime import datetime, timezone

from peewee import (
    PostgresqlDatabase, Model, CharField, TextField,
    DateTimeField, BooleanField, ForeignKeyField, IntegerField,
)

DB_URL = os.environ.get("DATABASE_URL")
db = PostgresqlDatabase(DB_URL) if DB_URL else None


class User(Model):
    firstName = CharField()
    lastName = CharField()
    username = CharField(unique=True, max_length=50)
    password_hash = CharField(max_length=255)
    verified = BooleanField(default=False)
    verification_code = CharField(max_length=10)
    is_admin = BooleanField(default=False)
    coins = IntegerField(default=0)
    created_at = DateTimeField(default=datetime.now)
    status = CharField(default="active")
    resend_count = IntegerField(default=0)

    class Meta:
        database = db


class RequestModel(Model):
    email = CharField(max_length=50)
    creator = ForeignKeyField(User, backref="requests", null=True)
    prompt = TextField()
    type = CharField(max_length=20, default="request")
    status = CharField(max_length=20, default="pending")
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        database = db


class Invite(Model):
    code = CharField(unique=True, max_length=32)
    creator = ForeignKeyField(User, backref="invites")
    uses = IntegerField(default=0)
    max_uses = IntegerField(default=10)
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        database = db


class UAccessAPIKEY(Model):
    key = CharField(unique=True, max_length=255)
    creator = ForeignKeyField(User, backref="uaccess")
    created_at = DateTimeField(default=datetime.now)
    permissions = CharField(max_length=255)
    appname = CharField(max_length=255)

    class Meta:
        database = db


class Group(Model):
    name = CharField(unique=True, max_length=50)
    description = TextField()
    creator = ForeignKeyField(User, backref="created_groups")
    created_at = DateTimeField(default=datetime.now)
    public = BooleanField(default=True)
    code = CharField(unique=True, max_length=32, default=lambda: secrets.token_urlsafe(12))

    class Meta:
        database = db


class GroupMember(Model):
    group = ForeignKeyField(Group, backref="memberships", on_delete="CASCADE")
    user = ForeignKeyField(User, backref="groups", on_delete="CASCADE")

    class Meta:
        database = db
        indexes = (
            (("group", "user"), True),
        )


class TextMessage(Model):
    group = ForeignKeyField(Group, backref="messages")
    sender = ForeignKeyField(User, backref="sent_messages")
    content = TextField()
    sent_at = DateTimeField(default=datetime.now)

    class Meta:
        database = db


ALL_MODELS = [User, RequestModel, Invite, UAccessAPIKEY, Group, GroupMember, TextMessage]


def init_db():
    if not db:
        return
    try:
        db.connect(reuse_if_open=True)
        db.create_tables(ALL_MODELS)
        try:
            db.execute_sql('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();')
        except Exception:
            pass
        try:
            db.execute_sql('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS coins INTEGER NOT NULL DEFAULT 0;')
            db.execute_sql('ALTER TABLE "invite" ADD COLUMN IF NOT EXISTS uses INTEGER NOT NULL DEFAULT 0;')
            db.execute_sql('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT \'active\';')
            db.execute_sql('ALTER TABLE "invite" ADD COLUMN IF NOT EXISTS max_uses INTEGER NOT NULL DEFAULT 10;')
        except Exception:
            pass
        cutoff = datetime.now(timezone.utc).timestamp() - 86400
        cutoff_dt = datetime.fromtimestamp(cutoff, tz=timezone.utc)
        User.delete().where(
            (User.verified == False) & ((User.created_at < cutoff_dt) | (User.created_at.is_null()))
        ).execute()
        db.close()
    except Exception as e:
        print(f"[startup] DB init failed (will retry per request): {e}")


def run_migrations():
    if not db:
        return
    try:
        db.execute_sql('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false;')
        try:
            db.execute_sql('ALTER TABLE "user" RENAME COLUMN "firstname" TO "firstName";')
        except Exception:
            try:
                db.execute_sql('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS "firstName" VARCHAR(255) NOT NULL DEFAULT \'\';')
            except Exception:
                pass
        try:
            db.execute_sql('ALTER TABLE "user" RENAME COLUMN "lastname" TO "lastName";')
        except Exception:
            try:
                db.execute_sql('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS "lastName" VARCHAR(255) NOT NULL DEFAULT \'\';')
            except Exception:
                pass
        db.execute_sql('ALTER TABLE "requestmodel" ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT \'pending\';')
        db.execute_sql('ALTER TABLE "requestmodel" ADD COLUMN IF NOT EXISTS creator_id INTEGER REFERENCES "user"(id);')
        db.execute_sql('ALTER TABLE "requestmodel" ADD COLUMN IF NOT EXISTS type VARCHAR(20) NOT NULL DEFAULT \'request\';')
        db.execute_sql('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS resend_count INTEGER NOT NULL DEFAULT 0;')
        db.execute_sql('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS coins INTEGER NOT NULL DEFAULT 0;')
        db.execute_sql('ALTER TABLE "invite" ADD COLUMN IF NOT EXISTS uses INTEGER NOT NULL DEFAULT 0;')
        db.execute_sql('ALTER TABLE "invite" ADD COLUMN IF NOT EXISTS max_uses INTEGER NOT NULL DEFAULT 10;')
    except Exception:
        pass
