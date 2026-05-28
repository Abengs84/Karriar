"""Shared logic for inspiratör-val vs faktiska tidspass."""

import re

from sqlalchemy.orm import joinedload

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename_part(text: str) -> str:
    """Gör en sträng säker som del av ett nedladdningsfilnamn (behåller åäö)."""
    s = _INVALID_FILENAME_CHARS.sub("_", text.strip())
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"_+", "_", s).strip("._")
    return s or "okand"


PLACEMENT_PDF_PREFIX = "Karriär – Placering"


def placement_pdf_filename(kind: str, school: str | None = None) -> str:
    """Filnamn för placering-PDF. kind: Schema, Rum, Inspiratör eller Skola."""
    if kind == "Skola" and school:
        school_part = _INVALID_FILENAME_CHARS.sub(" - ", school.strip())
        school_part = re.sub(r"\s+", " ", school_part)
        return f"{PLACEMENT_PDF_PREFIX} - Skola - {school_part}.pdf"
    return f"{PLACEMENT_PDF_PREFIX} - {kind}.pdf"


def content_disposition_attachment(filename: str) -> str:
    """Content-Disposition med UTF-8-filnamn (RFC 5987)."""
    from urllib.parse import quote

    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace("?", "_")
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )

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


def effective_required_choices_list(
    student: Student, suppressed: set[str]
) -> list[str]:
    """Val 1–3; undertröskel-inspiratörer ersätts av reserv (en gång per elev)."""
    out: list[str] = []
    reserve_used = False
    in_out: set[str] = set()
    for insp in student_required_choices_list(student):
        if insp in suppressed:
            reserve = student.reserve
            if (
                not reserve_used
                and reserve
                and reserve not in suppressed
                and reserve not in in_out
            ):
                out.append(reserve)
                reserve_used = True
                in_out.add(reserve)
            continue
        out.append(insp)
        in_out.add(insp)
    return out


def student_chose_for_placement(
    student: Student,
    inspiration: str,
    *,
    suppressed: set[str] | None = None,
) -> bool:
    """Samma logik som oplacerade grupper i frontend (val 1–3 + tröskel/reserv)."""
    if suppressed:
        return inspiration in effective_required_choices_list(student, suppressed)
    return student_chose_required(student, inspiration)


def is_placed_with_inspirator(student: Student, inspiration: str) -> bool:
    for p in student.placements:
        slot = p.session_slot
        if slot and slot.inspiration == inspiration:
            return True
    return False


def is_unplaced_for_inspirator(
    student: Student,
    inspiration: str,
    *,
    suppressed: set[str] | None = None,
) -> bool:
    """Samma logik som oplacerade grupper i Placering-fliken."""
    if not student_chose_for_placement(student, inspiration, suppressed=suppressed):
        return False
    if is_placed_with_inspirator(student, inspiration):
        return False
    if student_has_full_schedule(student):
        return False
    return True


def collect_effective_inspirations(
    students: list[Student], suppressed: set[str]
) -> list[str]:
    result: set[str] = set()
    for student in students:
        for insp in effective_required_choices_list(student, suppressed):
            result.add(insp)
    return sorted(result)


def unique_unplaced_student_ids(
    students: list[Student], min_students_threshold: int = 0
) -> set[int]:
    """Unika elever som syns i oplacerade grupper (samma som Placering-vyn)."""
    suppressed = suppressed_inspirations(students, min_students_threshold)
    ids: set[int] = set()
    for inspiration in collect_effective_inspirations(students, suppressed):
        for student in students:
            if is_unplaced_for_inspirator(
                student, inspiration, suppressed=suppressed
            ):
                ids.add(student.id)
    return ids


def count_unique_unplaced_students(
    students: list[Student], min_students_threshold: int = 0
) -> int:
    return len(unique_unplaced_student_ids(students, min_students_threshold))


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


def purge_invalid_placements(db) -> int:
    """Tar bort placeringar där eleven inte valt inspiratören (val 1–3 eller reserv)."""
    from app.models import Placement

    rows = (
        db.query(Placement)
        .options(
            joinedload(Placement.student),
            joinedload(Placement.session_slot),
        )
        .all()
    )
    removed = 0
    for placement in rows:
        slot = placement.session_slot
        student = placement.student
        if not slot or not student:
            continue
        if not student_chose(student, slot.inspiration):
            db.delete(placement)
            removed += 1
    if removed:
        db.flush()
    return removed


def purge_orphan_placements(db) -> int:
    """Tar bort placeringar vars session_slot saknas (undviker spökoplacerade)."""
    from app.models import Placement, SessionSlot

    valid_slot_ids = {row[0] for row in db.query(SessionSlot.id).all()}
    removed = 0
    for placement in db.query(Placement).all():
        if placement.session_slot_id not in valid_slot_ids:
            db.delete(placement)
            removed += 1
    if removed:
        db.flush()
    return removed


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
