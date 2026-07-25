import secrets

from flask import Blueprint, request
from werkzeug.security import generate_password_hash, check_password_hash

from db import db, User, UAccessAPIKEY, Invite
from utils import authenticated_user

user_bp = Blueprint("user", __name__)


@user_bp.route("/api/user/info", methods=["GET"])
def get_user_info():
    reqUser, error, code = authenticated_user()
    if error:
        return error, code

    data = request.get_json()
    if not data.get("email"):
        return {"status": "error", "message": "Missing email field."}, 400
    user = User.get_or_none(User.username == data["email"])
    if not user:
        return {"status": "error", "message": "User not found."}, 404

    return {
        "status": "success",
        "user": {
            "email": user.username,
            "firstName": user.firstName,
            "verified": user.verified,
        }
    }, 200


@user_bp.route("/api/update-profile", methods=["PUT"])
def update_profile():
    user, error, code = authenticated_user()
    if error:
        return error, code

    data = request.get_json()
    if not data:
        return {"status": "error", "message": "Missing JSON payload"}, 400

    new_password = data.get("new_password")
    current_password = data.get("current_password")

    if new_password:
        if not current_password:
            return {"status": "error", "message": "Current password required to set new password."}, 400
        if not check_password_hash(user.password_hash, current_password):
            return {"status": "error", "message": "Current password is incorrect."}, 401

        user.password_hash = generate_password_hash(new_password)

    if "firstName" in data:
        user.firstName = data["firstName"]
    if "lastName" in data:
        user.lastName = data["lastName"]
    if "phone" in data:
        user.phone = data["phone"]

    user.save()

    return {
        "status": "success",
        "message": "Profile updated.",
        "user": {
            "email": user.username,
            "firstName": user.firstName,
            "lastName": user.lastName,
            "phone": getattr(user, 'phone', None),
            "verified": user.verified,
            "is_admin": user.is_admin
        }
    }, 200


@user_bp.route("/api/user/createKey", methods=["POST"])
def create_api_key():
    key = "useracc_sk_live_" + secrets.token_urlsafe(32)
    data = request.get_json()
    prms = data.get("perms")
    name = data.get("appname")
    if not (prms or name):
        return {"status": "error", "message": "Missing permissions or app name."}, 400

    user, error, code = authenticated_user()
    if error:
        return error, code

    prms_str = ",".join(prms)
    UAccessAPIKEY.create(
        key=key,
        creator=user,
        permissions=prms_str,
        appname=name
    )

    return {"status": "success", "key": key}, 201


@user_bp.route("/api/user/status", methods=["GET", "POST"])
def user_status():
    data = request.get_json()
    key = data.get("key")
    if not key:
        return {"status": "error", "message": "Missing API key."}, 400
    if request.method == "POST":
        new_status = data.get("status")
        if not new_status:
            return {"status": "error", "message": "Missing status"}
        user = UAccessAPIKEY.get(UAccessAPIKEY.key == key).creator
        if user.status == new_status:
            return {"status": "error", "message": "Status is already set to this value."}, 400
        user.status = new_status
        user.save()
        return {"status": "success", "message": f"Status updated to {new_status}."}, 200

    if request.method == "GET":
        user = UAccessAPIKEY.get(UAccessAPIKEY.key == key).creator
        return {"status": "success", "user_status": user.status}, 200


@user_bp.route("/api/invites", methods=["GET", "POST"])
def invites():
    user, error, code = authenticated_user()
    if error:
        return error, code

    if request.method == "POST":
        invite = Invite.create(code=secrets.token_urlsafe(12), creator=user)
        base_url = "https://apg-two.vercel.app"
        return {
            "status": "success",
            "invite": {
                "code": invite.code,
                "link": f"{base_url}/signup.html?invite={invite.code}",
                "uses": invite.uses,
                "max_uses": invite.max_uses,
            },
        }, 201

    from flask import jsonify
    return jsonify([{
        "code": invite.code,
        "link": f"https://apg-two.vercel.app/signup.html?invite={invite.code}",
        "uses": invite.uses,
        "max_uses": invite.max_uses,
    } for invite in Invite.select().where(Invite.creator == user).order_by(Invite.created_at.desc())])
