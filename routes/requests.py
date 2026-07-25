from flask import Blueprint, request, jsonify

from db import db, User, RequestModel
from utils import read_token

requests_bp = Blueprint("requests", __name__)


@requests_bp.route("/api/requests", methods=["POST"])
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


@requests_bp.route("/api/requests", methods=["GET"])
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
