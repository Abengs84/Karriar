"""Shared logic for inspiratör-val vs faktiska tidspass."""

from app.models import Student

PASS2_TYPES = frozenset({"pass2a", "pass2b"})


def student_choices(student: Student) -> set[str]:
    fields = (student.choice1, student.choice2, student.choice3, student.reserve)
    return {c for c in fields if c}


def student_required_choices(student: Student) -> set[str]:
    """Val 1–3 (reserv räknas inte som oplacerad i statistik/placering)."""
    fields = (student.choice1, student.choice2, student.choice3)
    return {c for c in fields if c}


def student_chose(student: Student, inspiration: str) -> bool:
    return inspiration in student_choices(student)


def student_chose_required(student: Student, inspiration: str) -> bool:
    return inspiration in student_required_choices(student)


def is_placed_with_inspirator(student: Student, inspiration: str) -> bool:
    for p in student.placements:
        slot = p.session_slot
        if slot and slot.inspiration == inspiration:
            return True
    return False


def schedule_pass_key(pass_type: str) -> str:
    """pass2a och pass2b räknas som samma tidspass."""
    if pass_type in PASS2_TYPES:
        return "pass2"
    return pass_type


def has_placement_at_pass(student: Student, pass_type: str) -> bool:
    key = schedule_pass_key(pass_type)
    for p in student.placements:
        slot = p.session_slot
        if slot and schedule_pass_key(slot.pass_type) == key:
            return True
    return False


def get_slot_for_pass(student: Student, pass_type: str):
    """Hämta session för ett tidspass (pass1, pass2, pass3)."""
    key = schedule_pass_key(pass_type)
    for p in student.placements:
        slot = p.session_slot
        if slot and schedule_pass_key(slot.pass_type) == key:
            return slot
    return None


def collect_all_inspirations(students: list[Student]) -> set[str]:
    result: set[str] = set()
    for s in students:
        result.update(student_choices(s))
    return result


def count_required_inspiration_choices(students: list[Student]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in students:
        for insp in student_required_choices(s):
            counts[insp] = counts.get(insp, 0) + 1
    return counts


def purge_empty_session_slots(db) -> int:
    """Tar bort schemaceller utan elever (kvarlämnade av auto-placering m.m.)."""
    from app.models import Placement, SessionSlot

    empty_ids = [
        row[0]
        for row in db.query(SessionSlot.id)
        .outerjoin(Placement, Placement.session_slot_id == SessionSlot.id)
        .filter(Placement.id.is_(None))
        .all()
    ]
    if not empty_ids:
        return 0
    db.query(SessionSlot).filter(SessionSlot.id.in_(empty_ids)).delete(
        synchronize_session=False
    )
    db.flush()
    return len(empty_ids)


def suppressed_inspirations(students: list[Student], threshold: int) -> set[str]:
    """Inspiratörer med ≤ threshold elever (val 1–3). 0 = av."""
    if threshold <= 0:
        return set()
    counts = count_required_inspiration_choices(students)
    return {insp for insp, n in counts.items() if n <= threshold}
