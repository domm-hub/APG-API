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
        db.connect(reuse_if_open=True)
        db.execute_sql("ALTER TABLE user ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false;")
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

@app.route("/api/debug", methods=["GET"])
def debug():
    import traceback, sys
    try:
        db.connect(reuse_if_open=True)
        db.execute_sql("SELECT 1")
        db.close()
        return {"msg": "DB ok"}
    except Exception as e:
        return {"msg": f"DB fail: {type(e).__name__}: {e}", "trace": traceback.format_exc()}, 500

# Endpoint 1: Registration and Token Mailer Outbound
@app.route("/api/signup", methods=["POST"])
def handleSignUp():
    data = request.get_json()
    if not data:
        return {"status": "error", "message": "Missing JSON payload"}, 400

    email       = data.get("email")
    password    = data.get("password")
    firstName   = data.get("firstname")
    lastName    = data.get("lastname")
    phoneNumber = data.get("phonenumber")

    if not email or not password or not firstName or not lastName or not phoneNumber:
        return {"status": "error", "message": "Missing fields."}, 400

    hashed_password = generate_password_hash(password)

    try:
        code = genCode()
        newUser = User.create(username=email, password_hash=hashed_password, verified=False, verification_code=code)
        send_email(email, code)
        return {"status": "success", "message": "User created successfully. Verify email to get access."}, 200
    except IntegrityError:
        return {"status": "error", "message": "Email is already taken"}, 400

# Endpoint 2: Code Validation and Account Activation Check
@app.route("/api/verify", methods=["POST"])
def handleVerification():
    data = request.get_json()
    if not data:
        return {"status": "error", "message": "Missing JSON payload"}, 400

    email = data.get("email")
    submitted_code = data.get("code")

    if not email or not submitted_code:
        return {"status": "error", "message": "Missing fields."}, 400

    try:
        user = User.get(User.username == email)
        if user.verification_code == str(submitted_code):
            user.verified = True
            user.verification_code = ""  
            user.save()                 
            return {"status": "success", "message": "Account verified successfully! You can now log in."}, 200
        else:
            return {"status": "error", "message": "Invalid verification code."}, 400
    except User.DoesNotExist:
        return {"status": "error", "message": "User not found."}, 404

# Endpoint 2.5: Resend verification code
@app.route("/api/resend-code", methods=["POST"])
def handleResendCode():
    data = request.get_json()
    if not data:
        return {"status": "error", "message": "Missing JSON payload"}, 400

    email = data.get("email")
    if not email:
        return {"status": "error", "message": "Missing email."}, 400

    try:
        user = User.get(User.username == email)
        if user.verified:
            return {"status": "error", "message": "Account already verified."}, 400

        new_code = genCode()
        user.verification_code = new_code
        user.save()
        send_email(email, new_code)
        return {"status": "success", "message": "Verification code resent."}, 200
    except User.DoesNotExist:
        return {"status": "error", "message": "User not found."}, 404

# Endpoint 3: Verified User Validation and Session Cookie Issuance
@app.route("/api/login", methods=["POST"])
def handleLogin():
    data = request.get_json()
    if not data:
        return {"status": "error", "message": "Missing JSON payload"}, 400

    email       = data.get("email")
    password    = data.get("password")

    if not email or not password:
        return {"status": "error", "message": "Missing fields."}, 400

    try:
        user = User.get(User.username == email)
    except User.DoesNotExist:
        return {"status": "error", "message": "Invalid email or password"}, 401

    if check_password_hash(user.password_hash, password):
        if not user.verified:
            return {"status": "error", "message": "Please verify your email address first."}, 401

        return {
            "status": "success",
            "message": f"Welcome back, {user.username}!",
            "token": make_token(user.username)
        }, 200
    else:
        return {"status": "error", "message": "Invalid email or password"}, 401

@app.route("/api/check-session", methods=["GET"])
def check_session():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return {"status": "unauthenticated", "message": "No token provided."}, 401

    try:
        email = read_token(auth[7:])
    except Exception:
        return {"status": "unauthenticated", "message": "Invalid or expired token."}, 401

    try:
        user = User.get(User.username == email)
        return {
            "status": "authenticated",
            "user": {
                "email": user.username,
                "verified": user.verified,
                "is_admin": user.is_admin
            }
        }, 200
    except User.DoesNotExist:
        return {"status": "unauthenticated", "message": "User not found."}, 401

@app.route("/api/claim-admin", methods=["POST"])
def claim_admin():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return {"status": "error", "message": "Not authenticated."}, 401
    try:
        email = read_token(auth[7:])
    except Exception:
        return {"status": "error", "message": "Invalid token."}, 401

    data = request.get_json()
    if not data or not data.get("password"):
        return {"status": "error", "message": "Missing password."}, 400

    if not check_password_hash(ADMIN_PASSWORD_HASH, data["password"]):
        return {"status": "error", "message": "Wrong password."}, 401

    user = User.get(User.username == email)
    user.is_admin = True
    user.save()
    return {"status": "success", "message": "You are now admin!"}, 200

@app.route("/api/requests", methods=["POST"])
def submit_request():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return {"status": "error", "message": "Not authenticated."}, 401
    try:
        email = read_token(auth[7:])
    except Exception:
        return {"status": "error", "message": "Invalid token."}, 401

    data = request.get_json()
    if not data or not data.get("prompt"):
        return {"status": "error", "message": "Missing prompt."}, 400

    RequestModel.create(email=email, prompt=data["prompt"])
    return {"status": "success", "message": "Request saved."}, 200

@app.route("/api/requests", methods=["GET"])
def list_requests():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return {"status": "error", "message": "Not authenticated."}, 401
    try:
        email = read_token(auth[7:])
    except Exception:
        return {"status": "error", "message": "Invalid token."}, 401

    try:
        user = User.get(User.username == email)
    except User.DoesNotExist:
        return {"status": "error", "message": "User not found."}, 401

    if user.is_admin:
        requests = RequestModel.select().order_by(RequestModel.created_at.desc())
    else:
        requests = RequestModel.select().where(RequestModel.email == email).order_by(RequestModel.created_at.desc())

    return jsonify([{
        "id": r.id,
        "email": r.email,
        "prompt": r.prompt,
        "created_at": r.created_at.isoformat()
    } for r in requests])

# Endpoint 6: Clear Client Authentication Session Cookie
@app.route("/api/logout", methods=["POST"])
def handleLogout():
    return {"status": "success", "message": "Logged out."}, 200

@app.route("/api/health", methods=["GET"])
def health():
    db_ok = False
    try:
        if db.is_closed():
            db.connect()
        db.execute_sql("SELECT 1")
        db_ok = True
    except Exception as e:
        db_err = str(e)
    finally:
        if not db.is_closed():
            db.close()
    return {
        "status": "ok" if db_ok else "error",
        "has_db_url": bool(os.environ.get("DATABASE_URL")),
        "has_secret_key": bool(os.environ.get("SECRET_KEY")),
        "has_smtp_login": bool(os.environ.get("SMTP_LOGIN")),
    }, 200 if db_ok else 500


if __name__ == "__main__":
    app.run(debug=True)

