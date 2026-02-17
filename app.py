from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ---------------------------
# DATABASE SETUP
# ---------------------------
url = os.environ.get("DATABASE_URL")
if url is None:
    # локальная разработка
    url = "sqlite:///chat.db"
elif url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app)

# ---------------------------
# LOGIN SETUP
# ---------------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# ---------------------------
# MODELS
# ---------------------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    online = db.Column(db.Boolean, default=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class FriendRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), default="pending")  # pending, accepted, rejected

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=True)  # номер телефона
    online = db.Column(db.Boolean, default=False)


# ---------------------------
# LOGIN MANAGER
# ---------------------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------------------------
# ROUTES
# ---------------------------
@app.route("/add_friend", methods=["GET", "POST"])
@login_required
def add_friend():
    if request.method == "POST":
        phone = request.form.get("phone")
        friend = User.query.filter_by(phone=phone).first()
        if not friend:
            flash("Пользователь с таким номером не найден")
            return redirect(url_for("add_friend"))
        # Проверяем, нет ли уже запроса
        existing = FriendRequest.query.filter_by(sender_id=current_user.id, receiver_id=friend.id).first()
        if existing:
            flash("Запрос уже отправлен")
            return redirect(url_for("friends"))
        fr = FriendRequest(sender_id=current_user.id, receiver_id=friend.id)
        db.session.add(fr)
        db.session.commit()
        flash("Запрос отправлен!")
        return redirect(url_for("friends"))
    return render_template("add_friend.html")

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("chat"))
    return redirect(url_for("login"))

# ---------- REGISTER ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if not username or not password:
            flash("Заполните все поля")
            return redirect(url_for("register"))
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("Пользователь уже существует")
            return redirect(url_for("register"))
        hashed_pw = generate_password_hash(password)
        user = User(username=username, password=hashed_pw)
        db.session.add(user)
        db.session.commit()
        flash("Регистрация успешна! Войдите в систему")
        return redirect(url_for("login"))
    return render_template("register.html")

# ---------- LOGIN ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            user.online = True
            db.session.commit()
            return redirect(url_for("chat"))
        flash("Неверный логин или пароль")
    return render_template("login.html")

# ---------- LOGOUT ----------
@app.route("/logout")
@login_required
def logout():
    current_user.online = False
    db.session.commit()
    logout_user()
    return redirect(url_for("login"))

# ---------- CHAT ----------
@app.route("/chat")
@login_required
def chat():
    users = User.query.filter(User.id != current_user.id).all()
    return render_template("chat.html", users=users)

# ---------- FRIENDS ----------
@app.route("/friends")
@login_required
def friends():
    incoming = FriendRequest.query.filter_by(receiver_id=current_user.id, status="pending").all()
    return render_template("friends.html", requests=incoming)

# ---------------------------
# SOCKETIO EVENTS
# ---------------------------
@socketio.on("join")
def on_join(data):
    room = data["room"]
    join_room(room)

@socketio.on("send_message")
def handle_message(data):
    sender_id = current_user.id
    receiver_id = data["receiver_id"]
    text = data["text"]
    msg = Message(sender_id=sender_id, receiver_id=receiver_id, text=text)
    db.session.add(msg)
    db.session.commit()
    room = f"chat_{min(sender_id, receiver_id)}_{max(sender_id, receiver_id)}"
    emit("receive_message", {"sender_id": sender_id, "text": text}, room=room)

# ---------------------------
# DATABASE CREATION
# ---------------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()  # создаёт таблицы автоматически
    socketio.run(app, host="0.0.0.0", port=5000)
