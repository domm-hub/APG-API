import os
import json
import random

from flask import Flask, request, jsonify
from flask_cors import CORS
from itsdangerous import URLSafeTimedSerializer

from db import db, init_db, run_migrations
from utils import init_utils

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())
app.config["ADMIN_PASSWORD_HASH"] = os.environ.get("ADMIN_PASSWORD_HASH")
CORS(app, origins=["https://hamzaahmedcollab.github.io", "https://apg-two.vercel.app"], supports_credentials=True)

token_serializer = URLSafeTimedSerializer(app.secret_key, salt="auth")
init_utils(token_serializer)

from routes.auth import auth_bp
from routes.chat import chat_bp
from routes.admin import admin_bp
from routes.user import user_bp
from routes.requests import requests_bp
from routes.dm import dm_bp

app.register_blueprint(auth_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(user_bp)
app.register_blueprint(requests_bp)
app.register_blueprint(dm_bp)

from roasts import ROASTS

init_db()


@app.before_request
def _db_connect():
    if not db:
        return
    try:
        db.connect()
        run_migrations()
    except Exception:
        pass


@app.after_request
def inject_action_field(response):
    if response.is_json:
        try:
            data = response.get_json()
            if isinstance(data, dict):
                data.setdefault("action", "none")
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        item.setdefault("action", "none")
            response.set_json(data)
        except Exception as e:
            print(f"Error injecting action field: {e}", flush=True)
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
            body = json.loads(response.get_data(as_text=True))
            if isinstance(body, dict):
                body["roast"] = random.choice(ROASTS)
                response.set_data(json.dumps(body))
        except Exception:
            pass
    return response


if __name__ == "__main__":
    app.run(debug=True)
