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
    custom_status = CharField(max_length=100, default="")
    last_seen = DateTimeField(default=datetime.now)
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
    group_type = CharField(max_length=20, default="regular")

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
    message_type = CharField(max_length=20, default="message")
    sent_at = DateTimeField(default=datetime.now)

    class Meta:
        database = db


class Channel(Model):
    group = ForeignKeyField(Group, backref="channels", on_delete="CASCADE")
    name = CharField(max_length=50)
    description = CharField(max_length=200, default="")
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        database = db


class ChannelMessage(Model):
    channel = ForeignKeyField(Channel, backref="messages", on_delete="CASCADE")
    sender = ForeignKeyField(User, backref="channel_messages")
    content = TextField()
    sent_at = DateTimeField(default=datetime.now)

    class Meta:
        database = db


class DirectConversation(Model):
    user1 = ForeignKeyField(User, backref="dm_convos_1", on_delete="CASCADE")
    user2 = ForeignKeyField(User, backref="dm_convos_2", on_delete="CASCADE")
    created_at = DateTimeField(default=datetime.now)
    last_message_at = DateTimeField(default=datetime.now)

    class Meta:
        database = db
        indexes = (
            (("user1", "user2"), True),
        )


class DirectMessage(Model):
    conversation = ForeignKeyField(DirectConversation, backref="messages", on_delete="CASCADE")
    sender = ForeignKeyField(User, backref="sent_dms")
    content = TextField()
    sent_at = DateTimeField(default=datetime.now)
    read = BooleanField(default=False)

    class Meta:
        database = db


class MessageRead(Model):
    message = ForeignKeyField(TextMessage, backref="reads", on_delete="CASCADE")
    user = ForeignKeyField(User, backref="message_reads", on_delete="CASCADE")
    read_at = DateTimeField(default=datetime.now)

    class Meta:
        database = db
        indexes = (
            (("message", "user"), True),
        )


ALL_MODELS = [
    User, RequestModel, Invite, UAccessAPIKEY, Group, GroupMember,
    TextMessage, Channel, ChannelMessage, DirectConversation,
    DirectMessage, MessageRead,
]


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
            db.execute_sql('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS custom_status TEXT NOT NULL DEFAULT \'\';')
            db.execute_sql('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP DEFAULT NOW();')
            db.execute_sql('ALTER TABLE "group" ADD COLUMN IF NOT EXISTS group_type TEXT NOT NULL DEFAULT \'regular\';')
            db.execute_sql('ALTER TABLE "textmessage" ADD COLUMN IF NOT EXISTS message_type TEXT NOT NULL DEFAULT \'message\';')
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
        db.execute_sql('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS custom_status TEXT NOT NULL DEFAULT \'\';')
        db.execute_sql('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP DEFAULT NOW();')
        db.execute_sql('ALTER TABLE "group" ADD COLUMN IF NOT EXISTS group_type TEXT NOT NULL DEFAULT \'regular\';')
        db.execute_sql('ALTER TABLE "textmessage" ADD COLUMN IF NOT EXISTS message_type TEXT NOT NULL DEFAULT \'message\';')
    except Exception:
        pass
