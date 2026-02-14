"""
Smart Office Assistant - Authentication
Login verification and user storage in login.json.
"""
import json
from pathlib import Path
from typing import Tuple

from config import LOGIN_FILE


def ensure_login_file() -> None:
    """Create login.json with default Admin user if it does not exist."""
    LOGIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not LOGIN_FILE.exists():
        data = {
            "users": [
                {"email": "Admin", "password": "Admin", "role": "admin"}
            ]
        }
        with open(LOGIN_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


def load_login_data() -> dict:
    """Load login.json; ensure file exists first."""
    ensure_login_file()
    with open(LOGIN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_login_data(data: dict) -> None:
    """Save login.json."""
    with open(LOGIN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def verify_user(email: str, password: str) -> Tuple[bool, bool]:
    """
    Verify email and password against login.json.
    Returns (success, is_admin).
    """
    email = (email or "").strip()
    password = (password or "").strip()
    if not email or not password:
        return False, False

    data = load_login_data()
    for user in data.get("users", []):
        if (user.get("email", "").strip() == email and
                user.get("password", "").strip() == password):
            return True, (user.get("role", "").strip().lower() == "admin")
    return False, False
