
from sqlalchemy.orm import Session

from app.models import Room

# Bekräftade Karriär-rum med kapacitet.
KARRIAR_CONFIRMED_ROOMS: list[tuple[str, int]] = [
    ("Akademisalen", 355),
    ("Aud Bruhn", 99),
    ("C214", 24),
    ("B529", 20),
    ("B625", 22),
    ("E610", 34),
    ("F724", 24),
    ("F606", 40),
    ("F506", 20),
    ("F507", 20),
    ("C215", 30),
    ("C608", 40),
    ("B216", 16),
    ("D701", 20),
    ("E716", 40),
    ("F612", 12),
    ("F406", 24),
    ("B429", 24),
    ("D302", 18),
]

# Tidigare namn → nytt (vid omstart)
ROOM_RENAMES: dict[str, str] = {
    "Auditorium Bruhn": "Aud Bruhn",
}


def seed_academill_rooms(db: Session) -> int:
    """Lägger till saknade Karriär-rum, byter namn vid behov och synkar kapacitet."""
    changed = 0

    for old_name, new_name in ROOM_RENAMES.items():
        room = db.query(Room).filter(Room.name == old_name).first()
        if room is None:
            continue
        if db.query(Room).filter(Room.name == new_name).first():
            continue
        room.name = new_name
        changed += 1

    by_name = {r.name: r for r in db.query(Room).all()}

    for name, capacity in KARRIAR_CONFIRMED_ROOMS:
        room = by_name.get(name)
        if room is None:
            db.add(Room(name=name, capacity=capacity))
            changed += 1
        elif room.capacity != capacity:
            room.capacity = capacity
            changed += 1

    if changed:
        db.commit()
    return changed
