"""Authentication and Database Authorization Module for SQLPilot Web.

Provides:
- User ID & password authentication
- Salted password hashing (PBKDF2-HMAC-SHA256)
- Secure session token management
- Role-based authorization for database access and switching
"""

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class User:
    """Authenticated user entity."""

    username: str
    password_hash: str
    salt: str
    role: str  # "admin", "analyst", "viewer"
    authorized_databases: List[str]  # e.g. ["*"] for all, or ["sample_store.db"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "username": self.username,
            "role": self.role,
            "authorized_databases": self.authorized_databases,
        }


@dataclass
class Session:
    """Active user session."""

    token: str
    username: str
    role: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 86400)  # 24 hours

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


def _hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Generate salted PBKDF2-HMAC-SHA256 password hash."""
    if not salt:
        salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=100_000,
    ).hex()
    return pw_hash, salt


class AuthService:
    """Handles authentication, session tokens, and database access authorization."""

    def __init__(self):
        self.users: Dict[str, User] = {}
        self.sessions: Dict[str, Session] = {}
        self._init_default_users()

    def _init_default_users(self):
        """Seed default admin and analyst users with configurable overrides."""
        admin_pw = os.getenv("SQLPILOT_ADMIN_PASSWORD", "admin123")
        analyst_pw = os.getenv("SQLPILOT_ANALYST_PASSWORD", "analyst123")

        admin_hash, admin_salt = _hash_password(admin_pw)
        analyst_hash, analyst_salt = _hash_password(analyst_pw)

        self.users["admin"] = User(
            username="admin",
            password_hash=admin_hash,
            salt=admin_salt,
            role="admin",
            authorized_databases=["*"],
        )

        self.users["analyst"] = User(
            username="analyst",
            password_hash=analyst_hash,
            salt=analyst_salt,
            role="analyst",
            authorized_databases=["sample_store.db"],
        )

    def authenticate(self, username: str, password: str) -> Optional[Session]:
        """Authenticate user by username and password. Returns Session on success."""
        clean_user = username.strip().lower()
        user = self.users.get(clean_user)
        if not user:
            return None

        # Verify password using constant-time comparison
        test_hash, _ = _hash_password(password, user.salt)
        if not hmac.compare_digest(user.password_hash, test_hash):
            return None

        # Issue secure session token
        token = secrets.token_urlsafe(32)
        session = Session(
            token=token,
            username=user.username,
            role=user.role,
        )
        self.sessions[token] = session
        return session

    def verify_token(self, token: str) -> Optional[Session]:
        """Verify session token and ensure it has not expired."""
        if not token:
            return None
        session = self.sessions.get(token)
        if not session:
            return None
        if session.is_expired:
            del self.sessions[token]
            return None
        return session

    def logout(self, token: str) -> bool:
        """Invalidate active session."""
        if token in self.sessions:
            del self.sessions[token]
            return True
        return False

    def is_authorized_for_database(self, username: str, db_name: str) -> bool:
        """Check if user has permission to connect/switch to database."""
        user = self.users.get(username.strip().lower())
        if not user:
            return False

        if "*" in user.authorized_databases or user.role == "admin":
            return True

        clean_db = db_name.strip().lower()
        clean_db_stem = os.path.splitext(clean_db)[0]

        for auth_db in user.authorized_databases:
            target = auth_db.lower()
            target_stem = os.path.splitext(target)[0]
            if clean_db == target or clean_db_stem == target_stem:
                return True

        return False

    def get_user(self, username: str) -> Optional[User]:
        return self.users.get(username.strip().lower())


# Global singleton auth service instance
auth_service = AuthService()
