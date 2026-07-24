import os
import random
import smtplib
import secrets
from datetime import datetime, timezone
from email.message import EmailMessage

from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from itsdangerous import URLSafeTimedSerializer
from peewee import (
    PostgresqlDatabase, Model, CharField, TextField,
    DateTimeField, IntegrityError, BooleanField, ForeignKeyField,
    IntegerField,
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())
CORS(app, origins=["https://hamzaahmedcollab.github.io", "https://apg-two.vercel.app"], supports_credentials=True)

# Token setup
token_serializer = URLSafeTimedSerializer(app.secret_key, salt="auth")
TOKEN_EXPIRY = 86400 * 7
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "scrypt:32768:8:1$cbOQrgRcvYvBZvJJ$a4c09673c7a4a1f16f5c40555d6da7e34d6231c57fbd32e43af045b8a8e05db3b9ce3a2ee9372d91dd35cf74b97ed60f76d5809d02db26e74343643a55199db8")

def make_token(email):
    return token_serializer.dumps(email)

def read_token(token):
    return token_serializer.loads(token, max_age=TOKEN_EXPIRY)

# Database
DB_URL = os.environ.get('DATABASE_URL')
db = PostgresqlDatabase(DB_URL) if DB_URL else None
SMTP_FROM = "adam.afify13@gmail.com"


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


# Table Engine Initialization Loop
if db:
    try:
        db.connect(reuse_if_open=True)
        db.create_tables([User, RequestModel, Invite])
        try:
            db.execute_sql('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();')
        except Exception:
            pass
        try:
            db.execute_sql('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS coins INTEGER NOT NULL DEFAULT 0;')
            db.execute_sql('ALTER TABLE "invite" ADD COLUMN IF NOT EXISTS uses INTEGER NOT NULL DEFAULT 0;')
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


@app.before_request
def _db_connect():
    if not db:
        return
    try:
        db.connect()
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

@app.after_request
def inject_action_field(response):
    # 1. Only process if the response is JSON
    if response.is_json:
        try:
            data = response.get_json()
            
            # Scenario A: Response is a standard JSON Object {}
            if isinstance(data, dict):
                # Use setdefault to apply "none" only if the key doesn't exist
                data.setdefault("action", "none")
            
            # Scenario B: Response is a JSON Array []
            elif isinstance(data, list):
                # Inject the field into every object inside the array
                for item in data:
                    if isinstance(item, dict):
                        item.setdefault("action", "none")
            
            # 2. Save the modified payload back to the response
            response.set_json(data)
            
        except Exception as e:
            print(f"Error injecting action field: {e}", flush=True)
            
    # 3. Always return the response
    return response



@app.after_request
def _db_close(response):
    if db:
        try:
            if not db.is_closed():
                db.close()
        except Exception:
            pass
    if request.method == "GET" and request.path != "/api/login" and response.content_type and "application/json" in response.content_type:
        try:
            import json
            body = json.loads(response.get_data(as_text=True))
            if isinstance(body, dict):
                body["roast"] = random.choice(ROASTS)
                response.set_data(json.dumps(body))
        except Exception:
            pass
    return response


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
            <div class="logo">Our Space</div>
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
    # 1. Build the email message
    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM")
    msg["To"] = to
    msg["Subject"] = "Verify your email"
    msg.set_content(f"Your verification code is: {code}")
    
    # Ensure email_html_body is imported/defined globally in your file
    msg.add_alternative(email_html_body.format(secret_pin=code), subtype="html")
    
    # 2. Extract environment credentials
    smtp_host = os.environ.get("SMTP_HOST", "://gmail.com")
    smtp_login = os.environ.get("SMTP_LOGIN")
    smtp_password = os.environ.get("SMTP_PASSWORD")

    # 3. Connect securely via Port 587
    with smtplib.SMTP(smtp_host, 587) as s:
        s.set_debuglevel(1)
        s.starttls()  # Securely upgrades the connection to TLS encryption
        s.login(smtp_login, smtp_password)
        s.send_message(msg)


@app.route("/api/health", methods=["GET"])
def health():
    return {"status": "ok"}


@app.route("/api/signup", methods=["POST"])
def handleSignUp():
    data = request.get_json()
    if not data:
        return {"status": "error", "message": "Missing JSON payload"}, 400

    email = data.get("email")
    password = data.get("password")
    firstName = data.get("firstname")
    lastName = data.get("lastname")
    phoneNumber = data.get("phonenumber")
    invite_code = (data.get("invite_code") or "").strip()

    if not email or not password or not firstName or not lastName or not phoneNumber:
        return {"status": "error", "message": "Missing fields."}, 400

    if len(firstName) > 255 or len(lastName) > 255:
        return {"status": "error", "message": "Firstname or last name too long."}, 400

    hashed_password = generate_password_hash(password)

    try:
        code = genCode()
        with db.atomic():
            invite = None
            starting_coins = 0
            if invite_code:
                try:
                    invite = Invite.select().where(Invite.code == invite_code).for_update().get()
                except Invite.DoesNotExist:
                    return {"status": "error", "message": "Invite link is invalid."}, 400
                if invite.uses >= invite.max_uses:
                    return {"status": "error", "message": "Invite link has reached its 10-person limit."}, 400
                starting_coins = 20

            User.create(
                username=email,
                password_hash=hashed_password,
                verified=False,
                verification_code=code,
                firstName=firstName,
                lastName=lastName,
                coins=starting_coins,
            )
            if invite:
                User.update(coins=User.coins + 20).where(User.id == invite.creator_id).execute()
                Invite.update(uses=Invite.uses + 1).where(Invite.id == invite.id).execute()
        send_email(email, code)
        return {
            "status": "success",
            "message": "User created successfully. Verify email to get access.",
            "invite_reward": bool(invite_code),
        }, 200
    except IntegrityError:
        return {"status": "error", "message": "Email is already taken"}, 400


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

        if user.resend_count >= 5:
            return {"status": "error", "message": "Resend limit reached. Please contact support."}, 429

        new_code = genCode()
        user.verification_code = new_code
        user.resend_count += 1
        user.save()
        send_email(email, new_code)
        return {"status": "success", "message": "Verification code resent."}, 200
    except User.DoesNotExist:
        return {"status": "error", "message": "User not found."}, 404


@app.route("/api/login", methods=["POST"])
def handleLogin():
    data = request.get_json()
    if not data:
        return {"status": "error", "message": "Missing JSON payload"}, 400

    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return {"status": "error", "message": "Missing fields."}, 400

    try:
        user = User.get(User.username == email)
    except User.DoesNotExist:
        return {"status": "error", "message": "Invalid email or password"}, 401

    if check_password_hash(user.password_hash, password):
        if not user.verified:
            return {"status": "error", "message": "Please verify your email address first.", "action": "verify"}, 401

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
                "firstName": user.firstName,
                "lastName": user.lastName,
                "verified": user.verified,
                "is_admin": user.is_admin,
                "coins": None if user.is_admin else user.coins,
                "coins_infinite": user.is_admin,
            }
        }, 200
    except User.DoesNotExist:
        return {"status": "unauthenticated", "message": "User not found."}, 401


def authenticated_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, {"status": "error", "message": "Not authenticated."}, 401
    try:
        email = read_token(auth[7:])
        return User.get(User.username == email), None, None
    except (Exception, User.DoesNotExist):
        return None, {"status": "error", "message": "Invalid or expired token."}, 401


@app.route("/api/invites", methods=["GET", "POST"])
def invites():
    user, error, code = authenticated_user()
    if error:
        return error, code

    if request.method == "POST":
        invite = Invite.create(code=secrets.token_urlsafe(12), creator=user)
        base_url = os.environ.get("FRONTEND_URL", "https://apg-two.vercel.app").rstrip("/")
        return {
            "status": "success",
            "invite": {
                "code": invite.code,
                "link": f"{base_url}/signup.html?invite={invite.code}",
                "uses": invite.uses,
                "max_uses": invite.max_uses,
            },
        }, 201

    return jsonify([{
        "code": invite.code,
        "link": f"{os.environ.get('FRONTEND_URL', 'https://apg-two.vercel.app').rstrip('/')}/signup.html?invite={invite.code}",
        "uses": invite.uses,
        "max_uses": invite.max_uses,
    } for invite in Invite.select().where(Invite.creator == user).order_by(Invite.created_at.desc())])


@app.route("/api/update-profile", methods=["PUT"])
def update_profile():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return {"status": "error", "message": "Not authenticated."}, 401
    try:
        email = read_token(auth[7:])
    except Exception:
        return {"status": "error", "message": "Invalid token."}, 401

    data = request.get_json()
    if not data:
        return {"status": "error", "message": "Missing JSON payload"}, 400

    try:
        user = User.get(User.username == email)
    except User.DoesNotExist:
        return {"status": "error", "message": "User not found."}, 401

    firstName = data.get("firstName")
    lastName = data.get("lastName")
    phone = data.get("phone")
    new_password = data.get("new_password")
    current_password = data.get("current_password")

    if new_password:
        if not current_password:
            return {"status": "error", "message": "Current password required to set new password."}, 400
        if not check_password_hash(user.password_hash, current_password):
            return {"status": "error", "message": "Current password is incorrect."}, 401
        user.password_hash = generate_password_hash(new_password)

    if firstName is not None:
        user.firstName = firstName
    if lastName is not None:
        user.lastName = lastName
    user.save()

    return {
        "status": "success",
        "message": "Profile updated.",
        "user": {
            "email": user.username,
            "firstName": user.firstName,
            "lastName": user.lastName,
            "verified": user.verified,
            "is_admin": user.is_admin
        }
    }, 200


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


@app.route("/api/remove-admin", methods=["POST"])
def remove_admin():
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
    user.is_admin = False
    user.save()
    return {"status": "success", "message": "Admin status removed."}, 200


ROASTS = [
    "Your request is so vague, even ChatGPT gave up on it.",
    "Bold of you to assume anyone read this.",
    "Request submitted. Nobody was impressed.",
    "Cool request. Too bad it's terrible.",
    "Noted. Discarded. You're welcome.",
    "I've seen better ideas on a sticky note.",
    "Thanks for sharing. I wish I could un-read it.",
    "Your request has been received and immediately judged.",
    "Filed under: things nobody asked for.",
    "Wow. That's... certainly a request.",
    "I showed this to my dog. He left the room.",
    "Request logged. Dignity not found.",
    "This request has the energy of a wet sock.",
    "Congrats, you've invented a new kind of bad idea.",
    "On a scale of 1 to 10, this is a solid negative 3.",
]


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

    try:
        user = User.get(User.username == email)
    except User.DoesNotExist:
        user = None

    req_type = data.get("type", "request")
    if req_type not in ("request", "challenge"):
        req_type = "request"

    website_cost = 50
    with db.atomic():
        user = User.select().where(User.id == user.id).for_update().get()
        if req_type == "request" and not user.is_admin:
            if user.coins < website_cost:
                return {
                    "status": "error",
                    "message": f"You need {website_cost} coins to request a website. You have {user.coins}.",
                }, 402
            user.coins -= website_cost
            user.save()

        RequestModel.create(email=email, prompt=data["prompt"], creator=user, type=req_type)

    return {
        "status": "success",
        "message": "Request saved.",
        "coins": None if user.is_admin else user.coins,
        "coins_infinite": user.is_admin,
    }, 200


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
        "type": r.type,
        "status": r.status,
        "created_at": r.created_at.isoformat()
    } for r in requests])


@app.route("/api/logout", methods=["POST"])
def handleLogout():
    return {"status": "success", "message": "Logged out."}, 200


def require_admin():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, {"status": "error", "message": "Not authenticated."}, 401
    try:
        email = read_token(auth[7:])
    except Exception:
        return None, {"status": "error", "message": "Invalid token."}, 401
    try:
        user = User.get(User.username == email)
        if not user.is_admin:
            return None, {"status": "error", "message": "Not authorized."}, 403
        return user, None, None
    except User.DoesNotExist:
        return None, {"status": "error", "message": "User not found."}, 401


@app.route("/api/admin/stats", methods=["GET"])
def admin_stats():
    user, err, code = require_admin()
    if err:
        return err, code

    return {
        "total_users": User.select().count(),
        "verified_users": User.select().where(User.verified == True).count(),
        "admin_users": User.select().where(User.is_admin == True).count(),
        "total_requests": RequestModel.select().count(),
        "pending_requests": RequestModel.select().where(RequestModel.status == "pending").count(),
    }, 200


@app.route("/api/admin/users", methods=["GET"])
def admin_users():
    user, err, code = require_admin()
    if err:
        return err, code

    users = User.select().order_by(User.username)
    return jsonify([{
        "email": u.username,
        "id": u.id,
        "firstName": u.firstName,
        "lastName": u.lastName,
        "verified": u.verified,
        "is_admin": u.is_admin,
        "coins": None if u.is_admin else u.coins,
        "coins_infinite": u.is_admin,
    } for u in users])


@app.route("/api/admin/users/<email>", methods=["DELETE"])
def admin_delete_user(email):
    admin, err, code = require_admin()
    if err:
        return err, code

    try:
        user = User.get(User.username == email)
        if user.is_admin:
            return {"status": "error", "message": "Cannot delete admin users."}, 403
        user.delete_instance()
        return {"status": "success", "message": "User deleted."}, 200
    except User.DoesNotExist:
        return {"status": "error", "message": "User not found."}, 404


@app.route("/api/admin/users", methods=["DELETE"])
def admin_delete_users():
    user, err, code = require_admin()
    if err:
        return err, code

    User.delete().execute()
    return {"status": "success", "message": "All users deleted."}, 200


@app.route("/api/admin/requests", methods=["GET"])
def admin_requests():
    user, err, code = require_admin()
    if err:
        return err, code

    reqs = RequestModel.select().order_by(RequestModel.created_at.desc())
    return jsonify([{
        "id": r.id,
        "email": r.email,
        "prompt": r.prompt,
        "type": r.type,
        "status": r.status,
        "creator_email": r.creator.username if r.creator else None,
        "creator_name": ((r.creator.firstName + " " + r.creator.lastName) if r.creator else None),
        "created_at": r.created_at.isoformat()
    } for r in reqs])


@app.route("/api/admin/requests/<int:req_id>", methods=["DELETE"])
def admin_delete_request(req_id):
    user, err, code = require_admin()
    if err:
        return err, code

    try:
        req = RequestModel.get(RequestModel.id == req_id)
        req.delete_instance()
        return {"status": "success", "message": "Request deleted."}, 200
    except RequestModel.DoesNotExist:
        return {"status": "error", "message": "Request not found."}, 404


@app.route("/api/admin/requests/<int:req_id>/status", methods=["POST"])
def admin_update_request_status(req_id):
    user, err, code = require_admin()
    if err:
        return err, code

    data = request.get_json()
    if not data or not data.get("status"):
        return {"status": "error", "message": "Missing status."}, 400

    new_status = data["status"]
    if new_status not in ("accepted", "rejected"):
        return {"status": "error", "message": "Invalid status."}, 400

    try:
        req = RequestModel.get(RequestModel.id == req_id)
        req.status = new_status
        req.save()
        return {"status": "success", "message": f"Request {new_status}."}, 200
    except RequestModel.DoesNotExist:
        return {"status": "error", "message": "Request not found."}, 404


@app.route("/api/admin/cleanup", methods=["POST"])
def admin_cleanup():
    user, err, code = require_admin()
    if err:
        return err, code

    RequestModel.delete().execute()
    User.delete().execute()
    return {"status": "success", "message": "Everything deleted."}, 200


if __name__ == "__main__":
    app.run(debug=True)
