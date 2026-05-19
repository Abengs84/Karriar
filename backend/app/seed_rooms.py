
from sqlalchemy.orm import Session

from app.models import Room

# Bekräftade Karriär-rum med uppskattad kapacitet (Academill-kategorier).
KARRIAR_CONFIRMED_ROOMS: list[tuple[str, int]] = [
    ("Akademisalen", 120),
    ("Aud Bruhn", 80),
    ("C214", 80),
    ("C215", 80),
    ("C608", 35),
    ("B529", 25),
    ("B625", 25),
    ("B216", 30),
    ("D701", 25),
    ("E716", 30),
    ("E610", 30),
    ("F724", 30),
    ("F612", 25),
    ("F606", 25),
    ("F506", 20),
    ("F507", 20),
    ("F406", 20),
]


def seed_academill_rooms(db: Session) -> int:
    """Lägger till saknade Karriär-rum och synkar kapacitet. Returnerar antal ändringar."""
    by_name = {r.name: r for r in db.query(Room).all()}
    changed = 0

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
