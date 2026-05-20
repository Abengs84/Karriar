
from sqlalchemy.orm import Session

from app.models import Room

# Bekräftade Karriär-rum med kapacitet.
KARRIAR_CONFIRMED_ROOMS: list[tuple[str, int]] = [
    ("Akademisalen", 355),
    ("Auditorium Bruhn", 99),
    ("B215", 30),
    ("B216", 30),
    ("B529", 20),
    ("B624", 22),
    ("B625", 22),
    ("C214", 30),
    ("C215", 30),
    ("C608", 30),
    ("D402", 55),
    ("D404", 25),
    ("D405", 35),
    ("D406", 24),
    ("D505", 24),
    ("D508", 30),
    ("D701", 30),
    ("E610", 34),
    ("E716", 30),
    ("F406", 30),
    ("F506", 15),
    ("F507", 15),
    ("F606", 40),
    ("F612", 30),
    ("F724", 24),
]

# Tidigare namn → nytt (vid omstart)
ROOM_RENAMES: dict[str, str] = {
    "Aud Bruhn": "Auditorium Bruhn",
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
