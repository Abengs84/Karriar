"""Lås inspiratör → rum (alla pass ska ligga i samma rum)."""

from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from app.models import InspiratorRoomLock, SessionSlot


def room_locks_dict(db: Session) -> dict[str, int]:
    return {
        row.inspiration: row.room_id
        for row in db.query(InspiratorRoomLock).all()
    }


def list_room_locks(db: Session) -> list[dict]:
    rows = (
        db.query(InspiratorRoomLock)
        .options(joinedload(InspiratorRoomLock.room))
        .order_by(InspiratorRoomLock.inspiration)
        .all()
    )
    return [
        {
            "inspiration": row.inspiration,
            "room_id": row.room_id,
            "room_name": row.room.name if row.room else str(row.room_id),
        }
        for row in rows
    ]


def clear_room_locks(db: Session) -> int:
    n = db.query(InspiratorRoomLock).delete()
    db.flush()
    return n


def set_room_locks(db: Session, locks: dict[str, int]) -> int:
    clear_room_locks(db)
    count = 0
    for inspiration, room_id in locks.items():
        if not inspiration or room_id is None:
            continue
        db.add(InspiratorRoomLock(inspiration=inspiration, room_id=room_id))
        count += 1
    db.flush()
    return count


def locks_from_current_schedule(db: Session) -> dict[str, int]:
    """Ett rum per inspiratör: varje rum ägs av en inspiratör, ingen delar rum."""
    weight: dict[str, dict[int, int]] = {}
    by_room: dict[int, dict[str, int]] = {}
    slots = (
        db.query(SessionSlot)
        .options(joinedload(SessionSlot.placements))
        .all()
    )
    for slot in slots:
        n = len(slot.placements)
        if n == 0:
            continue
        weight.setdefault(slot.inspiration, {})
        weight[slot.inspiration][slot.room_id] = (
            weight[slot.inspiration].get(slot.room_id, 0) + n
        )
        by_room.setdefault(slot.room_id, {})
        by_room[slot.room_id][slot.inspiration] = (
            by_room[slot.room_id].get(slot.inspiration, 0) + n
        )

    room_owner: dict[int, str] = {
        rid: max(counts, key=counts.get)
        for rid, counts in by_room.items()
    }

    locks: dict[str, int] = {}
    used_rooms: set[int] = set()
    for inspiration, counts in sorted(
        weight.items(), key=lambda x: -sum(x[1].values())
    ):
        owned = [
            (counts[rid], rid)
            for rid in counts
            if room_owner.get(rid) == inspiration and rid not in used_rooms
        ]
        owned.sort(reverse=True)
        if owned:
            locks[inspiration] = owned[0][1]
            used_rooms.add(owned[0][1])
            continue
        free = [
            (counts[rid], rid)
            for rid in counts
            if rid not in used_rooms
        ]
        free.sort(reverse=True)
        if free:
            locks[inspiration] = free[0][1]
            used_rooms.add(free[0][1])

    return locks


def lock_all_inspirators_to_current_rooms(db: Session) -> int:
    locks = locks_from_current_schedule(db)
    return set_room_locks(db, locks)
