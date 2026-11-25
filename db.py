"""
db.py
------
SQLite storage layer, running in WAL (Write-Ahead Log) mode as required.
Handles: user accounts, email verification codes, and a persisted copy of
orders/trades per symbol so a user's history survives app restarts (the C
engine itself is purely in-memory per running process).
"""

import sqlite3
import os
import time
import secrets
import hashlib
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "app.db")


def _ensure_dir():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)


@contextmanager
def get_conn():
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")   # <-- WAL storage, as required
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT UNIQUE NOT NULL,
                username      TEXT UNIQUE,
                password_hash TEXT,
                salt          TEXT,
                verified      INTEGER NOT NULL DEFAULT 0,
                created_at    REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS verification_codes (
                email      TEXT PRIMARY KEY,
                code       TEXT NOT NULL,
                expires_at REAL NOT NULL,
                attempts   INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS order_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                symbol     TEXT NOT NULL,
                side       TEXT NOT NULL,
                order_type TEXT NOT NULL,
                price      REAL,
                qty        INTEGER NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS trade_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                symbol     TEXT NOT NULL,
                price      REAL NOT NULL,
                qty        INTEGER NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )


# ---------------------------------------------------------------------- #
# Password hashing (PBKDF2, no external deps)
# ---------------------------------------------------------------------- #

def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return digest.hex(), salt


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    digest, _ = hash_password(password, salt)
    return secrets.compare_digest(digest, expected_hash)


# ---------------------------------------------------------------------- #
# Users
# ---------------------------------------------------------------------- #

def get_user_by_email(email: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
        return dict(row) if row else None


def create_user(email: str, username: str, password: str):
    pw_hash, salt = hash_password(password)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (email, username, password_hash, salt, verified, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (email.lower().strip(), username.strip(), pw_hash, salt, time.time()),
        )


def authenticate(email: str, password: str):
    user = get_user_by_email(email)
    if not user or not user["password_hash"]:
        return None
    if verify_password(password, user["salt"], user["password_hash"]):
        return user
    return None


# ---------------------------------------------------------------------- #
# Email verification codes
# ---------------------------------------------------------------------- #

def issue_verification_code(email: str, ttl_seconds: int = 600) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO verification_codes (email, code, expires_at, attempts) "
            "VALUES (?, ?, ?, 0) "
            "ON CONFLICT(email) DO UPDATE SET code=excluded.code, expires_at=excluded.expires_at, attempts=0",
            (email.lower().strip(), code, time.time() + ttl_seconds),
        )
    return code


def check_verification_code(email: str, code: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM verification_codes WHERE email = ?", (email.lower().strip(),)
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE verification_codes SET attempts = attempts + 1 WHERE email = ?",
            (email.lower().strip(),),
        )
        if time.time() > row["expires_at"]:
            return False
        if row["attempts"] >= 5:
            return False
        return secrets.compare_digest(row["code"], code.strip())


# ---------------------------------------------------------------------- #
# Order / trade history (for charts)
# ---------------------------------------------------------------------- #

def log_order(user_id, symbol, side, order_type, price, qty):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO order_history (user_id, symbol, side, order_type, price, qty, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, symbol, side, order_type, price, qty, time.time()),
        )


def log_trade(user_id, symbol, price, qty):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO trade_history (user_id, symbol, price, qty, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, symbol, price, qty, time.time()),
        )


def get_trade_history(user_id, symbol=None, limit=500):
    with get_conn() as conn:
        if symbol:
            rows = conn.execute(
                "SELECT * FROM trade_history WHERE user_id = ? AND symbol = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, symbol, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trade_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]


def get_order_history(user_id, symbol=None, limit=500):
    with get_conn() as conn:
        if symbol:
            rows = conn.execute(
                "SELECT * FROM order_history WHERE user_id = ? AND symbol = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, symbol, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM order_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]
