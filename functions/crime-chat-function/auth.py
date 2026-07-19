"""
Role-Based Secure Access for KRIME AI
--------------------------------------
Lightweight username/password authentication with sqlite-backed session
tokens (no external identity provider needed) -- sufficient for a hackathon
POC while still demonstrating *real* role gating between API endpoints.

Roles (least -> most privileged is NOT implied; each role simply has a
different slice of the platform it is allowed to use):
  - Admin      : full access, including destructive ops (Reload DB)
  - SP         : full investigative + analytics access (no destructive ops)
  - Inspector  : chat / dashboards / analytics / network / PDF export
  - Analyst    : read-only chat / dashboards / analytics (no network graph,
                 no PDF export, no anomaly scan -- protects sensitive
                 criminal-identity data from non-investigative staff)
"""
import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta

SESSION_TTL_HOURS = 12

ROLES = ["Admin", "SP", "Inspector", "Analyst"]

# Seeded demo accounts (password shown in UI for hackathon judges to try
# different roles quickly). In a real deployment these would be created
# through an admin-only user-management flow with hashed/rotated secrets.
DEFAULT_USERS = [
    # username,     password,          role,         full_name,                                   badge
    ("admin",       "Admin@123",       "Admin",      "System Administrator",                       "KA-ADMIN"),
    ("sp.blru",     "Sp@12345",        "SP",         "SP - Bengaluru Urban",                        "KA-1001"),
    ("inspector1",  "Inspector@123",   "Inspector",  "Inspector Ravi Kumar",                         "KA-2041"),
    ("analyst1",    "Analyst@123",     "Analyst",    "Crime Data Analyst - Priya Sharma",            "KA-3007"),
]


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def ensure_auth_tables(conn: sqlite3.Connection):
    """Create the users/sessions tables (idempotent) and seed demo users."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        role TEXT NOT NULL,
        full_name TEXT,
        badge_number TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS auth_sessions (
        token TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        role TEXT NOT NULL,
        full_name TEXT,
        badge_number TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT NOT NULL
    );
    """)
    conn.commit()

    row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    if row and row[0] == 0:
        for username, password, role, full_name, badge in DEFAULT_USERS:
            salt = secrets.token_hex(8)
            conn.execute(
                "INSERT INTO users (username, password_hash, salt, role, full_name, badge_number) "
                "VALUES (?,?,?,?,?,?)",
                (username, _hash_password(password, salt), salt, role, full_name, badge),
            )
        conn.commit()


def verify_login(conn: sqlite3.Connection, username: str, password: str):
    """Return the user dict if credentials are valid, else None."""
    ensure_auth_tables(conn)
    row = conn.execute(
        "SELECT username, password_hash, salt, role, full_name, badge_number "
        "FROM users WHERE username = ?",
        (username.strip().lower(),),
    ).fetchone()
    if not row:
        return None
    db_username, password_hash, salt, role, full_name, badge = row
    if _hash_password(password, salt) != password_hash:
        return None
    return {"username": db_username, "role": role, "full_name": full_name, "badge_number": badge}


def create_session(conn: sqlite3.Connection, user: dict) -> str:
    ensure_auth_tables(conn)
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(hours=SESSION_TTL_HOURS)).isoformat()
    conn.execute(
        "INSERT INTO auth_sessions (token, username, role, full_name, badge_number, expires_at) "
        "VALUES (?,?,?,?,?,?)",
        (token, user["username"], user["role"], user["full_name"], user["badge_number"], expires_at),
    )
    conn.commit()
    return token


def get_session_user(conn: sqlite3.Connection, token: str):
    """Return the user dict for a valid, non-expired session token."""
    if not token:
        return None
    ensure_auth_tables(conn)
    row = conn.execute(
        "SELECT username, role, full_name, badge_number, expires_at FROM auth_sessions WHERE token = ?",
        (token,),
    ).fetchone()
    if not row:
        return None
    username, role, full_name, badge, expires_at = row
    try:
        if datetime.fromisoformat(expires_at) < datetime.utcnow():
            conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
            conn.commit()
            return None
    except ValueError:
        pass
    return {"username": username, "role": role, "full_name": full_name, "badge_number": badge}


def delete_session(conn: sqlite3.Connection, token: str):
    ensure_auth_tables(conn)
    conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
    conn.commit()


def extract_token(req) -> str:
    """Pull the bearer token out of the Authorization header (or the
    X-Auth-Token fallback header, useful for simple GET requests)."""
    header = req.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return req.headers.get("X-Auth-Token", "").strip()
