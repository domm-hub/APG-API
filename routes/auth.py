from flask import Blueprint, request
from peewee import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

from db import db, User, Invite
from utils import genCode, send_email, make_token, read_token, authenticated_user

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/health", methods=["GET"])
def health():
    return {"status": "ok"}


@auth_bp.route("/api/signup", methods=["POST"])
def handleSignUp():
    data = request.get_json()
    if not data:
        return {"status": "error", "message": "Missing JSON payload"}, 400

    email = data.get("email")
    password = data.get("password")
    firstName = data.get("firstname")
    lastName = data.get("lastname")
    phoneNumber = data.get("phonenumber")
    display_name = (data.get("display_name") or "").strip()
    invite_code = (data.get("invite_code") or "").strip()

    if not email or not password or not firstName or not lastName or not phoneNumber:
        return {"status": "error", "message": "Missing fields."}, 400

    if not display_name or len(display_name) < 3 or len(display_name) > 30:
        return {"status": "error", "message": "Username must be 3-30 characters."}, 400

    if not display_name.replace("_", "").replace("-", "").isalnum():
        return {"status": "error", "message": "Username can only contain letters, numbers, underscores, and hyphens."}, 400

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

            if User.get_or_none(User.display_name == display_name):
                return {"status": "error", "message": "Username is already taken."}, 400

            User.create(
                username=email,
                display_name=display_name,
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
        return {"status": "error", "message": "Email or username is already taken."}, 400


@auth_bp.route("/api/verify", methods=["POST"])
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


@auth_bp.route("/api/resend-code", methods=["POST"])
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


@auth_bp.route("/api/login", methods=["POST"])
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


@auth_bp.route("/api/check-session", methods=["GET"])
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
    except Exception:
        return {"status": "unauthenticated", "message": "User not found."}, 401

    return {
        "status": "authenticated",
        "user": {
            "id": user.id,
            "email": user.username,
                "username": getattr(user, 'display_name', '') or user.username,
            "firstName": user.firstName,
            "lastName": user.lastName,
            "verified": user.verified,
            "is_admin": user.is_admin,
            "coins": None if user.is_admin else user.coins,
            "coins_infinite": user.is_admin,
            "custom_status": getattr(user, 'custom_status', ''),
        }
    }, 200


@auth_bp.route("/api/logout", methods=["POST"])
def handleLogout():
    return {"status": "success", "message": "Logged out."}, 200


@auth_bp.route("/api/claim-admin", methods=["POST"])
def claim_admin():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return {"status": "error", "message": "Not authenticated."}, 401
    try:
        email = read_token(auth[7:])
    except Exception:
        return {"status": "error", "message": "Invalid token."}, 401

    from flask import current_app
    ADMIN_PASSWORD_HASH = current_app.config.get("ADMIN_PASSWORD_HASH")
    if not ADMIN_PASSWORD_HASH:
        return {"status": "error", "message": "Admin password not configured."}, 500

    data = request.get_json()
    if not data or not data.get("password"):
        return {"status": "error", "message": "Missing password."}, 400

    if not check_password_hash(ADMIN_PASSWORD_HASH, data["password"]):
        return {"status": "error", "message": "Wrong password."}, 401

    user = User.get(User.username == email)
    user.is_admin = True
    user.save()
    return {"status": "success", "message": "You are now admin!"}, 200


@auth_bp.route("/api/remove-admin", methods=["POST"])
def remove_admin():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return {"status": "error", "message": "Not authenticated."}, 401
    try:
        email = read_token(auth[7:])
    except Exception:
        return {"status": "error", "message": "Invalid token."}, 401

    from flask import current_app
    ADMIN_PASSWORD_HASH = current_app.config.get("ADMIN_PASSWORD_HASH")
    if not ADMIN_PASSWORD_HASH:
        return {"status": "error", "message": "Admin password not configured."}, 500

    data = request.get_json()
    if not data or not data.get("password"):
        return {"status": "error", "message": "Missing password."}, 400

    if not check_password_hash(ADMIN_PASSWORD_HASH, data["password"]):
        return {"status": "error", "message": "Wrong password."}, 401

    user = User.get(User.username == email)
    user.is_admin = False
    user.save()
    return {"status": "success", "message": "Admin status removed."}, 200
