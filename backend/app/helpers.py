"""Shared logic for inspiratör-val vs faktiska tidspass."""

from app.models import Student

PASS2_TYPES = frozenset({"pass2a", "pass2b"})
MAX_SCHEDULE_PASSES_PER_INSPIRATOR = 3
REQUIRED_CHOICE_FIELDS = ("choice1", "choice2", "choice3")


def iter_required_choice_fields(student) -> list[tuple[str, str]]:
    """Val 1–3 i ordning; senare dubblett av samma inspiratör ersätts av reserv."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    reserve_substitute_used = False
    reserve = getattr(student, "reserve", None)

    for field_name in REQUIRED_CHOICE_FIELDS:
        val = getattr(student, field_name, None)
        if not val:
            continue
        if val in seen:
            if (
                not reserve_substitute_used
                and reserve
                and reserve not in seen
            ):
                out.append(("reserve", reserve))
                seen.add(reserve)
                reserve_substitute_used = True
            continue
        seen.add(val)
        out.append((field_name, val))
    return out


def student_required_choices_list(student) -> list[str]:
    """Unika obligatoriska val (dubbletter → reserv)."""
    return [insp for _, insp in iter_required_choice_fields(student)]


def student_choices(student: Student) -> set[str]:
    fields = (student.choice1, student.choice2, student.choice3, student.reserve)
    return {c for c in fields if c}


def student_required_choices(student: Student) -> set[str]:
    """Val 1–3 (reserv räknas inte som oplacerad i statistik/placering)."""
    return set(student_required_choices_list(student))


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


def schedule_pass_keys_from_types(pass_types: list[str]) -> set[str]:
    """Unika tidspass (pass1, pass2, pass3) från passtyper."""
    return {schedule_pass_key(pt) for pt in pass_types}


def would_exceed_inspirator_pass_limit(
    existing_keys: set[str], pass_type: str
) -> bool:
    """True om ett nytt tidspass skulle ge fler än tre pass för inspiratören."""
    key = schedule_pass_key(pass_type)
    if key in existing_keys:
        return False
    return len(existing_keys) >= MAX_SCHEDULE_PASSES_PER_INSPIRATOR


def can_add_inspirator_schedule_pass(
    existing_keys: set[str], pass_type: str
) -> bool:
    return not would_exceed_inspirator_pass_limit(existing_keys, pass_type)


def inspirator_pass2_variant_locked(pass_types: list[str]) -> str | None:
    """Vilket lunchspår (pass2a eller pass2b) inspiratören redan använder."""
    has_a = "pass2a" in pass_types
    has_b = "pass2b" in pass_types
    if has_a:
        return "pass2a"
    if has_b:
        return "pass2b"
    return None


def inspirator_has_pass_at_other_room(
    slots: list,
    inspiration: str,
    pass_type: str,
    room_id: int,
    *,
    inspiration_attr: str = "inspiration",
    pass_type_attr: str = "pass_type",
    room_id_attr: str = "room_id",
) -> bool:
    """True om inspiratören redan har detta pass i ett annat rum."""
    for slot in slots:
        if (
            getattr(slot, inspiration_attr) == inspiration
            and getattr(slot, pass_type_attr) == pass_type
            and getattr(slot, room_id_attr) != room_id
        ):
            return True
    return False


def would_conflict_inspirator_pass2(
    pass_types: list[str], pass_type: str
) -> bool:
    """Inspiratör får bara ligga på antingen 2a eller 2b, inte båda."""
    if pass_type not in PASS2_TYPES:
        return False
    locked = inspirator_pass2_variant_locked(pass_types)
    return locked is not None and locked != pass_type


def has_placement_at_pass(student: Student, pass_type: str) -> bool:
    key = schedule_pass_key(pass_type)
    for p in student.placements:
        slot = p.session_slot
        if slot and schedule_pass_key(slot.pass_type) == key:
            return True
    return False


def student_has_full_schedule(student: Student) -> bool:
    """True om eleven har pass 1, 2 och 3 (inget ledigt tidspass)."""
    return all(
        has_placement_at_pass(student, schedule_pass)
        for schedule_pass in ("pass1", "pass2", "pass3")
    )


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
