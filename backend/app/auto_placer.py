"""
Heuristisk automatisk placering av elever på inspiratörspass.

Maximerar antal uppfyllda inspiratörsval (choice1–3 + reserv)
med så få krockar som möjligt inom hårda regler: ett pass
per tid, en gång per inspiratör, rumskapacitet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.helpers import schedule_pass_key

SchedulePass = Literal["pass1", "pass2", "pass3"]
PASS_ORDER: list[SchedulePass] = ["pass1", "pass2", "pass3"]
PASS2_VARIANTS = ("pass2a", "pass2b")

CHOICE_RANK = {
    "choice1": 1000,
    "choice2": 500,
    "choice3": 200,
    "reserve": 50,
}


@dataclass
class ChoiceRef:
    inspiration: str
    rank: int
    field: str


@dataclass
class RoomRef:
    id: int
    name: str
    capacity: int


@dataclass
class SlotRef:
    id: int | None
    room_id: int
    pass_type: str
    inspiration: str
    student_ids: list[int] = field(default_factory=list)
    capacity: int = 30

    @property
    def remaining(self) -> int:
        return max(0, self.capacity - len(self.student_ids))

    @property
    def key(self) -> tuple[int, str]:
        return (self.room_id, self.pass_type)


@dataclass
class StudentRef:
    id: int
    choice1: str | None
    choice2: str | None
    choice3: str | None
    reserve: str | None
    lunch_track: str | None
    # (pass_type, inspiration)
    placements: list[tuple[str, str]] = field(default_factory=list)

    def choices_ordered(self) -> list[ChoiceRef]:
        out: list[ChoiceRef] = []
        for field_name in ("choice1", "choice2", "choice3", "reserve"):
            val = getattr(self, field_name)
            if val:
                out.append(ChoiceRef(val, CHOICE_RANK[field_name], field_name))
        return out

    def has_pass(self, schedule_pass: SchedulePass) -> bool:
        key = "pass2" if schedule_pass == "pass2" else schedule_pass
        for pt, _ in self.placements:
            if schedule_pass_key(pt) == key:
                return True
        return False

    def has_inspirator(self, inspiration: str) -> bool:
        return any(insp == inspiration for _, insp in self.placements)

    def pass_type_for(self, schedule_pass: SchedulePass) -> str | None:
        key = "pass2" if schedule_pass == "pass2" else schedule_pass
        for pt, _ in self.placements:
            if schedule_pass_key(pt) == key:
                return pt
        return None


@dataclass
class UnplacedNeed:
    student_id: int
    inspiration: str
    rank: int
    field: str


@dataclass
class AutoSolveResult:
    placed_new: int
    slots_created: int
    unplaced_needs: list[UnplacedNeed]
    score: int
    by_choice_field: dict[str, int]
    summary: str


def _student_choices_list(s: StudentRef) -> list[ChoiceRef]:
    return s.choices_ordered()


def _load_student_from_orm(student) -> StudentRef:
    placements = []
    for p in student.placements:
        slot = p.session_slot
        if slot:
            placements.append((slot.pass_type, slot.inspiration))
    return StudentRef(
        id=student.id,
        choice1=student.choice1,
        choice2=student.choice2,
        choice3=student.choice3,
        reserve=student.reserve,
        lunch_track=student.lunch_track,
        placements=placements,
    )


def _load_slot_from_orm(slot) -> SlotRef:
    return SlotRef(
        id=slot.id,
        room_id=slot.room_id,
        pass_type=slot.pass_type,
        inspiration=slot.inspiration,
        student_ids=[p.student_id for p in slot.placements],
        capacity=slot.room.capacity,
    )


def _required_choices(s: StudentRef) -> list[ChoiceRef]:
    """Val 1–3 ska placeras om möjligt; reserv är frivillig."""
    return [c for c in _student_choices_list(s) if c.field != "reserve"]


def _pending_needs(students: list[StudentRef]) -> list[UnplacedNeed]:
    needs: list[UnplacedNeed] = []
    for s in students:
        for c in _required_choices(s):
            if not s.has_inspirator(c.inspiration):
                needs.append(
                    UnplacedNeed(s.id, c.inspiration, c.rank, c.field)
                )
    return needs


def _room_pass_occupant(slots: list[SlotRef]) -> dict[tuple[int, str], str]:
    occ: dict[tuple[int, str], str] = {}
    for slot in slots:
        occ[slot.key] = slot.inspiration
    return occ


def _find_slot_for(
    slots: list[SlotRef],
    rooms: list[RoomRef],
    inspiration: str,
    pass_type: str,
) -> SlotRef | None:
    candidates = [
        s
        for s in slots
        if s.inspiration == inspiration
        and s.pass_type == pass_type
        and s.remaining > 0
    ]
    if candidates:
        return max(candidates, key=lambda s: s.remaining)

    occ = _room_pass_occupant(slots)
    for room in sorted(rooms, key=lambda r: (-r.capacity, r.name)):
        key = (room.id, pass_type)
        if key in occ and occ[key] != inspiration:
            continue
        existing = next((s for s in slots if s.key == key), None)
        if existing:
            if existing.inspiration == inspiration and existing.remaining > 0:
                return existing
            continue
        new_slot = SlotRef(
            id=None,
            room_id=room.id,
            pass_type=pass_type,
            inspiration=inspiration,
            capacity=room.capacity,
        )
        slots.append(new_slot)
        occ[key] = inspiration
        return new_slot
    return None


def _prebalance_pass2_lunch(students: list[StudentRef], slots: list[SlotRef]) -> None:
    """Sätter lunch_track i förväg (~50/50) för elever som saknar pass 2."""
    count_2a, count_2b = _pass2_lunch_counts(students, slots)
    need = sorted(
        (s for s in students if not s.has_pass("pass2") and not s.lunch_track),
        key=lambda s: s.id,
    )
    for s in need:
        if count_2a <= count_2b:
            s.lunch_track = "2a"
            count_2a += 1
        else:
            s.lunch_track = "2b"
            count_2b += 1


def _pass2_lunch_counts(
    students: list[StudentRef],
    slots: list[SlotRef],
) -> tuple[int, int]:
    """Antal unika elever på pass 2a respektive 2b (lunchspår)."""
    ids_2a: set[int] = set()
    ids_2b: set[int] = set()
    for s in students:
        pt = s.pass_type_for("pass2")
        if pt == "pass2a":
            ids_2a.add(s.id)
        elif pt == "pass2b":
            ids_2b.add(s.id)
    for slot in slots:
        if slot.pass_type == "pass2a":
            ids_2a.update(slot.student_ids)
        elif slot.pass_type == "pass2b":
            ids_2b.update(slot.student_ids)
    return len(ids_2a), len(ids_2b)


def _pick_pass2_variant(
    slots: list[SlotRef],
    rooms: list[RoomRef],
    inspiration: str,
    student: StudentRef,
    students: list[StudentRef],
) -> str | None:
    if student.lunch_track == "2a":
        order: tuple[str, ...] = ("pass2a", "pass2b")
    elif student.lunch_track == "2b":
        order = ("pass2b", "pass2a")
    else:
        count_2a, count_2b = _pass2_lunch_counts(students, slots)
        # Fördela ~50/50 mellan lunch 2a och 2b när spåret inte är låst
        if count_2a <= count_2b:
            order = ("pass2a", "pass2b")
        else:
            order = ("pass2b", "pass2a")

    for variant in order:
        if _find_slot_for(slots, rooms, inspiration, variant):
            return variant
    return None


def _pick_pass_type(
    slots: list[SlotRef],
    rooms: list[RoomRef],
    inspiration: str,
    schedule_pass: SchedulePass,
    student: StudentRef,
    students: list[StudentRef],
) -> str | None:
    if schedule_pass == "pass2":
        return _pick_pass2_variant(slots, rooms, inspiration, student, students)
    return schedule_pass


def _can_assign(
    student: StudentRef,
    inspiration: str,
    pass_type: str,
) -> bool:
    if not student_chose_orm(student, inspiration):
        return False
    if student.has_inspirator(inspiration):
        return False
    if has_placement_at_pass_orm(student, pass_type):
        return False
    return True


def student_chose_orm(s: StudentRef, inspiration: str) -> bool:
    return any(c.inspiration == inspiration for c in _student_choices_list(s))


def has_placement_at_pass_orm(s: StudentRef, pass_type: str) -> bool:
    key = schedule_pass_key(pass_type)
    for pt, _ in s.placements:
        if schedule_pass_key(pt) == key:
            return True
    return False


def _assign(
    student: StudentRef,
    slot: SlotRef,
    pass_type: str,
) -> bool:
    if slot.remaining <= 0:
        return False
    if not _can_assign(student, slot.inspiration, pass_type):
        return False
    slot.student_ids.append(student.id)
    student.placements.append((pass_type, slot.inspiration))
    if pass_type in PASS2_VARIANTS:
        student.lunch_track = "2a" if pass_type == "pass2a" else "2b"
    return True


def _best_choice_for_pass(
    student: StudentRef,
    schedule_pass: SchedulePass,
    slots: list[SlotRef],
    rooms: list[RoomRef],
    students: list[StudentRef],
) -> tuple[ChoiceRef, str] | None:
    if student.has_pass(schedule_pass):
        return None

    candidates: list[tuple[ChoiceRef, str]] = []
    for choice in _required_choices(student):
        if student.has_inspirator(choice.inspiration):
            continue
        pass_type = _pick_pass_type(
            slots, rooms, choice.inspiration, schedule_pass, student, students
        )
        if not pass_type:
            continue
        if not _can_assign(student, choice.inspiration, pass_type):
            continue
        slot = _find_slot_for(slots, rooms, choice.inspiration, pass_type)
        if slot and slot.remaining > 0:
            candidates.append((choice, pass_type))

    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x[0].rank, x[0].inspiration))
    return candidates[0]


def _student_difficulty(student: StudentRef) -> tuple[int, int]:
    remaining = sum(
        1
        for c in _required_choices(student)
        if not student.has_inspirator(c.inspiration)
    )
    max_rank = max(
        (
            c.rank
            for c in _required_choices(student)
            if not student.has_inspirator(c.inspiration)
        ),
        default=0,
    )
    return (remaining, max_rank)


def solve_auto_placement(
    students: list[StudentRef],
    rooms: list[RoomRef],
    slots: list[SlotRef],
) -> AutoSolveResult:
    """Kör heuristiken. Muterar students/slots in-place."""
    if not rooms:
        return AutoSolveResult(
            placed_new=0,
            slots_created=0,
            unplaced_needs=_pending_needs(students),
            score=0,
            by_choice_field={},
            summary="Inga rum – skapa rum först.",
        )

    initial_placed = sum(len(s.placements) for s in students)
    initial_slot_count = len(slots)

    for schedule_pass in PASS_ORDER:
        if schedule_pass == "pass2":
            _prebalance_pass2_lunch(students, slots)
        ordered = sorted(students, key=_student_difficulty, reverse=True)
        for student in ordered:
            pick = _best_choice_for_pass(student, schedule_pass, slots, rooms, students)
            if not pick:
                continue
            choice, pass_type = pick
            slot = _find_slot_for(slots, rooms, choice.inspiration, pass_type)
            if slot:
                _assign(student, slot, pass_type)

    # Andra pass: försök fylla kvarvarande behov på vilken tid som helst
    for _ in range(3):
        improved = False
        needs = _pending_needs(students)
        needs.sort(key=lambda n: (-n.rank, n.inspiration))
        for need in needs:
            student = next(s for s in students if s.id == need.student_id)
            if student.has_inspirator(need.inspiration):
                continue
            for schedule_pass in PASS_ORDER:
                if student.has_pass(schedule_pass):
                    continue
                pass_type = _pick_pass_type(
                    slots, rooms, need.inspiration, schedule_pass, student, students
                )
                if not pass_type:
                    continue
                slot = _find_slot_for(slots, rooms, need.inspiration, pass_type)
                if slot and _assign(student, slot, pass_type):
                    improved = True
                    break
        if not improved:
            break

    final_placed = sum(len(s.placements) for s in students)
    placed_new = final_placed - initial_placed
    slots_created = len(slots) - initial_slot_count
    unplaced = _pending_needs(students)
    score = sum(
        c.rank
        for s in students
        for c in _student_choices_list(s)
        if s.has_inspirator(c.inspiration)
    )
    by_field: dict[str, int] = {f: 0 for f in CHOICE_RANK}
    for s in students:
        for _pt, insp in s.placements:
            for c in _student_choices_list(s):
                if c.inspiration == insp:
                    by_field[c.field] = by_field.get(c.field, 0) + 1
                    break

    unplaced_count = len(unplaced)
    if unplaced_count == 0:
        unplaced_part = "Alla val 1–3 har fått pass (reserv placeras inte automatiskt)."
    elif unplaced_count == 1:
        unplaced_part = "1 val (1–3) kvar utan pass."
    else:
        unplaced_part = f"{unplaced_count} val (1–3) kvar utan pass."
    summary = (
        f"Placerade {placed_new} nya pass "
        f"(totalt {final_placed} pass på {len(students)} elever). "
        f"{unplaced_part}"
    )

    return AutoSolveResult(
        placed_new=placed_new,
        slots_created=slots_created,
        unplaced_needs=unplaced,
        score=score,
        by_choice_field=by_field,
        summary=summary,
    )


def run_on_orm(
    students_orm, rooms_orm, slots_orm
) -> tuple[list[StudentRef], list[SlotRef], AutoSolveResult]:
    students = [_load_student_from_orm(s) for s in students_orm]
    rooms = [RoomRef(r.id, r.name, r.capacity) for r in rooms_orm]
    slots = [_load_slot_from_orm(s) for s in slots_orm]
    result = solve_auto_placement(students, rooms, slots)
    return students, slots, result


def apply_solution_to_db(db, students_orm, slots: list[SlotRef]) -> int:
    """Skriver nya slots och placeringar till databasen.

    Returnerar antal nya placeringar.
    """
    from app.models import Placement, SessionSlot

    student_by_id = {s.id: s for s in students_orm}
    existing_pairs: set[tuple[int, int]] = set()
    for s in students_orm:
        for p in s.placements:
            existing_pairs.add((p.student_id, p.session_slot_id))

    new_placements = 0
    slot_id_map: dict[tuple[int, str, str], int] = {}

    for slot in slots:
        db_slot = None
        if slot.id is not None:
            db_slot = db.query(SessionSlot).filter(SessionSlot.id == slot.id).first()
        else:
            db_slot = (
                db.query(SessionSlot)
                .filter(
                    SessionSlot.room_id == slot.room_id,
                    SessionSlot.pass_type == slot.pass_type,
                )
                .first()
            )
            if not db_slot:
                db_slot = SessionSlot(
                    room_id=slot.room_id,
                    pass_type=slot.pass_type,
                    inspiration=slot.inspiration,
                )
                db.add(db_slot)
                db.flush()
            slot.id = db_slot.id

        slot_id_map[(slot.room_id, slot.pass_type, slot.inspiration)] = db_slot.id

        for sid in slot.student_ids:
            key = (sid, db_slot.id)
            if key in existing_pairs:
                continue
            student = student_by_id.get(sid)
            if not student:
                continue
            db.add(Placement(student_id=sid, session_slot_id=db_slot.id))
            if slot.pass_type in PASS2_VARIANTS:
                student.lunch_track = "2a" if slot.pass_type == "pass2a" else "2b"
            existing_pairs.add(key)
            new_placements += 1

    return new_placements
