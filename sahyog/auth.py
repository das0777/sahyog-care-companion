"""Dev identity: local HS256 tokens standing in for OIDC, as agreed for S0.

Every request gets an AuthContext: who is calling, in which role, for what purpose, and the
trace id that ties its audit rows together.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sahyog.config import get_settings

ALGORITHM = "HS256"


class Role(StrEnum):
    PATIENT = "patient"
    CAREGIVER = "caregiver"
    DOCTOR = "doctor"
    DESK = "desk"
    PHARMACIST = "pharmacist"
    COMPLIANCE = "compliance"


# Purpose recorded on the audit row when the caller sends no X-Purpose header
DEFAULT_PURPOSE = {
    Role.PATIENT: "self_access",
    Role.CAREGIVER: "caregiving",
    Role.DOCTOR: "treatment",
    Role.DESK: "scheduling",
    Role.PHARMACIST: "dispensing",
    Role.COMPLIANCE: "audit",
}


@dataclass(frozen=True)
class AuthContext:
    actor_id: str
    role: Role
    purpose: str
    trace_id: str


def issue_token(role: Role, actor_id: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    claims = {
        "sub": actor_id,
        "role": role.value,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


_bearer = HTTPBearer(auto_error=False)


def get_auth_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_purpose: str | None = Header(default=None, max_length=40),
) -> AuthContext:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        claims = jwt.decode(
            credentials.credentials,
            get_settings().jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "role", "exp"]},
        )
        role = Role(claims["role"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    return AuthContext(
        actor_id=claims["sub"],
        role=role,
        purpose=x_purpose or DEFAULT_PURPOSE[role],
        trace_id=request.state.trace_id,
    )


def new_trace_id() -> str:
    return uuid.uuid4().hex
