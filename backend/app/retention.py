"""Automatisk radering av elevdata efter Excel-import."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Placement, SessionSlot, Student, SystemMeta

META_PURGE_AT = "purge_scheduled_at"
PURGE_CHECK_INTERVAL_SEC = 30


def retention_hours() -> int:
    raw = os.getenv("KARRIAR_RETENTION_HOURS", "3")
    try:
        hours = int(raw)
    except ValueError:
        hours = 3
    return max(1, min(hours, 168))


def retention_enabled() -> bool:
    return os.getenv("KARRIAR_RETENTION_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _get_meta(db: Session, key: str) -> str | None:
    row = db.query(SystemMeta).filter(SystemMeta.key == key).first()
    return row.value if row else None


def _set_meta(db: Session, key: str, value: str | None) -> None:
    row = db.query(SystemMeta).filter(SystemMeta.key == key).first()
    if value is None:
        if row:
            db.delete(row)
        return
    if row:
        row.value = value
    else:
        db.add(SystemMeta(key=key, value=value))


def get_purge_scheduled_at(db: Session) -> datetime | None:
    raw = _get_meta(db, META_PURGE_AT)
    if not raw:
        return None
    return _parse_iso(raw)


def clear_purge_schedule(db: Session) -> None:
    _set_meta(db, META_PURGE_AT, None)


def schedule_purge_after_import(db: Session) -> datetime:
    """Schemalägg radering RETENTION_HOURS efter senaste import."""
    if not retention_enabled():
        clear_purge_schedule(db)
        db.commit()
        return _utcnow()

    at = _utcnow() + timedelta(hours=retention_hours())
    _set_meta(db, META_PURGE_AT, at.isoformat())
    db.commit()
    return at


def retention_status(db: Session) -> dict:
    purge_at = get_purge_scheduled_at(db)
    hours = retention_hours()
    if not retention_enabled() or purge_at is None:
        return {
            "enabled": retention_enabled(),
            "purge_at": None,
            "seconds_remaining": None,
            "retention_hours": hours,
        }
    remaining = int((purge_at - _utcnow()).total_seconds())
    if remaining < 0:
        remaining = 0
    return {
        "enabled": True,
        "purge_at": purge_at.isoformat(),
        "seconds_remaining": remaining,
        "retention_hours": hours,
    }


def purge_student_data(db: Session) -> dict:
    """Radera elever, placeringar och schemaceller (rum behålls)."""
    removed_placements = db.query(Placement).delete()
    removed_students = db.query(Student).delete()
    removed_session_slots = db.query(SessionSlot).delete()
    clear_purge_schedule(db)
    db.commit()
    return {
        "ok": True,
        "removed_placements": removed_placements,
        "removed_students": removed_students,
        "removed_session_slots": removed_session_slots,
    }


def check_and_purge_if_due(db: Session) -> dict | None:
    if not retention_enabled():
        return None
    purge_at = get_purge_scheduled_at(db)
    if purge_at is None:
        return None
    if _utcnow() < purge_at:
        return None
    return purge_student_data(db)


async def retention_worker() -> None:
    while True:
        await asyncio.sleep(PURGE_CHECK_INTERVAL_SEC)
        db = SessionLocal()
        try:
            check_and_purge_if_due(db)
        except Exception:
            db.rollback()
        finally:
            db.close()
