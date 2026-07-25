import json
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from peewee import DoesNotExist

from db import db, User, DirectConversation, DirectMessage
from utils import authenticated_user

dm_bp = Blueprint("dm", __name__)


@dm_bp.route("/api/dm/conversations", methods=["GET"])
def list_conversations():
    user, error, code = authenticated_user()
    if error:
        return error, code

    convos = (DirectConversation.select()
              .where((DirectConversation.user1 == user) | (DirectConversation.user2 == user))
              .order_by(DirectConversation.last_message_at.desc()))

    result = []
    for c in convos:
        other = c.user2 if c.user1_id == user.id else c.user1
        last_msg = (DirectMessage.select()
                    .where(DirectMessage.conversation == c)
                    .order_by(DirectMessage.sent_at.desc())
                    .first())
        unread = (DirectMessage.select()
                  .where((DirectMessage.conversation == c) &
                         (DirectMessage.sender != user) &
                         (DirectMessage.read == False))
                  .count())
        result.append({
            "id": c.id,
            "other_user": {
                "id": other.id,
                "name": ((other.firstName or '') + ' ' + (other.lastName or '')).strip() or other.username,
                "custom_status": other.custom_status or "",
                "last_seen": other.last_seen.isoformat() if other.last_seen else None,
            },
            "last_message": {
                "content": last_msg.content if last_msg else "",
                "sent_at": last_msg.sent_at.isoformat() if last_msg else "",
            } if last_msg else None,
            "unread": unread,
        })

    return jsonify(result), 200


@dm_bp.route("/api/dm/conversation", methods=["POST"])
def get_or_create_conversation():
    user, error, code = authenticated_user()
    if error:
        return error, code

    data = request.get_json()
    other_id = data.get("user_id")
    other_username = data.get("username")

    if not other_id and not other_username:
        return {"status": "error", "message": "Missing user_id or username."}, 400

    try:
        if other_id:
            other = User.get_by_id(other_id)
        else:
            other = User.get(User.username == other_username)
    except DoesNotExist:
        return {"status": "error", "message": "User not found."}, 404

    if other.id == user.id:
        return {"status": "error", "message": "Can't DM yourself."}, 400

    u1, u2 = (user, other) if user.id < other.id else (other, user)
    convo, created = DirectConversation.get_or_create(user1=u1, user2=u2)

    return {
        "status": "success",
        "conversation": {
            "id": convo.id,
            "other_user": {
                "id": other.id,
                "name": ((other.firstName or '') + ' ' + (other.lastName or '')).strip() or other.username,
            }
        }
    }, 200


@dm_bp.route("/api/dm/messages", methods=["GET"])
def get_dm_messages():
    user, error, code = authenticated_user()
    if error:
        return error, code

    convo_id = request.args.get("conversation_id")
    if not convo_id:
        return {"status": "error", "message": "Missing conversation_id."}, 400

    try:
        convo = DirectConversation.get_by_id(convo_id)
    except DoesNotExist:
        return {"status": "error", "message": "Conversation not found."}, 404

    if convo.user1_id != user.id and convo.user2_id != user.id:
        return {"status": "error", "message": "Access denied."}, 403

    limit = min(int(request.args.get("limit", 50)), 200)

    msgs = (DirectMessage.select()
            .where(DirectMessage.conversation == convo)
            .order_by(DirectMessage.sent_at.desc())
            .limit(limit))

    message_list = []
    for m in reversed(list(msgs)):
        sender = m.sender
        message_list.append({
            "id": m.id,
            "sender_id": sender.id,
            "sender": ((sender.firstName or '') + ' ' + (sender.lastName or '')).strip() or sender.username,
            "content": m.content,
            "sent_at": m.sent_at.isoformat(),
            "read": m.read,
        })

    return {"status": "success", "messages": message_list}, 200


@dm_bp.route("/api/dm/send", methods=["POST"])
def send_dm():
    user, error, code = authenticated_user()
    if error:
        return error, code

    data = request.get_json()
    convo_id = data.get("conversation_id")
    content = data.get("message", "").strip()

    if not convo_id or not content:
        return {"status": "error", "message": "Missing conversation_id or message."}, 400

    try:
        convo = DirectConversation.get_by_id(convo_id)
    except DoesNotExist:
        return {"status": "error", "message": "Conversation not found."}, 404

    if convo.user1_id != user.id and convo.user2_id != user.id:
        return {"status": "error", "message": "Access denied."}, 403

    msg = DirectMessage.create(conversation=convo, sender=user, content=content)
    convo.last_message_at = datetime.now()
    convo.save()

    return {
        "status": "success",
        "message": {
            "id": msg.id,
            "sender_id": user.id,
            "sender": ((user.firstName or '') + ' ' + (user.lastName or '')).strip() or user.username,
            "content": msg.content,
            "sent_at": msg.sent_at.isoformat(),
            "read": False,
        }
    }, 201


@dm_bp.route("/api/dm/markRead", methods=["POST"])
def mark_read():
    user, error, code = authenticated_user()
    if error:
        return error, code

    data = request.get_json()
    convo_id = data.get("conversation_id")
    if not convo_id:
        return {"status": "error", "message": "Missing conversation_id."}, 400

    try:
        convo = DirectConversation.get_by_id(convo_id)
    except DoesNotExist:
        return {"status": "error", "message": "Conversation not found."}, 404

    if convo.user1_id != user.id and convo.user2_id != user.id:
        return {"status": "error", "message": "Access denied."}, 403

    other_id = convo.user2_id if convo.user1_id == user.id else convo.user1_id
    (DirectMessage.update(read=True)
     .where((DirectMessage.conversation == convo) &
            (DirectMessage.sender_id == other_id) &
            (DirectMessage.read == False))
     .execute())

    return {"status": "success"}, 200


@dm_bp.route("/api/dm/unread", methods=["GET"])
def get_unread():
    user, error, code = authenticated_user()
    if error:
        return error, code

    convos = (DirectConversation.select()
              .where((DirectConversation.user1 == user) | (DirectConversation.user2 == user)))

    total = 0
    for c in convos:
        other_id = c.user2_id if c.user1_id == user.id else c.user1_id
        count = (DirectMessage.select()
                 .where((DirectMessage.conversation == c) &
                        (DirectMessage.sender_id == other_id) &
                        (DirectMessage.read == False))
                 .count())
        total += count

    return {"status": "success", "unread": total}, 200
