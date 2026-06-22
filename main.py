import os
import random
import resend
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from peewee import PostgresqlDatabase, Model, CharField, IntegrityError, BooleanField

app = Flask(__name__)
CORS(app, origins=["https://hamzaahmedcollab.github.io"], supports_credentials=True)

# Core Environment Initializations
DB_URL = os.environ.get('DATABASE_URL')
resend.api_key = os.environ.get("RESEND_API_KEY")
db = PostgresqlDatabase(DB_URL)

# Database Table Layout
class User(Model):
    username = CharField(unique=True, max_length=50) # Stores the 'email' payload input
    password_hash = CharField(max_length=255)
    verified = BooleanField(default=False)
    verification_code = CharField(max_length=10)

    class Meta:
        database = db

# Table Engine Initialization Loop
with db:
    db.create_tables([User])

# Optimizing Neon Database connection pools per request
@app.before_request
def _db_connect():
    if db.is_closed():
        db.connect()

@app.after_request
def _db_close(response):
    if not db.is_closed():
        db.close()
    return response

# Numeric unique token algorithm 
def genCode():
    return "".join([str(random.randint(0, 9)) for i in range(4)])

# Endpoint 1: Registration and Token Mailer Outbound
@app.route("/api/signup", methods=["POST"])
def handleSignUp():
    data = request.get_json()
    if not data:
        return {"status": "error", "message": "Missing JSON payload"}, 400

    email       = data.get("email")
    password    = data.get("password")
    firstName   = data.get("firstname")
    lastName    = data.get("lastname")
    phoneNumber = data.get("phonenumber")

    if not email or not password or not firstName or not lastName or not phoneNumber:
        return {"status": "error", "message": "Missing fields."}, 400

    hashed_password = generate_password_hash(password)
    
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
            <div class="logo">🛠️ Our Space</div>
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

    try:
        code = genCode()
        newUser = User.create(username=email, password_hash=hashed_password, verified=False, verification_code=code)
        
        resend.Emails.send({
            "from": "onboarding@resend.dev",
            "to": email,
            "subject": "Verify your email",
            "html": email_html_body.format(secret_pin=code)
        })
         
        return {"status": "success", "message": "User created successfully. Verify email to get access."}, 200
    except IntegrityError:
        return {"status": "error", "message": "Email is already taken"}, 400

# Endpoint 2: Code Validation and Account Activation Check
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

# Endpoint 3: Verified User Validation and Session Cookie Issuance
@app.route("/api/login", methods=["POST"])
def handleLogin():
    data = request.get_json()
    if not data:
        return {"status": "error", "message": "Missing JSON payload"}, 400

    email       = data.get("email")
    password    = data.get("password")

    if not email or not password:
        return {"status": "error", "message": "Missing fields."}, 400

    try:
        user = User.get(User.username == email)
    except User.DoesNotExist:
        return {"status": "error", "message": "Invalid email or password"}, 401

    if check_password_hash(user.password_hash, password):
        if not user.verified:
            return {"status": "error", "message": "Please verify your email address first."}, 401
            
        # Packaging explicit response headers to hold the tracking session token cookie
        success_payload = jsonify({
            "status": "success", 
            "message": f"Welcome back, {user.username}!"
        })
        response = make_response(success_payload, 200)
        response.set_cookie(
            'session_user',      
            user.username,       
            max_age=86400 * 7,   
            httponly=True,       
            samesite='Lax',       
            secure=True        # Uncomment on Cloud Run deployment!
        )
        return response
    else:
        return {"status": "error", "message": "Invalid email or password"}, 401

@app.route("/api/check-session", methods=["GET"])
def check_session():
    # 1. Look for the secure cookie sent automatically by the browser
    logged_in_email = request.cookies.get('session_user')

    # 2. If the cookie is missing, they aren't logged in
    if not logged_in_email:
        return {"status": "unauthenticated", "message": "No active session found."}, 401

    try:
        # 3. Double-check with Neon to make sure this user actually exists and is active
        user = User.get(User.username == logged_in_email)
        
        # 4. If everything matches, tell the frontend who is logged in!
        return {
            "status": "authenticated", 
            "user": {
                "email": user.username,
                "verified": user.verified
            }
        }, 200
        
    except User.DoesNotExist:
        # If the cookie has an old email that was deleted, clear it out
        response = make_response(jsonify({"status": "unauthenticated", "message": "Session invalid."}), 401)
        response.set_cookie('session_user', '', expires=0)
        return response

# Endpoint 6: Clear Client Authentication Session Cookie
@app.route("/api/logout", methods=["POST"])
def handleLogout():
    success_json = jsonify({"status": "success", "message": "Logged out."})
    response = make_response(success_json, 200)
    
    # Force the user client browser to instantly delete the token header row
    response.set_cookie('session_user', '', expires=0, httponly=True, samesite='Lax', secure=True)
    return response


if __name__ == "__main__":
    app.run(debug=True)

