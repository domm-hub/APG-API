from peewee import PostgresqlDatabase, Model, CharField, BooleanField
from dotenv import load_dotenv
import os

load_dotenv()

db = PostgresqlDatabase(os.environ["DATABASE_URL"])

class User(Model):
    username = CharField(unique=True, max_length=50)
    password_hash = CharField(max_length=255)
    verified = BooleanField(default=False)
    verification_code = CharField(max_length=10)
    class Meta:
        database = db

with db:
    db.drop_tables([User])
    db.create_tables([User])

print("💥 POOF. Database nuked.")
