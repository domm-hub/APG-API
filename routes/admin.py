from flask import Blueprint, request, jsonify

from db import User, RequestModel
from utils import require_admin

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/api/admin/stats", methods=["GET"])
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


@admin_bp.route("/api/admin/users", methods=["GET"])
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
        "username": getattr(u, 'display_name', ''),
        "verified": u.verified,
        "is_admin": u.is_admin,
        "coins": None if u.is_admin else u.coins,
        "coins_infinite": u.is_admin,
    } for u in users])


@admin_bp.route("/api/admin/users/<email>", methods=["DELETE"])
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


@admin_bp.route("/api/admin/users", methods=["DELETE"])
def admin_delete_users():
    user, err, code = require_admin()
    if err:
        return err, code

    User.delete().execute()
    return {"status": "success", "message": "All users deleted."}, 200


@admin_bp.route("/api/admin/requests", methods=["GET"])
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


@admin_bp.route("/api/admin/requests/<int:req_id>", methods=["DELETE"])
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


@admin_bp.route("/api/admin/requests/<int:req_id>/status", methods=["POST"])
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


@admin_bp.route("/api/admin/give-coins", methods=["POST"])
def admin_give_coins():
    admin, err, code = require_admin()
    if err:
        return err, code

    data = request.get_json()
    if not data or not data.get("email") or data.get("amount") is None:
        return {"status": "error", "message": "Missing email or amount."}, 400

    amount = data["amount"]
    if not isinstance(amount, int) or amount <= 0:
        return {"status": "error", "message": "Amount must be a positive integer."}, 400

    try:
        user = User.get(User.username == data["email"])
    except User.DoesNotExist:
        return {"status": "error", "message": "User not found."}, 404

    from db import db
    with db.atomic():
        user = User.select().where(User.id == user.id).for_update().get()
        user.coins += amount
        user.save()

    return {"status": "success", "message": f"Gave {amount} coins to {data['email']}.", "coins": user.coins}, 200


@admin_bp.route("/api/admin/cleanup", methods=["POST"])
def admin_cleanup():
    user, err, code = require_admin()
    if err:
        return err, code

    RequestModel.delete().execute()
    User.delete().execute()
    return {"status": "success", "message": "Everything deleted."}, 200
