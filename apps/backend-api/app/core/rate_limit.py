"""Persistent, database-backed throttling for authentication endpoints."""

from __future__ import annotations

import hmac
import ipaddress
import os
import threading
import time

from fastapi import HTTPException, Request
from sqlalchemy import BigInteger, Column, Integer, String, Table, case, delete
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config.database import Base


auth_rate_limit_windows = Table(
    "auth_rate_limit_windows",
    Base.metadata,
    Column("key_hash", String(64), primary_key=True),
    Column("window_started_at", BigInteger, nullable=False),
    Column("request_count", Integer, nullable=False),
    Column("updated_at", BigInteger, nullable=False, index=True),
)

_cleanup_lock = threading.Lock()
_last_cleanup = 0


def _canonical_client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    address = peer
    # Render sets the actual client IP at the beginning of X-Forwarded-For.
    if os.getenv("RENDER", "").lower() == "true":
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            address = forwarded
    try:
        return str(ipaddress.ip_address(address))
    except ValueError:
        return "unknown"


def _record_attempt(db: Session, key: str, window_seconds: int) -> tuple[int, int]:
    now = int(time.time())
    window_started_at = now - (now % window_seconds)
    secret_key = os.getenv("SECRET_KEY", "")
    if not secret_key:
        raise RuntimeError("SECRET_KEY no está configurada para proteger los contadores de autenticación.")
    key_hash = hmac.new(secret_key.encode("utf-8"), key.encode("utf-8"), "sha256").hexdigest()
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        insert = postgresql_insert
    elif dialect == "sqlite":
        insert = sqlite_insert
    else:
        raise RuntimeError(f"Rate limiting no está implementado para el motor {dialect}.")

    same_window = auth_rate_limit_windows.c.window_started_at == window_started_at
    statement = insert(auth_rate_limit_windows).values(
        key_hash=key_hash,
        window_started_at=window_started_at,
        request_count=1,
        updated_at=now,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[auth_rate_limit_windows.c.key_hash],
        set_={
            "window_started_at": case((same_window, auth_rate_limit_windows.c.window_started_at), else_=window_started_at),
            "request_count": case((same_window, auth_rate_limit_windows.c.request_count + 1), else_=1),
            "updated_at": now,
        },
    ).returning(auth_rate_limit_windows.c.request_count)

    try:
        count = db.execute(statement).scalar_one()
        db.commit()
    except Exception:
        db.rollback()
        raise

    _prune_expired_windows(db, now)
    retry_after = max(1, window_started_at + window_seconds - now)
    return count, retry_after


def _prune_expired_windows(db: Session, now: int) -> None:
    global _last_cleanup
    if now - _last_cleanup < 300 or not _cleanup_lock.acquire(blocking=False):
        return
    try:
        _last_cleanup = now
        db.execute(delete(auth_rate_limit_windows).where(auth_rate_limit_windows.c.updated_at < now - 86400))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        _cleanup_lock.release()


def enforce_rate_limit(
    db: Session,
    request: Request,
    category: str,
    subject: str,
    *,
    max_requests: int,
    window_seconds: int,
    include_client_ip: bool = True,
) -> None:
    """Count an attempt across API instances; reject over-limit requests."""
    source = _canonical_client_ip(request) if include_client_ip else "all-clients"
    key = f"{category}:{source}:{subject}"
    count, retry_after = _record_attempt(db, key, window_seconds)
    if count > max_requests:
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos. Espera un momento e inténtalo de nuevo.",
            headers={"Retry-After": str(retry_after)},
        )
