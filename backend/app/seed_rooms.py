
from sqlalchemy.orm import Session

from app.models import Room

# Mellanstora seminarierum ~20–30 platser (vi använder 25)
ACADEMILL_SEMINAR_ROOMS: list[tuple[str, int]] = [
    ("B0216 Seminarie rum", 25),
    ("B0429 SI sem.", 25),
    ("B0529 Seminarierum", 25),
    ("B0607 Seminarierum", 25),
    ("B0624 Sem.rum", 25),
    ("B0625 Sem.rum", 25),
    ("C0214 Seminarierum", 25),
    ("C0215 Seminarie rum", 25),
    ("D0402 Seminarierum", 25),
    ("D0404 Finska sem.rum", 25),
    ("D0405 Modersmål sem.rum", 25),
    ("D0406 Engelska sem.rum", 25),
    ("D0505 Matematik sem.rum", 25),
    ("D0508 Bi/Ge sem.rum", 25),
    ("E0610 Seminarierum", 25),
    ("F0507 Ma-dt sem.rum", 25),
    ("F0606 seminarierum", 25),
    ("F0607 Ped sem rum", 25),
    ("F0724 Seminarierum", 25),
]

# Grupprum ~10–16 platser (vi använder 13)
ACADEMILL_GROUP_ROOMS: list[tuple[str, int]] = [
    ("B0215 Grupprum", 13),
]

# Mötesrum (liknande storlek som grupprum)
ACADEMILL_MEETING_ROOMS: list[tuple[str, int]] = [
    ("A0208 Mötesrum", 14),
    ("F0407 mötesrum", 14),
    ("F0412 mötesrum", 14),
    ("F0612 mötesrum", 14),
    ("ICT:s mötesrum", 14),
]

# Större salar (användbara vid Karriär – öppning m.m.)
ACADEMILL_LARGE_ROOMS: list[tuple[str, int]] = [
    ("C0302 Akademisalen", 120),
    ("C0201 Auditorium Bruhn", 80),
]


def seed_academill_rooms(db: Session) -> int:
    """Lägger till Academill-rum som saknas. Returnerar antal nya rum."""
    existing = {r.name for r in db.query(Room).all()}
    added = 0

    all_rooms = (
        ACADEMILL_SEMINAR_ROOMS
        + ACADEMILL_GROUP_ROOMS
        + ACADEMILL_MEETING_ROOMS
        + ACADEMILL_LARGE_ROOMS
    )

    for name, capacity in all_rooms:
        if name in existing:
            continue
        db.add(Room(name=name, capacity=capacity))
        existing.add(name)
        added += 1

    if added:
        db.commit()
    return added
