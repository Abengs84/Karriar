"""Föreslå och verkställ omfördelning av pass 2a/2b för jämnare lunchspår."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session, joinedload

from app.models import SessionSlot, Student

PASS2_TYPES = frozenset({"pass2a", "pass2b"})
TEMP_ROOM_OFFSET = 1_000_000


@dataclass
class Pass2SlotState:
    id: int
    room_id: int
    room_name: str
    pass_type: str
    inspiration: str
    student_count: int
    student_ids: list[int] = field(default_factory=list)


@dataclass
class LunchMove:
    kind: str  # flip | swap
    session_slot_id: int
    session_slot_id_b: int | None
    inspiration: str
    inspiration_b: str | None
    room_id: int
    room_name: str
    from_track: str
    to_track: str
    student_count: int
    student_count_b: int
    net_delta: int


@dataclass
class LunchRebalanceResult:
    lunch_2a_before: int
    lunch_2b_before: int
    lunch_2a_after: int
    lunch_2b_after: int
    moves: list[LunchMove]
    summary: str
    blocked_reason: str | None = None


def _track(pass_type: str) -> str:
    return "2a" if pass_type == "pass2a" else "2b"


def _pass_type(track: str) -> str:
    return "pass2a" if track == "2a" else "pass2b"


def _count_tracks(slots: list[Pass2SlotState]) -> tuple[int, int, int]:
    ids_2a: set[int] = set()
    ids_2b: set[int] = set()
    for slot in slots:
        if slot.pass_type == "pass2a":
            ids_2a.update(slot.student_ids)
        else:
            ids_2b.update(slot.student_ids)
    n2a, n2b = len(ids_2a), len(ids_2b)
    return n2a, n2b, n2a - n2b


def _load_pass2_slots(db: Session) -> list[Pass2SlotState]:
    rows = (
        db.query(SessionSlot)
        .options(
            joinedload(SessionSlot.room),
            joinedload(SessionSlot.placements),
        )
        .filter(SessionSlot.pass_type.in_(PASS2_TYPES))
        .all()
    )
    out: list[Pass2SlotState] = []
    for slot in rows:
        student_ids = [p.student_id for p in slot.placements]
        if not student_ids:
            continue
        out.append(
            Pass2SlotState(
                id=slot.id,
                room_id=slot.room_id,
                room_name=slot.room.name if slot.room else f"rum {slot.room_id}",
                pass_type=slot.pass_type,
                inspiration=slot.inspiration,
                student_count=len(student_ids),
                student_ids=student_ids,
            )
        )
    return out


def _flip_delta(from_track: str, n: int) -> int:
    """Ändring av (count_2a - count_2b) vid flytt av n elever."""
    return -2 * n if from_track == "2a" else 2 * n


def _swap_delta(n_a: int, n_b: int) -> int:
    return 2 * (n_b - n_a)


def _room_pass_types(
    all_pass2: list[SessionSlot],
    pass_type_by_id: dict[int, str],
) -> dict[int, dict[str, int | None]]:
    """room_id -> pass2a/2b -> slot_id eller None."""
    rooms: dict[int, dict[str, int | None]] = {}
    for slot in all_pass2:
        pt = pass_type_by_id.get(slot.id, slot.pass_type)
        if slot.room_id not in rooms:
            rooms[slot.room_id] = {"pass2a": None, "pass2b": None}
        rooms[slot.room_id][pt] = slot.id
    return rooms


def _find_flip_candidates(
    slots: list[Pass2SlotState],
    rooms: dict[int, dict[str, int | None]],
    used: set[int],
) -> list[tuple[Pass2SlotState, str, int]]:
    by_id = {s.id: s for s in slots}
    out: list[tuple[Pass2SlotState, str, int]] = []
    for slot in slots:
        if slot.id in used:
            continue
        other_type = "pass2b" if slot.pass_type == "pass2a" else "pass2a"
        other_id = rooms.get(slot.room_id, {}).get(other_type)
        if other_id is not None:
            other = by_id.get(other_id)
            if other is not None and other.student_count > 0:
                continue
        target = other_type
        delta = _flip_delta(_track(slot.pass_type), slot.student_count)
        out.append((slot, target, delta))
    return out


def _find_swap_candidates(
    slots: list[Pass2SlotState],
    rooms: dict[int, dict[str, int | None]],
    used: set[int],
) -> list[tuple[Pass2SlotState, Pass2SlotState, int]]:
    by_id = {s.id: s for s in slots}
    out: list[tuple[Pass2SlotState, Pass2SlotState, int]] = []
    seen: set[tuple[int, int]] = set()
    for room_id, sides in rooms.items():
        id_a, id_b = sides.get("pass2a"), sides.get("pass2b")
        if id_a is None or id_b is None:
            continue
        if id_a in used or id_b in used:
            continue
        a, b = by_id.get(id_a), by_id.get(id_b)
        if not a or not b:
            continue
        pair = tuple(sorted((id_a, id_b)))
        if pair in seen:
            continue
        seen.add(pair)
        delta = _swap_delta(a.student_count, b.student_count)
        out.append((a, b, delta))
    return out


def plan_lunch_rebalance(db: Session, *, tolerance: int = 1) -> LunchRebalanceResult:
    slots = _load_pass2_slots(db)
    all_pass2_rows = (
        db.query(SessionSlot)
        .options(joinedload(SessionSlot.placements))
        .filter(SessionSlot.pass_type.in_(PASS2_TYPES))
        .all()
    )

    n2a_before, n2b_before, diff = _count_tracks(slots)
    if not slots:
        return LunchRebalanceResult(
            lunch_2a_before=n2a_before,
            lunch_2b_before=n2b_before,
            lunch_2a_after=n2a_before,
            lunch_2b_after=n2b_before,
            moves=[],
            summary="Inga pass 2-sessioner med elever att omfördela.",
        )

    planned: list[LunchMove] = []
    used: set[int] = set()
    working = [
        Pass2SlotState(
            id=s.id,
            room_id=s.room_id,
            room_name=s.room_name,
            pass_type=s.pass_type,
            inspiration=s.inspiration,
            student_count=s.student_count,
            student_ids=list(s.student_ids),
        )
        for s in slots
    ]
    pass_type_by_id = {s.id: s.pass_type for s in working}

    while abs(diff) > tolerance:
        _, _, diff = _count_tracks(working)
        rooms = _room_pass_types(all_pass2_rows, pass_type_by_id)
        best: tuple[int, LunchMove, Pass2SlotState, Pass2SlotState | None, str | None] | None = (
            None
        )

        for slot, target, delta in _find_flip_candidates(working, rooms, used):
            new_diff = diff + delta
            score = abs(new_diff)
            if score >= abs(diff):
                continue
            move = LunchMove(
                kind="flip",
                session_slot_id=slot.id,
                session_slot_id_b=None,
                inspiration=slot.inspiration,
                inspiration_b=None,
                room_id=slot.room_id,
                room_name=slot.room_name,
                from_track=_track(slot.pass_type),
                to_track=_track(target),
                student_count=slot.student_count,
                student_count_b=0,
                net_delta=delta,
            )
            if best is None or score < best[0]:
                best = (score, move, slot, None, target)

        for a, b, delta in _find_swap_candidates(working, rooms, used):
            new_diff = diff + delta
            score = abs(new_diff)
            if score >= abs(diff):
                continue
            move = LunchMove(
                kind="swap",
                session_slot_id=a.id,
                session_slot_id_b=b.id,
                inspiration=a.inspiration,
                inspiration_b=b.inspiration,
                room_id=a.room_id,
                room_name=a.room_name,
                from_track="2a",
                to_track="2b",
                student_count=a.student_count,
                student_count_b=b.student_count,
                net_delta=delta,
            )
            if best is None or score < best[0]:
                best = (score, move, a, b, None)

        if best is None:
            break

        _, move, slot_a, slot_b, target = best
        planned.append(move)
        used.add(move.session_slot_id)
        if move.session_slot_id_b is not None:
            used.add(move.session_slot_id_b)

        if move.kind == "flip":
            ws = next(s for s in working if s.id == slot_a.id)
            pass_type_by_id[ws.id] = target  # type: ignore[arg-type]
            ws.pass_type = target  # type: ignore[assignment]
        else:
            wa = next(s for s in working if s.id == slot_a.id)
            wb = next(s for s in working if s.id == slot_b.id)  # type: ignore[union-attr]
            pass_type_by_id[wa.id] = "pass2b"
            pass_type_by_id[wb.id] = "pass2a"
            wa.pass_type, wb.pass_type = "pass2b", "pass2a"

        _, _, diff = _count_tracks(working)

    n2a_after, n2b_after, _ = _count_tracks(working)
    if not planned:
        blocked = (
            "Ingen förbättring möjlig med befintliga rum (båda pass 2-rutorna upptagna "
            "eller ingen flytt minskar obalansen)."
        )
        summary = (
            f"Lunchspår oförändrat: {n2a_before} på 2a, {n2b_before} på 2b. {blocked}"
        )
        return LunchRebalanceResult(
            lunch_2a_before=n2a_before,
            lunch_2b_before=n2b_before,
            lunch_2a_after=n2a_after,
            lunch_2b_after=n2b_after,
            moves=[],
            summary=summary,
            blocked_reason=blocked,
        )

    summary = (
        f"Föreslår {len(planned)} flytt(ar): lunch 2a {n2a_before} → {n2a_after}, "
        f"2b {n2b_before} → {n2b_after}."
    )
    return LunchRebalanceResult(
        lunch_2a_before=n2a_before,
        lunch_2b_before=n2b_before,
        lunch_2a_after=n2a_after,
        lunch_2b_after=n2b_after,
        moves=planned,
        summary=summary,
    )


def _update_lunch_tracks(db: Session, student_ids: list[int], track: str) -> None:
    if not student_ids:
        return
    db.query(Student).filter(Student.id.in_(student_ids)).update(
        {Student.lunch_track: track},
        synchronize_session=False,
    )


def _apply_flip(db: Session, slot_id: int, target_pass: str) -> None:
    slot = (
        db.query(SessionSlot)
        .options(joinedload(SessionSlot.placements), joinedload(SessionSlot.room))
        .filter(SessionSlot.id == slot_id)
        .first()
    )
    if not slot:
        raise ValueError(f"Session {slot_id} hittades inte")
    if slot.pass_type == target_pass:
        return
    # Kolla om mål-rutan redan är upptagen av en annan session (t.ex. tom reserverad cell).
    blocking = (
        db.query(SessionSlot)
        .filter(
            SessionSlot.room_id == slot.room_id,
            SessionSlot.pass_type == target_pass,
            SessionSlot.id != slot.id,
        )
        .first()
    )
    if blocking is not None and len(blocking.placements) == 0:
        db.delete(blocking)
        db.flush()
    elif blocking is not None:
        room_label = slot.room.name if slot.room else f"rum {slot.room_id}"
        raise ValueError(
            f"{room_label} har redan {target_pass} med «{blocking.inspiration}»"
        )

    student_ids = [p.student_id for p in slot.placements]
    slot.pass_type = target_pass
    _update_lunch_tracks(db, student_ids, _track(target_pass))


def _apply_swap(db: Session, slot_a_id: int, slot_b_id: int) -> None:
    slot_a = (
        db.query(SessionSlot)
        .options(joinedload(SessionSlot.placements))
        .filter(SessionSlot.id == slot_a_id)
        .first()
    )
    slot_b = (
        db.query(SessionSlot)
        .options(joinedload(SessionSlot.placements))
        .filter(SessionSlot.id == slot_b_id)
        .first()
    )
    if not slot_a or not slot_b:
        raise ValueError("Session för byte hittades inte")
    if slot_a.room_id != slot_b.room_id:
        raise ValueError("Byte kräver samma rum")
    if slot_a.pass_type != "pass2a" or slot_b.pass_type != "pass2b":
        raise ValueError("Byte kräver pass2a och pass2b i samma rum")

    room_id = slot_a.room_id
    temp_room = TEMP_ROOM_OFFSET + room_id
    slot_a.room_id = temp_room
    db.flush()
    slot_b.pass_type = "pass2a"
    slot_a.pass_type = "pass2b"
    slot_a.room_id = room_id
    db.flush()

    _update_lunch_tracks(db, [p.student_id for p in slot_a.placements], "2b")
    _update_lunch_tracks(db, [p.student_id for p in slot_b.placements], "2a")


def apply_lunch_rebalance(db: Session, moves: list[LunchMove]) -> None:
    for move in moves:
        if move.kind == "flip":
            _apply_flip(db, move.session_slot_id, _pass_type(move.to_track))
        elif move.kind == "swap":
            if move.session_slot_id_b is None:
                raise ValueError("swap saknar andra session")
            _apply_swap(db, move.session_slot_id, move.session_slot_id_b)
    db.commit()
