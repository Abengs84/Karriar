"""Shared logic for inspiratör-val vs faktiska tidspass."""

from app.models import Student

PASS2_TYPES = frozenset({"pass2a", "pass2b"})


def student_choices(student: Student) -> set[str]:
    fields = (student.choice1, student.choice2, student.choice3, student.reserve)
    return {c for c in fields if c}


def student_chose(student: Student, inspiration: str) -> bool:
    return inspiration in student_choices(student)


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
