from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from app import db, app
import os

app = Flask(__name__, instance_relative_config=True)
app.config['SECRET_KEY'] = 'supersecret'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///chat.db"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
with app.app_context():
    db.create_all()

socketio = SocketIO(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

online_users = set()

# ---------------- MODELS ----------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, nullable=False)
    receiver_id = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, nullable=False)
    receiver_id = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


# ---------------- LOGIN ----------------

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------------- ROUTES ----------------

def get_friends(user_id):
    accepted = FriendRequest.query.filter(
        ((FriendRequest.sender_id == user_id) |
         (FriendRequest.receiver_id == user_id)) &
        (FriendRequest.status == "accepted")
    ).all()

    friend_ids = []
    for fr in accepted:
        if fr.sender_id == user_id:
            friend_ids.append(fr.receiver_id)
        else:
            friend_ids.append(fr.sender_id)

    return User.query.filter(User.id.in_(friend_ids)).all()

@app.route("/")
@login_required
def chat():
    friends = get_friends(current_user.id)
    requests = FriendRequest.query.filter_by(
        receiver_id=current_user.id,
        status="pending"
    ).all()

    return render_template("chat.html",
                           friends=friends,
                           requests=requests)


@app.route("/add_friend/<int:user_id>")
@login_required
def add_friend(user_id):
    if user_id == current_user.id:
        return redirect("/")

    existing = FriendRequest.query.filter(
        ((FriendRequest.sender_id == current_user.id) &
         (FriendRequest.receiver_id == user_id)) |
        ((FriendRequest.sender_id == user_id) &
         (FriendRequest.receiver_id == current_user.id))
    ).first()

    if not existing:
        fr = FriendRequest(
            sender_id=current_user.id,
            receiver_id=user_id
        )
        db.session.add(fr)
        db.session.commit()

    return redirect("/")

@app.route("/accept_friend/<int:req_id>")
@login_required
def accept_friend(req_id):
    fr = FriendRequest.query.get(req_id)
    if fr.receiver_id == current_user.id:
        fr.status = "accepted"
        db.session.commit()
    return redirect("/")

@app.route("/decline_friend/<int:req_id>")
@login_required
def decline_friend(req_id):
    fr = FriendRequest.query.get(req_id)
    if fr.receiver_id == current_user.id:
        fr.status = "declined"
        db.session.commit()
    return redirect("/")

@app.route("/users")
@login_required
def users():
    users = User.query.filter(User.id != current_user.id).all()
    return render_template("users.html", users=users)


@app.route("/messages/<int:user_id>")
@login_required
def get_messages(user_id):
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp).all()

    return [{
        "sender_id": m.sender_id,
        "text": m.text,
        "time": m.timestamp.strftime("%H:%M")
    } for m in messages]

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"]).first()
        if user and check_password_hash(user.password, request.form["password"]):
            login_user(user)
            return redirect("/")
        flash("Неверный логин или пароль")
    return render_template("login.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        if User.query.filter_by(username=request.form["username"]).first():
            flash("Пользователь уже существует")
            return redirect("/register")

        new_user = User(
            username=request.form["username"],
            password=generate_password_hash(request.form["password"])
        )
        db.session.add(new_user)
        db.session.commit()
        return redirect("/login")
    return render_template("register.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/login")

# ---------------- SOCKET ----------------

@socketio.on("connect")
def connect():
    if current_user.is_authenticated:
        online_users.add(current_user.id)
        join_room(str(current_user.id))
        emit("online_users", list(online_users), broadcast=True)

@socketio.on("disconnect")
def disconnect():
    if current_user.is_authenticated:
        online_users.discard(current_user.id)
        emit("online_users", list(online_users), broadcast=True)

@socketio.on("send_private")
def handle_private(data):
    msg = Message(
        sender_id=current_user.id,
        receiver_id=data["receiver_id"],
        text=data["message"]
    )
    db.session.add(msg)
    db.session.commit()

    emit("receive_private", {
        "sender_id": current_user.id,
        "receiver_id": data["receiver_id"],
        "message": data["message"],
        "time": msg.timestamp.strftime("%H:%M")
    }, room=str(data["receiver_id"]))

    emit("receive_private", {
        "sender_id": current_user.id,
        "receiver_id": data["receiver_id"],
        "message": data["message"],
        "time": msg.timestamp.strftime("%H:%M")
    }, room=str(current_user.id))

# ---------------- START ----------------

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)
    os.makedirs("instance", exist_ok=True)
    with app.app_context():
        db.create_all()
    socketio.run(app, debug=True)
