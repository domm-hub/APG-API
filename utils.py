import os
import random
import smtplib
from email.message import EmailMessage

from flask import request
from werkzeug.security import check_password_hash
from peewee import DoesNotExist

from db import User, Group, GroupMember

TOKEN_EXPIRY = 86400 * 7

_token_serializer = None


def init_utils(token_serializer):
    global _token_serializer
    _token_serializer = token_serializer


def make_token(email):
    return _token_serializer.dumps(email)


def read_token(token):
    return _token_serializer.loads(token, max_age=TOKEN_EXPIRY)


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
            <div class="logo">AP<b>G</b></div>
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
    msg["From"] = os.environ.get("SMTP_FROM")
    msg["To"] = to
    msg["Subject"] = "Verify your email"
    msg.set_content(f"Your verification code is: {code}")
    msg.add_alternative(email_html_body.format(secret_pin=code), subtype="html")

    smtp_host = os.environ.get("SMTP_HOST", "://gmail.com")
    smtp_login = os.environ.get("SMTP_LOGIN")
    smtp_password = os.environ.get("SMTP_PASSWORD")

    with smtplib.SMTP(smtp_host, 587) as s:
        s.set_debuglevel(1)
        s.starttls()
        s.login(smtp_login, smtp_password)
        s.send_message(msg)


def authenticated_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, {"status": "error", "message": "Not authenticated."}, 401
    try:
        email = read_token(auth[7:])
        return User.get(User.username == email), None, None
    except (Exception, User.DoesNotExist):
        return None, {"status": "error", "message": "Invalid or expired token."}, 401


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


def join_group(user, group):
    try:
        member, created = GroupMember.get_or_create(group=group, user=user)
        return created
    except Exception:
        return False


def list_group(group):
    query = (User
             .select()
             .join(GroupMember)
             .where(GroupMember.group == group))
    return list(query)


def getGroupByID(group_id):
    if not group_id:
        return False
    return Group.get_or_none(Group.id == group_id)


def getGroupIdByCode(code):
    if not code:
        return False
    group = Group.get_or_none(Group.code == code)
    return group.id if group else False
