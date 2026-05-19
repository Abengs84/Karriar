"""
Heuristisk automatisk placering av elever på inspiratörspass.

Maximerar antal uppfyllda inspiratörsval (choice1–3 + reserv)
med så få krockar som möjligt inom hårda regler: ett pass
per tid, en gång per inspiratör, rumskapacitet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.helpers import (
    can_add_inspirator_schedule_pass,
    inspirator_pass2_variant_locked,
    iter_required_choice_fields,
    schedule_pass_key,
    schedule_pass_keys_from_types,
)

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
    suppressed_inspirators: list[str] = field(default_factory=list)


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


def _student_required_inspirations(s: StudentRef) -> set[str]:
    return {insp for _, insp in iter_required_choice_fields(s)}


def _base_required_choice_refs(s: StudentRef) -> list[ChoiceRef]:
    """Val 1–3; dublett ersätts av reserv."""
    return [
        ChoiceRef(insp, CHOICE_RANK[field], field)
        for field, insp in iter_required_choice_fields(s)
    ]


def _compute_suppressed(students: list[StudentRef], threshold: int) -> set[str]:
    if threshold <= 0:
        return set()
    counts: dict[str, int] = {}
    for s in students:
        for insp in _student_required_inspirations(s):
            counts[insp] = counts.get(insp, 0) + 1
    return {insp for insp, n in counts.items() if n <= threshold}


def _effective_required_choices(
    s: StudentRef, suppressed: set[str]
) -> list[ChoiceRef]:
    """Val 1–3 (efter dedup); undertröskel-inspiratörer ersätts av reserv (en gång per elev)."""
    out: list[ChoiceRef] = []
    reserve_used = False
    in_out: set[str] = set()
    for c in _base_required_choice_refs(s):
        if c.inspiration in suppressed:
            if (
                not reserve_used
                and s.reserve
                and s.reserve not in suppressed
                and s.reserve not in in_out
            ):
                out.append(ChoiceRef(s.reserve, CHOICE_RANK["reserve"], "reserve"))
                reserve_used = True
                in_out.add(s.reserve)
            continue
        out.append(c)
        in_out.add(c.inspiration)
    return out


def _required_choices(s: StudentRef, suppressed: set[str] | None = None) -> list[ChoiceRef]:
    if suppressed:
        return _effective_required_choices(s, suppressed)
    return _base_required_choice_refs(s)


def _student_has_full_schedule(s: StudentRef) -> bool:
    """True om eleven redan har pass 1, 2 och 3 (inget ledigt tidspass kvar)."""
    return all(s.has_pass(schedule_pass) for schedule_pass in PASS_ORDER)


def _pending_needs(
    students: list[StudentRef], suppressed: set[str] | None = None
) -> list[UnplacedNeed]:
    """Val 1–3 utan matchande placering och minst ett ledigt tidspass."""
    needs: list[UnplacedNeed] = []
    for s in students:
        if _student_has_full_schedule(s):
            continue
        for c in _required_choices(s, suppressed):
            if not s.has_inspirator(c.inspiration):
                needs.append(
                    UnplacedNeed(s.id, c.inspiration, c.rank, c.field)
                )
    return needs


def _inspirator_schedule_pass_keys(slots: list[SlotRef], inspiration: str) -> set[str]:
    return schedule_pass_keys_from_types(
        [s.pass_type for s in slots if s.inspiration == inspiration]
    )


def _room_pass_occupant(slots: list[SlotRef]) -> dict[tuple[int, str], str]:
    occ: dict[tuple[int, str], str] = {}
    for slot in slots:
        occ[slot.key] = slot.inspiration
    return occ


def _estimate_group_size(
    students: list[StudentRef] | None,
    inspiration: str,
    suppressed: set[str] | None = None,
) -> int:
    """Uppskattar hur många som fortfarande ska till samma inspiratör."""
    if not students:
        return 1
    pending = 0
    for s in students:
        if s.has_inspirator(inspiration):
            continue
        for c in _required_choices(s, suppressed):
            if c.inspiration == inspiration:
                pending += 1
                break
    return max(1, pending)


def _pick_existing_slot(
    candidates: list[SlotRef], *, minimize_sessions: bool
) -> SlotRef:
    if minimize_sessions:
        # Fyll befintliga sessioner innan en ny öppnas.
        return max(candidates, key=lambda s: (len(s.student_ids), -s.remaining))
    # Samla i befintlig session; vid paritet välj mindre rum.
    return max(candidates, key=lambda s: (len(s.student_ids), -s.capacity))


def _find_slot_for(
    slots: list[SlotRef],
    rooms: list[RoomRef],
    inspiration: str,
    pass_type: str,
    students: list[StudentRef] | None = None,
    *,
    minimize_sessions: bool = False,
    suppressed: set[str] | None = None,
) -> SlotRef | None:
    existing_for_insp = [
        s for s in slots if s.inspiration == inspiration and s.pass_type == pass_type
    ]
    if existing_for_insp:
        candidates = [s for s in existing_for_insp if s.remaining > 0]
        if candidates:
            return _pick_existing_slot(candidates, minimize_sessions=minimize_sessions)
        # Redan bokad denna tid – inget andra rum (fysiskt omöjligt).
        return None

    group_size = _estimate_group_size(students, inspiration, suppressed)
    occ = _room_pass_occupant(slots)
    if minimize_sessions:
        ordered = sorted(rooms, key=lambda r: (-r.capacity, r.name))
    else:
        ordered = sorted(rooms, key=lambda r: (r.capacity, r.name))
    insp_pass_keys = _inspirator_schedule_pass_keys(slots, inspiration)
    for min_capacity in (group_size, 1):
        for room in ordered:
            if room.capacity < min_capacity:
                continue
            key = (room.id, pass_type)
            if key in occ and occ[key] != inspiration:
                continue
            existing = next((s for s in slots if s.key == key), None)
            if existing:
                if existing.inspiration == inspiration and existing.remaining > 0:
                    return existing
                continue
            if not can_add_inspirator_schedule_pass(insp_pass_keys, pass_type):
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
            insp_pass_keys.add(schedule_pass_key(pass_type))
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


def _inspirator_pass2_variant_locked(
    slots: list[SlotRef], inspiration: str
) -> str | None:
    pass_types = [s.pass_type for s in slots if s.inspiration == inspiration]
    return inspirator_pass2_variant_locked(pass_types)


def _pick_pass2_variant(
    slots: list[SlotRef],
    rooms: list[RoomRef],
    inspiration: str,
    student: StudentRef,
    students: list[StudentRef],
    *,
    minimize_sessions: bool = False,
    suppressed: set[str] | None = None,
) -> str | None:
    locked = _inspirator_pass2_variant_locked(slots, inspiration)
    if locked:
        order = (locked,)
    elif student.lunch_track == "2a":
        order = ("pass2a", "pass2b")
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
        if _find_slot_for(
            slots, rooms, inspiration, variant, students,
            minimize_sessions=minimize_sessions,
            suppressed=suppressed,
        ):
            return variant
    return None


def _pick_pass_type(
    slots: list[SlotRef],
    rooms: list[RoomRef],
    inspiration: str,
    schedule_pass: SchedulePass,
    student: StudentRef,
    students: list[StudentRef],
    *,
    minimize_sessions: bool = False,
    suppressed: set[str] | None = None,
) -> str | None:
    if schedule_pass == "pass2":
        return _pick_pass2_variant(
            slots, rooms, inspiration, student, students,
            minimize_sessions=minimize_sessions,
            suppressed=suppressed,
        )
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
    *,
    minimize_sessions: bool = False,
    suppressed: set[str] | None = None,
) -> tuple[ChoiceRef, str] | None:
    if student.has_pass(schedule_pass):
        return None

    candidates: list[tuple[ChoiceRef, str]] = []
    for choice in _required_choices(student, suppressed):
        if student.has_inspirator(choice.inspiration):
            continue
        pass_type = _pick_pass_type(
            slots, rooms, choice.inspiration, schedule_pass, student, students,
            minimize_sessions=minimize_sessions,
            suppressed=suppressed,
        )
        if not pass_type:
            continue
        if not _can_assign(student, choice.inspiration, pass_type):
            continue
        slot = _find_slot_for(
            slots, rooms, choice.inspiration, pass_type, students,
            minimize_sessions=minimize_sessions,
            suppressed=suppressed,
        )
        if slot and slot.remaining > 0:
            candidates.append((choice, pass_type))

    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x[0].rank, x[0].inspiration))
    return candidates[0]


def _students_with_unplaced_required(
    students: list[StudentRef], suppressed: set[str] | None = None
) -> set[int]:
    return {n.student_id for n in _pending_needs(students, suppressed)}


def _snapshot_student_slots(
    student: StudentRef, slots: list[SlotRef]
) -> tuple[list[tuple[str, str]], str | None, dict[int, list[int]]]:
    affected: dict[int, list[int]] = {}
    for slot in slots:
        if student.id in slot.student_ids:
            affected[id(slot)] = list(slot.student_ids)
    return (list(student.placements), student.lunch_track, affected)


def _restore_student_slots(
    student: StudentRef,
    slots: list[SlotRef],
    snap: tuple[list[tuple[str, str]], str | None, dict[int, list[int]]],
) -> None:
    placements, lunch_track, affected = snap
    student.placements = placements
    student.lunch_track = lunch_track
    for slot in slots:
        sid = id(slot)
        if sid in affected:
            slot.student_ids = affected[sid]


def _inspiration_on_schedule_pass(
    student: StudentRef, schedule_pass: SchedulePass
) -> str | None:
    key = "pass2" if schedule_pass == "pass2" else schedule_pass
    for pt, insp in student.placements:
        if schedule_pass_key(pt) == key:
            return insp
    return None


def _unassign_at_schedule_pass(
    student: StudentRef, slots: list[SlotRef], schedule_pass: SchedulePass
) -> tuple[str, str] | None:
    key = "pass2" if schedule_pass == "pass2" else schedule_pass
    remove_idx: int | None = None
    removed_pt = ""
    removed_insp = ""
    for i, (pt, insp) in enumerate(student.placements):
        if schedule_pass_key(pt) == key:
            remove_idx = i
            removed_pt, removed_insp = pt, insp
            break
    if remove_idx is None:
        return None
    for slot in slots:
        if slot.pass_type == removed_pt and slot.inspiration == removed_insp:
            if student.id in slot.student_ids:
                slot.student_ids.remove(student.id)
                break
    del student.placements[remove_idx]
    if removed_pt in PASS2_VARIANTS and not student.has_pass("pass2"):
        student.lunch_track = None
    return removed_pt, removed_insp


def _try_place_reserve_on_schedule_pass(
    student: StudentRef,
    schedule_pass: SchedulePass,
    slots: list[SlotRef],
    rooms: list[RoomRef],
    students: list[StudentRef],
    *,
    suppressed: set[str],
    minimize_sessions: bool,
) -> bool:
    if not student.reserve or student.reserve in suppressed:
        return False
    if student.has_pass(schedule_pass) or student.has_inspirator(student.reserve):
        return False
    pass_type = _pick_pass_type(
        slots,
        rooms,
        student.reserve,
        schedule_pass,
        student,
        students,
        minimize_sessions=minimize_sessions,
        suppressed=suppressed,
    )
    if not pass_type or not _can_assign(student, student.reserve, pass_type):
        return False
    slot = _find_slot_for(
        slots,
        rooms,
        student.reserve,
        pass_type,
        students,
        minimize_sessions=minimize_sessions,
        suppressed=suppressed,
    )
    return bool(slot and _assign(student, slot, pass_type))


def _try_relocate_inspiration(
    student: StudentRef,
    inspiration: str,
    slots: list[SlotRef],
    rooms: list[RoomRef],
    students: list[StudentRef],
    *,
    source_pass: SchedulePass,
    suppressed: set[str],
    minimize_sessions: bool,
) -> bool:
    for target_pass in PASS_ORDER:
        if target_pass == source_pass or student.has_pass(target_pass):
            continue
        pass_type = _pick_pass_type(
            slots,
            rooms,
            inspiration,
            target_pass,
            student,
            students,
            minimize_sessions=minimize_sessions,
            suppressed=suppressed,
        )
        if not pass_type or not _can_assign(student, inspiration, pass_type):
            continue
        slot = _find_slot_for(
            slots,
            rooms,
            inspiration,
            pass_type,
            students,
            minimize_sessions=minimize_sessions,
            suppressed=suppressed,
        )
        if slot and _assign(student, slot, pass_type):
            return True
    return False


def _try_reserve_via_shuffle(
    student: StudentRef,
    slots: list[SlotRef],
    rooms: list[RoomRef],
    students: list[StudentRef],
    *,
    suppressed: set[str],
    minimize_sessions: bool,
) -> bool:
    """Flytta ett befintligt pass för att frigöra tid åt reserv."""
    occupied = [
        sp
        for sp in PASS_ORDER
        if student.has_pass(sp)
        and _inspiration_on_schedule_pass(student, sp) != student.reserve
    ]
    for source_pass in occupied:
        inspiration = _inspiration_on_schedule_pass(student, source_pass)
        if not inspiration:
            continue
        snap = _snapshot_student_slots(student, slots)
        if not _unassign_at_schedule_pass(student, slots, source_pass):
            continue
        if not _try_relocate_inspiration(
            student,
            inspiration,
            slots,
            rooms,
            students,
            source_pass=source_pass,
            suppressed=suppressed,
            minimize_sessions=minimize_sessions,
        ):
            _restore_student_slots(student, slots, snap)
            continue
        if _try_place_reserve_on_schedule_pass(
            student,
            source_pass,
            slots,
            rooms,
            students,
            suppressed=suppressed,
            minimize_sessions=minimize_sessions,
        ):
            return True
        _restore_student_slots(student, slots, snap)
    return False


def _try_reserve_for_unplaced(
    students: list[StudentRef],
    slots: list[SlotRef],
    rooms: list[RoomRef],
    *,
    suppressed: set[str],
    minimize_sessions: bool = False,
) -> set[int]:
    """Placera reserv för elever med kvarvarande val 1–3 (ledigt pass eller omflyttning)."""
    placed_ids: set[int] = set()
    need_ids = _students_with_unplaced_required(students, suppressed)

    for student in students:
        if student.id not in need_ids:
            continue
        if not student.reserve or student.reserve in suppressed:
            continue
        if student.has_inspirator(student.reserve):
            continue

        placed = False
        for schedule_pass in PASS_ORDER:
            if _try_place_reserve_on_schedule_pass(
                student,
                schedule_pass,
                slots,
                rooms,
                students,
                suppressed=suppressed,
                minimize_sessions=minimize_sessions,
            ):
                placed = True
                break

        if not placed:
            placed = _try_reserve_via_shuffle(
                student,
                slots,
                rooms,
                students,
                suppressed=suppressed,
                minimize_sessions=minimize_sessions,
            )

        if placed:
            placed_ids.add(student.id)

    return placed_ids


def _student_difficulty(
    student: StudentRef, suppressed: set[str] | None = None
) -> tuple[int, int]:
    remaining = sum(
        1
        for c in _required_choices(student, suppressed)
        if not student.has_inspirator(c.inspiration)
    )
    max_rank = max(
        (
            c.rank
            for c in _required_choices(student, suppressed)
            if not student.has_inspirator(c.inspiration)
        ),
        default=0,
    )
    return (remaining, max_rank)


def solve_auto_placement(
    students: list[StudentRef],
    rooms: list[RoomRef],
    slots: list[SlotRef],
    *,
    minimize_sessions_per_inspirator: bool = False,
    min_students_threshold: int = 0,
    try_reserve_for_unplaced: bool = False,
) -> AutoSolveResult:
    """Kör heuristiken. Muterar students/slots in-place."""
    suppressed = _compute_suppressed(students, min_students_threshold)
    suppressed_list = sorted(suppressed)

    if not rooms:
        return AutoSolveResult(
            placed_new=0,
            slots_created=0,
            unplaced_needs=_pending_needs(students, suppressed),
            score=0,
            by_choice_field={},
            summary="Inga rum – skapa rum först.",
            suppressed_inspirators=suppressed_list,
        )

    initial_placed = sum(len(s.placements) for s in students)
    initial_slot_count = len(slots)

    for schedule_pass in PASS_ORDER:
        if schedule_pass == "pass2":
            _prebalance_pass2_lunch(students, slots)
        ordered = sorted(
            students,
            key=lambda s: _student_difficulty(s, suppressed),
            reverse=True,
        )
        for student in ordered:
            pick = _best_choice_for_pass(
                student, schedule_pass, slots, rooms, students,
                minimize_sessions=minimize_sessions_per_inspirator,
                suppressed=suppressed,
            )
            if not pick:
                continue
            choice, pass_type = pick
            slot = _find_slot_for(
                slots, rooms, choice.inspiration, pass_type, students,
                minimize_sessions=minimize_sessions_per_inspirator,
                suppressed=suppressed,
            )
            if slot:
                _assign(student, slot, pass_type)

    # Andra pass: försök fylla kvarvarande behov på vilken tid som helst
    for _ in range(3):
        improved = False
        needs = _pending_needs(students, suppressed)
        needs.sort(key=lambda n: (-n.rank, n.inspiration))
        for need in needs:
            student = next(s for s in students if s.id == need.student_id)
            if student.has_inspirator(need.inspiration):
                continue
            for schedule_pass in PASS_ORDER:
                if student.has_pass(schedule_pass):
                    continue
                pass_type = _pick_pass_type(
                    slots, rooms, need.inspiration, schedule_pass, student, students,
                    minimize_sessions=minimize_sessions_per_inspirator,
                    suppressed=suppressed,
                )
                if not pass_type:
                    continue
                slot = _find_slot_for(
                    slots, rooms, need.inspiration, pass_type, students,
                    minimize_sessions=minimize_sessions_per_inspirator,
                    suppressed=suppressed,
                )
                if slot and _assign(student, slot, pass_type):
                    improved = True
                    break
        if not improved:
            break

    reserve_fallback_ids: set[int] = set()
    if try_reserve_for_unplaced:
        reserve_fallback_ids = _try_reserve_for_unplaced(
            students,
            slots,
            rooms,
            suppressed=suppressed,
            minimize_sessions=minimize_sessions_per_inspirator,
        )

    # Ta bort tomma celler som skapats under sökning men aldrig fylldes.
    slots[:] = [s for s in slots if len(s.student_ids) > 0]

    final_placed = sum(len(s.placements) for s in students)
    placed_new = final_placed - initial_placed
    slots_created = len(slots) - initial_slot_count
    unplaced = _pending_needs(students, suppressed)
    if reserve_fallback_ids:
        unplaced = [n for n in unplaced if n.student_id not in reserve_fallback_ids]
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
    reserve_count = len(reserve_fallback_ids)
    if unplaced_count == 0:
        if reserve_count:
            unplaced_part = (
                f"Alla val 1–3 har pass eller reserv ({reserve_count} på reserv)."
            )
        elif try_reserve_for_unplaced:
            unplaced_part = "Alla val 1–3 har fått pass."
        else:
            unplaced_part = "Alla val 1–3 har fått pass (reserv placeras inte automatiskt)."
    elif unplaced_count == 1:
        unplaced_part = "1 val (1–3) kvar utan tidspass."
    else:
        unplaced_part = f"{unplaced_count} val (1–3) kvar utan tidspass."
    if reserve_count and unplaced_count > 0:
        if reserve_count == 1:
            unplaced_part += " 1 elev fick reserv på ledigt pass."
        else:
            unplaced_part += f" {reserve_count} elever fick reserv på ledigt pass."
    summary = (
        f"{placed_new} val placerade "
        f"(totalt {final_placed} pass på {len(students)} elever). "
        f"{unplaced_part}"
    )
    if suppressed_list:
        summary += (
            f" {len(suppressed_list)} inspiratör(er) under tröskel – elever dirigeras till reserv."
        )

    return AutoSolveResult(
        placed_new=placed_new,
        slots_created=slots_created,
        unplaced_needs=unplaced,
        score=score,
        by_choice_field=by_field,
        summary=summary,
        suppressed_inspirators=suppressed_list,
    )


def run_on_orm(
    students_orm,
    rooms_orm,
    slots_orm,
    *,
    minimize_sessions_per_inspirator: bool = False,
    min_students_threshold: int = 0,
    try_reserve_for_unplaced: bool = False,
) -> tuple[list[StudentRef], list[SlotRef], AutoSolveResult]:
    students = [_load_student_from_orm(s) for s in students_orm]
    rooms = [RoomRef(r.id, r.name, r.capacity) for r in rooms_orm]
    slots = [_load_slot_from_orm(s) for s in slots_orm]
    result = solve_auto_placement(
        students, rooms, slots,
        minimize_sessions_per_inspirator=minimize_sessions_per_inspirator,
        min_students_threshold=min_students_threshold,
        try_reserve_for_unplaced=try_reserve_for_unplaced,
    )
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
        if len(slot.student_ids) == 0:
            continue
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
