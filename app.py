import os
import sqlite3
from pathlib import Path

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "users.db"
UPLOAD_FOLDER = BASE_DIR / "uploads"
ALLOWED_EXTENSIONS = {"txt"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                firstname TEXT,
                lastname TEXT,
                email TEXT,
                address TEXT,
                limerick_filename TEXT
            )
            """
        )
        conn.commit()

    ensure_columns(
        {
            "firstname": "TEXT",
            "lastname": "TEXT",
            "email": "TEXT",
            "address": "TEXT",
            "limerick_filename": "TEXT",
        }
    )


def ensure_columns(columns):
    with get_db() as conn:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        for name, col_type in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {col_type}")
        conn.commit()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def require_login():
    username = session.get("username")
    if not username:
        flash("Please log in to continue.", "error")
        return None
    return username


def get_user(username):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()


def update_user_details(username, firstname, lastname, email, address):
    with get_db() as conn:
        conn.execute(
            """
            UPDATE users
            SET firstname = ?, lastname = ?, email = ?, address = ?
            WHERE username = ?
            """,
            (firstname, lastname, email, address, username),
        )
        conn.commit()


def update_user_file(username, filename):
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET limerick_filename = ? WHERE username = ?",
            (filename, username),
        )
        conn.commit()


def count_words(text):
    return len([word for word in text.split() if word.strip()])


def get_word_count(file_path):
    if not file_path or not Path(file_path).exists():
        return None
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
            return count_words(handle.read())
    except OSError:
        return None


@app.route("/", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("register.html", step="register")

        hashed = generate_password_hash(password)
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO users (username, password) VALUES (?, ?)",
                    (username, hashed),
                )
                conn.commit()
        except sqlite3.IntegrityError:
            flash("That username is already taken. Try another.", "error")
            return render_template("register.html", step="register")

        session["username"] = username
        flash("Account created. Add your details below.", "success")
        return redirect(url_for("details"))

    return render_template("register.html", step="register")


@app.route("/details", methods=["GET", "POST"])
def details():
    username = require_login()
    if not username:
        return redirect(url_for("login"))

    user = get_user(username)
    if not user:
        flash("Account not found. Please register again.", "error")
        return redirect(url_for("register"))

    if request.method == "POST":
        firstname = request.form.get("firstname", "").strip()
        lastname = request.form.get("lastname", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()

        update_user_details(username, firstname, lastname, email, address)
        flash("Profile details saved.", "success")
        return redirect(url_for("profile", username=username))

    return render_template("details.html", user=user, step="details")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("Both fields are required.", "error")
            return render_template("login.html", step="login")

        user = get_user(username)
        if not user:
            flash("Invalid username or password.", "error")
            return render_template("login.html", step="login")

        stored_password = user["password"] or ""
        is_hashed = stored_password.startswith("pbkdf2:") or stored_password.startswith(
            "scrypt:"
        )
        if is_hashed:
            valid = check_password_hash(stored_password, password)
        else:
            valid = stored_password == password

        if not valid:
            flash("Invalid username or password.", "error")
            return render_template("login.html", step="login")

        session["username"] = username
        flash("Welcome back!", "success")
        return redirect(url_for("profile", username=username))

    return render_template("login.html", step="login")


@app.route("/logout")
def logout():
    session.clear()
    flash("You are now logged out.", "success")
    return redirect(url_for("login"))


@app.route("/profile/<username>", methods=["GET", "POST"])
def profile(username):
    current_user = require_login()
    if not current_user:
        return redirect(url_for("login"))
    if current_user != username:
        flash("You can only access your own profile.", "error")
        return redirect(url_for("profile", username=current_user))

    user = get_user(username)
    if not user:
        flash("Profile not found.", "error")
        return redirect(url_for("register"))

    if request.method == "POST":
        if "limerick" not in request.files:
            flash("Please choose a file to upload.", "error")
            return redirect(url_for("profile", username=username))

        file = request.files["limerick"]
        if file.filename == "":
            flash("No file selected.", "error")
            return redirect(url_for("profile", username=username))

        if not allowed_file(file.filename):
            flash("Only .txt files are allowed.", "error")
            return redirect(url_for("profile", username=username))

        safe_name = secure_filename(file.filename)
        stored_name = f"{username}_Limerick.txt"
        if safe_name.lower() != "limerick.txt":
            flash("Uploaded file accepted. For grading, Limerick.txt is recommended.", "info")

        destination = UPLOAD_FOLDER / stored_name
        file.save(destination)
        update_user_file(username, stored_name)

        word_count = get_word_count(destination)
        if word_count is None:
            flash("File uploaded, but word count could not be read.", "error")
        else:
            flash(f"File uploaded. Word count: {word_count}", "success")

        return redirect(url_for("profile", username=username))

    file_path = None
    word_count = None
    if user["limerick_filename"]:
        file_path = UPLOAD_FOLDER / user["limerick_filename"]
        word_count = get_word_count(file_path)

    filled_fields = sum(
        1
        for key in ("firstname", "lastname", "email", "address")
        if (user[key] or "").strip()
    )
    completeness = int((filled_fields / 4) * 100)

    return render_template(
        "profile.html",
        user=user,
        step="profile",
        word_count=word_count,
        has_file=bool(user["limerick_filename"]),
        completeness=completeness,
    )


@app.route("/download/<username>")
def download(username):
    current_user = require_login()
    if not current_user:
        return redirect(url_for("login"))
    if current_user != username:
        flash("You can only download your own file.", "error")
        return redirect(url_for("profile", username=current_user))

    user = get_user(username)
    if not user or not user["limerick_filename"]:
        flash("No file available to download.", "error")
        return redirect(url_for("profile", username=username))

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        user["limerick_filename"],
        as_attachment=True,
    )


UPLOAD_FOLDER.mkdir(exist_ok=True)
init_db()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
