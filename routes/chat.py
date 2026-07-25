from flask import Blueprint, request, jsonify
from peewee import DoesNotExist, IntegrityError

from db import db, User, Group, GroupMember, TextMessage
from utils import authenticated_user, join_group

chat_bp = Blueprint("chat", __name__)


@chat_bp.route("/api/chat/createGroup", methods=["POST"])
def createGroup():
    data = request.get_json()
    group_name = data.get("name")
    group_description = data.get("description")
    public = data.get("public", True)

    if not group_name or not group_description:
        return {"status": "error", "message": "Missing group name or description."}, 400

    user, error, code = authenticated_user()
    if error:
        return error, code

    group = Group.create(
        name=group_name,
        description=group_description,
        creator=user,
        public=public
    )

    join_group(user, group)

    return {"status": "success", "message": f"Group '{group_name}' created successfully."}, 201


@chat_bp.route("/api/chat/listGroups", methods=["GET"])
def listGroups():
    user, error, code = authenticated_user()
    if error:
        return error, code

    groups = (Group.select()
              .join(GroupMember)
              .where(GroupMember.user == user))
    return jsonify([{
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "creator": group.creator.username,
        "created_at": group.created_at.isoformat(),
    } for group in groups]), 200


@chat_bp.route("/api/chat/group", methods=["GET", "PUT"])
def manage_group():
    user, error, code = authenticated_user()
    if error:
        return error, code

    if request.method == "GET":
        group_id = request.args.get("group_id")
    else:
        data = request.get_json() or {}
        group_id = data.get("group_id")

    if not group_id:
        return {"status": "error", "message": "Missing group_id parameter."}, 400

    try:
        group = Group.get_by_id(group_id)
    except DoesNotExist:
        return {"status": "error", "message": "Group not found."}, 404

    if request.method == "GET":
        is_member = GroupMember.select().where(
            (GroupMember.group == group) & (GroupMember.user == user)
        ).exists()

        if not group.public and not is_member:
            return {"status": "error", "message": "Access denied to this private group."}, 403

        members_query = (User
                         .select(User.username, User.firstName, User.lastName)
                         .join(GroupMember)
                         .where(GroupMember.group == group))

        members_list = [
            {
                "username": m.username,
                "firstName": getattr(m, 'firstName', None),
                "lastName": getattr(m, 'lastName', None)
            }
            for m in members_query
        ]

        return {
            "status": "success",
            "group": {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "public": group.public,
                "creator": group.creator.username,
                "members": members_list
            }
        }, 200

    if request.method == "PUT":
        data = request.get_json()
        if not data:
            return {"status": "error", "message": "Missing JSON payload."}, 400

        if group.creator_id != user.id:
            return {"status": "error", "message": "Only the group creator can modify this group."}, 403

        try:
            with db.atomic():
                target_username = data.get("add_user")
                if target_username:
                    try:
                        target_user = User.get(User.username == target_username)
                        GroupMember.get_or_create(group=group, user=target_user)
                    except DoesNotExist:
                        return {"status": "error", "message": f"User '{target_username}' not found."}, 404

                if "name" in data and data["name"]:
                    group.name = data["name"]

                if "group_description" in data:
                    group.description = data["group_description"]

                if "public" in data:
                    if isinstance(data["public"], bool):
                        group.public = data["public"]
                    else:
                        return {"status": "error", "message": "Field 'public' must be a boolean."}, 400

                group.save()

        except IntegrityError:
            return {"status": "error", "message": "Database integrity failure during update."}, 500

        return {"status": "success", "message": "Group updated successfully."}, 200


@chat_bp.route("/api/chat/getGroupId", methods=["GET"])
def getGroupID():
    group_name = request.args.get("name")
    if not group_name:
        return {"status": "error", "message": "Missing group name."}, 400

    try:
        group = Group.get(Group.name == group_name)
        return {"status": "success", "group_id": group.id}, 200
    except Group.DoesNotExist:
        return {"status": "error", "message": "Group not found."}, 404


@chat_bp.route("/api/chat/getGroupCode", methods=["POST"])
def getGroupCode():
    user, error, code = authenticated_user()
    if error:
        return error, code

    data = request.get_json()


@chat_bp.route("/api/chat/sendmessage", methods=["POST"])
def send_message():
    data = request.get_json()
    if not data:
        return {"status": "error", "message": "Missing JSON payload."}, 400

    user, error, code = authenticated_user()
    if error:
        return error, code

    message = data.get("message")
    group_id = data.get("group_id")

    if not message or not group_id:
        return {"status": "error", "message": "Missing message or group_id."}, 400

    group = Group.get_or_none(Group.id == group_id)
    if not group:
        return {"status": "error", "message": "Group not found."}, 404

    is_member = GroupMember.select().where(
        (GroupMember.group == group) & (GroupMember.user == user)
    ).exists()
    if not is_member:
        return {"status": "error", "message": "You are not a member of this group."}, 403

    msg = TextMessage.create(group=group, sender=user, content=message)
    return {
        "status": "success",
        "message": {
            "id": msg.id,
            "sender": user.username,
            "content": msg.content,
            "sent_at": msg.sent_at.isoformat()
        }
    }, 201


@chat_bp.route("/api/chat/getMessages", methods=["GET"])
def get_messages():
    user, error, code = authenticated_user()
    if error:
        return error, code

    group_id = request.args.get("group_id")
    if not group_id:
        return {"status": "error", "message": "Missing group_id parameter."}, 400

    group = Group.get_or_none(Group.id == group_id)
    if not group:
        return {"status": "error", "message": "Group not found."}, 404

    is_member = GroupMember.select().where(
        (GroupMember.group == group) & (GroupMember.user == user)
    ).exists()
    if not is_member:
        return {"status": "error", "message": "You are not a member of this group."}, 403

    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    messages = (TextMessage.select()
                .where(TextMessage.group == group)
                .order_by(TextMessage.sent_at.desc())
                .limit(limit)
                .offset(offset))

    return {
        "status": "success",
        "messages": [{
            "id": msg.id,
            "sender": msg.sender.username,
            "content": msg.content,
            "sent_at": msg.sent_at.isoformat()
        } for msg in reversed(list(messages))]
    }, 200
