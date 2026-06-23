import os
import random
import smtplib
from email.message import EmailMessage
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from peewee import PostgresqlDatabase, Model, CharField, TextField, DateTimeField, IntegrityError, BooleanField
from datetime import datetime, timezone

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())
CORS(app, origins=["https://hamzaahmedcollab.github.io"], supports_credentials=True)

token_serializer = URLSafeTimedSerializer(app.secret_key, salt="auth")
TOKEN_EXPIRY = 86400 * 7  # 7 days
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "scrypt:32768:8:1$cbOQrgRcvYvBZvJJ$a4c09673c7a4a1f16f5c40555d6da7e34d6231c57fbd32e43af045b8a8e05db3b9ce3a2ee9372d91dd35cf74b97ed60f76d5809d02db26e74343643a55199db8")

# Core Environment Initializations
DB_URL = os.environ.get('DATABASE_URL')
db = PostgresqlDatabase(DB_URL)

SMTP_FROM = "adam.afify13@gmail.com"

def make_token(email):
    return token_serializer.dumps(email)

def read_token(token):
    return token_serializer.loads(token, max_age=TOKEN_EXPIRY)

# Database Table Layout
class User(Model):
    username = CharField(unique=True, max_length=50)
    password_hash = CharField(max_length=255)
    verified = BooleanField(default=False)
    verification_code = CharField(max_length=10)
    is_admin = BooleanField(default=False)

    class Meta:
        database = db

class RequestModel(Model):
    email = CharField(max_length=50)
    prompt = TextField()
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        database = db

# Table Engine Initialization Loop
try:
    db.connect(reuse_if_open=True)
    db.create_tables([User, RequestModel])
    db.execute_sql("ALTER TABLE user ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false;")
    db.close()
except Exception as e:
    print(f"[startup] DB init failed (will retry per request): {e}")

# Optimizing Neon Database connection pools per request
@app.before_request
def _db_connect():
    try:
        db.connect()
        db.execute_sql("""
            ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false
        """)
    except Exception:
        pass

@app.after_request
def _db_close(response):
    try:
        if not db.is_closed():
            db.close()
    except Exception:
        pass
    return response

# Numeric unique token algorithm 
def genCode():
    return "".join([str(random.randint(0, 9)) for i in range(4)])

email_html_body = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Verify Your Account</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: #f9f9f9;
            margin: 0;
            padding: 0;
            -webkit-font-smoothing: antialiased;
        }}
        .wrapper {{
            width: 100%;
            background-color: #f9f9f9;
            padding: 40px 0;
        }}
        .container {{
            max-width: 480px;
            margin: 0 auto;
            background-color: #ffffff;
            border-radius: 16px;
            padding: 32px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
            border: 1px solid #f0f0f0;
        }}
        .logo {{
            font-size: 20px;
            font-weight: 700;
            color: #111111;
            margin-bottom: 24px;
            letter-spacing: -0.5px;
        }}
        h1 {{
            font-size: 24px;
            font-weight: 700;
            color: #111111;
            margin: 0 0 12px 0;
            letter-spacing: -0.5px;
        }}
        p {{
            font-size: 15px;
            line-height: 1.6;
            color: #555555;
            margin: 0 0 24px 0;
        }}
        .pin-box {{
            background-color: #f4f4f5;
            border-radius: 12px;
            padding: 16px;
            text-align: center;
            margin-bottom: 24px;
            letter-spacing: 6px;
            text-indent: 6px;
        }}
        .pin-code {{
            font-size: 32px;
            font-weight: 800;
            color: #111111;
            font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace;
        }}
        .footer {{
            font-size: 12px;
            color: #999999;
            text-align: center;
            margin-top: 32px;
            line-height: 1.5;
        }}
        @media (prefers-color-scheme: dark) {{
            body, .wrapper {{ background-color: #121212 !important; }}
            .container {{ background-color: #1c1c1e !important; border-color: #2c2c2e !important; }}
            h1, .logo {{ color: #ffffff !important; }}
            p {{ color: #a1a1aa !important; }}
            .pin-box {{ background-color: #2c2c2e !important; }}
            .pin-code {{ color: #ffffff !important; }}
        }}
    </style>
</head>
<body>
    <div class="wrapper">
        <div class="container">
            <div class="logo">🛠️ Our Space</div>
            <h1>Hey there!</h1>
            <p>Welcome to the portal. Drop the 4-digit activation code below into the confirmation screen to unlock your account.</p>
            <div class="pin-box">
                <span class="pin-code">{secret_pin}</span>
            </div>
            <p style="margin-bottom: 0; font-size: 13px; color: #888888;">If you didn't trigger this sign-up request, you can safely ignore this email entirely.</p>
        </div>
        <div class="footer">
            Automated via Resend Engine<br>
            Powered by Python & Cloud Run
        </div>
    </div>
</body>
</html>
"""

def send_email(to, code):
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg["Subject"] = "Verify your email"
    msg.set_content(f"Your verification code is: {code}")
    msg.add_alternative(email_html_body.format(secret_pin=code), subtype="html")
    port = int(os.environ.get("SMTP_PORT", 587))
    if port == 465:
        s = smtplib.SMTP_SSL("smtp-relay.brevo.com", port)
    else:
        s = smtplib.SMTP("smtp-relay.brevo.com", port)
        s.starttls()
    with s:
        s.login(os.environ.get("SMTP_LOGIN"), os.environ.get("SMTP_PASSWORD"))
        s.send_message(msg)

@app.route("/api/health", methods=["GET"])
def health():
    return {"status": "ok"}

# Endpoint 1: Registration and Token Mailer Outbound


if __name__ == "__main__":
    app.run(debug=True)

