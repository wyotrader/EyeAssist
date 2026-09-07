from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, HTTPException, Response, status
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATABASE_URL, SESSION_COOKIE, SESSION_MAX_AGE_SECONDS, SESSION_SECRET, SESSION_SECURE

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Auth(Base):
    __tablename__ = "auth"

    id = Column(String, primary_key=True)
    email = Column(String)
    password = Column(Text)
    active = Column(Boolean)


class User(Base):
    __tablename__ = "user"

    id = Column(String, primary_key=True)
    name = Column(String)
    email = Column(String)
    role = Column(String)
    profile_image_url = Column(Text)


class LoginRequest(BaseModel):
    email: str
    password: str


class UserSession(BaseModel):
    id: str
    name: str
    email: str
    role: str


def verify_password(plain: str, hashed: str | None) -> bool:
    return bool(hashed and pwd_context.verify(plain, hashed))


def _safe_role(role: str | None) -> str | None:
    if role == "admin":
        return "admin"
    if role in {"clinician", "user"}:
        return "clinician"
    return None


def _session_for_user(user: User) -> UserSession:
    role = _safe_role(user.role)
    if role is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized")
    return UserSession(id=user.id, name=user.name or user.email, email=user.email, role=role)


def authenticate(email: str, password: str) -> UserSession | None:
    with SessionLocal() as db:
        auth = db.execute(select(Auth).where(Auth.email == email, Auth.active == True)).scalar_one_or_none()
        if not auth or not verify_password(password, auth.password):
            return None
        user = db.get(User, auth.id)
        return _session_for_user(user) if user and _safe_role(user.role) else None


def make_token(user: UserSession) -> str:
    expires = datetime.now(timezone.utc) + timedelta(seconds=SESSION_MAX_AGE_SECONDS)
    return jwt.encode({"sub": user.id, "role": user.role, "exp": expires}, SESSION_SECRET, algorithm="HS256")


def set_session_cookie(response: Response, user: UserSession) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        make_token(user),
        httponly=True,
        secure=SESSION_SECURE,
        samesite="lax",
        max_age=SESSION_MAX_AGE_SECONDS,
    )


def get_current_user(token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None) -> UserSession:
    if not token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authenticated")
    try:
        payload = jwt.decode(token, SESSION_SECRET, algorithms=["HS256"])
    except Exception:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authenticated")
    with SessionLocal() as db:
        user = db.get(User, payload.get("sub"))
        if not user:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authenticated")
        return _session_for_user(user)


def require_admin(user: Annotated[UserSession, Depends(get_current_user)]) -> UserSession:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin required")
    return user
