import time
from datetime import datetime

from flask import Blueprint, request, jsonify
from peewee import DoesNotExist, IntegrityError

from db import db, User, Group, GroupMember, TextMessage, Channel, ChannelMessage, MessageRead
from utils import authenticated_user, join_group

chat_bp = Blueprint("chat", __name__)

_typing_store = {}


def _clean_typing():
    now = time.time()
    expired = [k for k, v in _typing_store.items() if now - v > 4]
    for k in expired:
        del _typing_store[k]


@chat_bp.route("/api/chat/typing", methods=["POST", "GET"])
def typing():
    user, error, code = authenticated_user()
    if error:
        return error, code

    if request.method == "POST":
        data = request.get_json()
        group_id = data.get("group_id") if data else None
        if group_id:
            _typing_store[f"{group_id}:{user.id}"] = time.time()
        _clean_typing()
        return {"status": "success"}, 200

    group_id = request.args.get("group_id")
    _clean_typing()
    now = time.time()
    typers = []
    for key, ts in _typing_store.items():
        gid, uid = key.split(":")
        if gid == str(group_id) and uid != str(user.id) and now - ts <= 4:
            try:
                u = User.get_by_id(int(uid))
                name = ((u.firstName or '') + ' ' + (u.lastName or '')).strip() or u.username
                typers.append(name)
            except Exception:
                pass
    return {"status": "success", "typers": typers}, 200


@chat_bp.route("/api/chat/createGroup", methods=["POST"])
def createGroup():
    data = request.get_json()
    group_name = data.get("name")
    group_description = data.get("description")
    public = data.get("public", True)
    group_type = data.get("group_type", "regular")

    if not group_name or not group_description:
        return {"status": "error", "message": "Missing group name or description."}, 400

    user, error, code = authenticated_user()
    if error:
        return error, code

    group = Group.create(
        name=group_name,
        description=group_description,
        creator=user,
        public=public,
        group_type=group_type
    )

    join_group(user, group)

    if group_type == "community":
        Channel.create(group=group, name="general", description="General chat")

    return {"status": "success", "message": f"Group '{group_name}' created successfully.", "group_id": group.id, "code": group.code}, 201


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
        "public": group.public,
        "code": group.code,
        "group_type": group.group_type,
        "creator": (group.creator.firstName + ' ' + group.creator.lastName).strip() or group.creator.username,
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
                         .select(User.id, User.username, User.firstName, User.lastName, User.custom_status, User.last_seen)
                         .join(GroupMember)
                         .where(GroupMember.group == group))

        members_list = [
            {
                "id": m.id,
                "username": m.username,
                "firstName": getattr(m, 'firstName', None),
                "lastName": getattr(m, 'lastName', None),
                "display_name": ((getattr(m, 'firstName', '') or '') + ' ' + (getattr(m, 'lastName', '') or '')).strip() or m.username,
                "custom_status": getattr(m, 'custom_status', ''),
                "last_seen": m.last_seen.isoformat() if m.last_seen else None,
            }
            for m in members_query
        ]

        channels = []
        if group.group_type == "community":
            channels = [{"id": ch.id, "name": ch.name, "description": ch.description}
                        for ch in Channel.select().where(Channel.group == group)]

        return {
            "status": "success",
            "group": {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "public": group.public,
                "group_type": group.group_type,
                "creator": group.creator.username,
                "members": members_list,
                "channels": channels,
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
                        member, created = GroupMember.get_or_create(group=group, user=target_user)
                        if created:
                            joiner_name = ((target_user.firstName or '') + ' ' + (target_user.lastName or '')).strip() or target_user.username
                            TextMessage.create(group=group, sender=target_user, content=f"{joiner_name} joined the group", message_type="join")
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
    group_id = data.get("group_id") if data else None
    if not group_id:
        return {"status": "error", "message": "Missing group_id."}, 400

    try:
        group = Group.get_by_id(group_id)
    except DoesNotExist:
        return {"status": "error", "message": "Group not found."}, 404

    is_member = GroupMember.select().where(
        (GroupMember.group == group) & (GroupMember.user == user)
    ).exists()
    if not is_member:
        return {"status": "error", "message": "You are not a member of this group."}, 403

    return {
        "status": "success",
        "code": group.code,
        "link": f"https://apg-two.vercel.app/home.html#chat?join={group.code}"
    }, 200


@chat_bp.route("/api/chat/joinByCode", methods=["POST"])
def joinByCode():
    user, error, code = authenticated_user()
    if error:
        return error, code

    data = request.get_json()
    invite_code = data.get("code") if data else None
    if not invite_code:
        return {"status": "error", "message": "Missing invite code."}, 400

    group = Group.get_or_none(Group.code == invite_code)
    if not group:
        return {"status": "error", "message": "Invalid invite code."}, 404

    is_member = GroupMember.select().where(
        (GroupMember.group == group) & (GroupMember.user == user)
    ).exists()
    if is_member:
        return {"status": "success", "message": "You are already a member.", "group_id": group.id, "group_name": group.name}, 200

    join_group(user, group)
    display_name = (user.firstName + ' ' + user.lastName).strip() or user.username
    TextMessage.create(group=group, sender=user, content=f"{display_name} joined the group", message_type="join")
    return {"status": "success", "message": f"Joined '{group.name}'!", "group_id": group.id, "group_name": group.name}, 200


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
    display_name = (user.firstName + ' ' + user.lastName).strip() or user.username
    return {
        "status": "success",
        "message": {
            "id": msg.id,
            "sender": display_name,
            "username": user.username,
            "content": msg.content,
            "message_type": msg.message_type,
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

    msg_list = list(reversed(list(messages)))
    msg_ids = [m.id for m in msg_list]
    read_by = {}
    if msg_ids:
        reads = (MessageRead.select(MessageRead.message_id, MessageRead.user)
                 .where(MessageRead.message_id << msg_ids))
        for r in reads:
            if r.message_id not in read_by:
                read_by[r.message_id] = []
            read_by[r.message_id].append(r.user_id)

    return {
        "status": "success",
        "messages": [{
            "id": msg.id,
            "sender": (msg.sender.firstName + ' ' + msg.sender.lastName).strip() or msg.sender.username,
            "username": msg.sender.username,
            "content": msg.content,
            "message_type": msg.message_type,
            "sent_at": msg.sent_at.isoformat(),
            "read_by": read_by.get(msg.id, []),
        } for msg in msg_list]
    }, 200


@chat_bp.route("/api/chat/markRead", methods=["POST"])
def mark_messages_read():
    user, error, code = authenticated_user()
    if error:
        return error, code

    data = request.get_json()
    group_id = data.get("group_id")
    msg_ids = data.get("message_ids", [])

    if not group_id:
        return {"status": "error", "message": "Missing group_id."}, 400

    group = Group.get_or_none(Group.id == group_id)
    if not group:
        return {"status": "error", "message": "Group not found."}, 404

    if msg_ids:
        for mid in msg_ids:
            try:
                msg = TextMessage.get_by_id(mid)
                if msg.sender_id != user.id:
                    MessageRead.get_or_create(message=msg, user=user)
            except Exception:
                pass
    else:
        msgs = (TextMessage.select()
                .where((TextMessage.group == group) & (TextMessage.sender != user))
                .order_by(TextMessage.sent_at.desc())
                .limit(50))
        for msg in msgs:
            MessageRead.get_or_create(message=msg, user=user)

    return {"status": "success"}, 200


@chat_bp.route("/api/chat/channels", methods=["GET", "POST"])
def channels():
    user, error, code = authenticated_user()
    if error:
        return error, code

    if request.method == "GET":
        group_id = request.args.get("group_id")
        if not group_id:
            return {"status": "error", "message": "Missing group_id."}, 400

        group = Group.get_or_none(Group.id == group_id)
        if not group:
            return {"status": "error", "message": "Group not found."}, 404

        if group.group_type != "community":
            return {"status": "error", "message": "Group is not a community."}, 400

        chs = Channel.select().where(Channel.group == group)
        return jsonify([{"id": ch.id, "name": ch.name, "description": ch.description} for ch in chs]), 200

    data = request.get_json()
    group_id = data.get("group_id")
    name = data.get("name", "").strip()
    description = data.get("description", "")

    if not group_id or not name:
        return {"status": "error", "message": "Missing group_id or name."}, 400

    group = Group.get_or_none(Group.id == group_id)
    if not group:
        return {"status": "error", "message": "Group not found."}, 404

    if group.creator_id != user.id:
        return {"status": "error", "message": "Only the group creator can add channels."}, 403

    if group.group_type != "community":
        return {"status": "error", "message": "Group is not a community."}, 400

    try:
        ch = Channel.create(group=group, name=name, description=description)
    except IntegrityError:
        return {"status": "error", "message": "Channel name already exists in this group."}, 400

    return {"status": "success", "channel": {"id": ch.id, "name": ch.name, "description": ch.description}}, 201


@chat_bp.route("/api/chat/channelMessages", methods=["GET", "POST"])
def channel_messages():
    user, error, code = authenticated_user()
    if error:
        return error, code

    if request.method == "GET":
        channel_id = request.args.get("channel_id")
        if not channel_id:
            return {"status": "error", "message": "Missing channel_id."}, 400

        try:
            ch = Channel.get_by_id(channel_id)
        except DoesNotExist:
            return {"status": "error", "message": "Channel not found."}, 404

        limit = min(int(request.args.get("limit", 50)), 200)
        msgs = (ChannelMessage.select()
                .where(ChannelMessage.channel == ch)
                .order_by(ChannelMessage.sent_at.desc())
                .limit(limit))

        return {
            "status": "success",
            "messages": [{
                "id": m.id,
                "sender": ((m.sender.firstName or '') + ' ' + (m.sender.lastName or '')).strip() or m.sender.username,
                "username": m.sender.username,
                "content": m.content,
                "sent_at": m.sent_at.isoformat(),
            } for m in reversed(list(msgs))]
        }, 200

    data = request.get_json()
    channel_id = data.get("channel_id")
    content = data.get("message", "").strip()

    if not channel_id or not content:
        return {"status": "error", "message": "Missing channel_id or message."}, 400

    try:
        ch = Channel.get_by_id(channel_id)
    except DoesNotExist:
        return {"status": "error", "message": "Channel not found."}, 404

    group = ch.group
    is_member = GroupMember.select().where(
        (GroupMember.group == group) & (GroupMember.user == user)
    ).exists()
    if not is_member:
        return {"status": "error", "message": "Not a member."}, 403

    msg = ChannelMessage.create(channel=ch, sender=user, content=content)
    display_name = (user.firstName + ' ' + user.lastName).strip() or user.username
    return {
        "status": "success",
        "message": {
            "id": msg.id,
            "sender": display_name,
            "username": user.username,
            "content": msg.content,
            "sent_at": msg.sent_at.isoformat()
        }
    }, 201
