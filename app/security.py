import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt
from dotenv import load_dotenv
from pwdlib import PasswordHash


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_FILE, override=True)



SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
)


if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is missing. Add it to the project's .env file."
    )


password_hasher = PasswordHash.recommended()


def hash_password(plain_password: str) -> str:
    """
    Convert a plain-text password into a secure one-way hash.
    """
    return password_hasher.hash(plain_password)


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    """
    Check whether a plain-text password matches a stored hash.
    """
    return password_hasher.verify(
        plain_password,
        hashed_password,
    )


def create_access_token(
    subject: str,
    additional_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a signed JWT access token.

    The subject should uniquely identify the authenticated user.
    """
    now = datetime.now(timezone.utc)

    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": expire,
    }

    if additional_claims:
        payload.update(additional_claims)

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Validate a JWT signature and expiration, then return its payload.

    PyJWT raises an exception when the token is invalid or expired.
    """
    return jwt.decode(
        token,
        SECRET_KEY,
        algorithms=[ALGORITHM],
    )