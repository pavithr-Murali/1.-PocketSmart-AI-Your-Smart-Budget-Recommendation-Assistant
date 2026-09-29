"""SQLite storage, password hashing, JWT auth, sessions and history."""
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import HTTPException, Request

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
ALGORITHM = "HS256"
TOKEN_MINUTES = 30
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pocketsmart.db")

blacklisted_tokens = set()
active_sessions = {}


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
            full_name TEXT, password_hash BLOB NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS history (
            id TEXT PRIMARY KEY, username TEXT NOT NULL, type TEXT NOT NULL,
            timestamp TEXT NOT NULL, input_json TEXT, result_json TEXT)""")


# ---------- users ----------
def create_user(username, email, password, full_name=None):
    username, email = username.strip().lower(), email.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{3,30}", username):
        raise HTTPException(400, "Username must be 3-30 letters, numbers or underscores")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "Enter a valid email address")
    if len(password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    pw = bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt())
    try:
        with db() as c:
            c.execute("INSERT INTO users VALUES (?,?,?,?)", (username, email, full_name, pw))
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Username or email is already registered")


def authenticate(username, password):
    with db() as c:
        row = c.execute("SELECT username, password_hash FROM users WHERE username=?",
                        (username.strip().lower(),)).fetchone()
    if row and bcrypt.checkpw(password.encode()[:72], bytes(row["password_hash"])):
        return row["username"]
    return None


# ---------- tokens and sessions ----------
def create_token(username):
    now = datetime.now(timezone.utc)
    payload = {"sub": username, "iat": now, "exp": now + timedelta(minutes=TOKEN_MINUTES)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_token(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:]
    return token


def touch_session(username):
    now = datetime.now()
    s = active_sessions.setdefault(username, {"login_time": now, "token": None, "user_data": {}})
    s["last_activity"] = now
    return s


def start_session(username, token):
    old = active_sessions.get(username)
    if old and old.get("token"):
        blacklisted_tokens.add(old["token"])
    now = datetime.now()
    active_sessions[username] = {"login_time": now, "last_activity": now, "token": token,
                                 "user_data": old["user_data"] if old else {}}


def end_session(token):
    blacklisted_tokens.add(token)
    try:
        username = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]).get("sub")
        active_sessions.pop(username, None)
    except jwt.PyJWTError:
        pass


def get_current_user(request: Request):
    token = get_token(request)
    if not token or token in blacklisted_tokens:
        raise HTTPException(401, "Not authenticated")
    try:
        username = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]).get("sub")
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired, please log in again")
    with db() as c:
        row = c.execute("SELECT username, email, full_name FROM users WHERE username=?",
                        (username,)).fetchone()
    if not row:
        raise HTTPException(401, "Unknown user")
    touch_session(username)
    return dict(row)


# ---------- history ----------
def save_history(username, rtype, input_data, result):
    rid = uuid.uuid4().hex[:12]
    with db() as c:
        c.execute("INSERT INTO history VALUES (?,?,?,?,?,?)",
                  (rid, username, rtype, datetime.now().isoformat(timespec="seconds"),
                   json.dumps(input_data, default=str), json.dumps(result)))
    return rid


def list_history(username):
    with db() as c:
        rows = c.execute("SELECT * FROM history WHERE username=? ORDER BY timestamp DESC",
                         (username,)).fetchall()
    out = []
    for r in rows:
        res = json.loads(r["result_json"] or "{}")
        out.append({"id": r["id"], "type": r["type"], "timestamp": r["timestamp"],
                    "input": json.loads(r["input_json"] or "{}"),
                    "summary": {"total_budget": res.get("total_budget"),
                                "remaining_budget": res.get("remaining_budget")}})
    return out


def get_history_item(username, rid):
    with db() as c:
        r = c.execute("SELECT * FROM history WHERE id=? AND username=?", (rid, username)).fetchone()
    if not r:
        raise HTTPException(404, "Recommendation not found")
    return {"id": r["id"], "type": r["type"], "timestamp": r["timestamp"],
            "input": json.loads(r["input_json"] or "{}"),
            "full_result": json.loads(r["result_json"] or "{}")}
