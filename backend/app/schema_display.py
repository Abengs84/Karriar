"""Visningslogik för schema-PDF (samma regler som SchemaTab i frontend)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.models import Room, SessionSlot

PASS2_BLOCKS = (
    {"variant": "2a", "pass_type": "pass2a", "time": "11:45–12:15"},
    {"variant": "2b", "pass_type": "pass2b", "time": "12:30–13:00"},
)

LUNCH_TIMES = {"2a": "12:15–13:00", "2b": "11:30–12:15"}


def is_booked(slot: SessionSlot | None) -> bool:
    return slot is not None and len(slot.placements) > 0


def placed_count(slot: SessionSlot | None) -> int:
    return len(slot.placements) if slot else 0


def slot_label(slot: SessionSlot, capacity: int) -> str:
    n = placed_count(slot)
    free = max(0, capacity - n)
    return f"{n} elever · {free} ledig(a) plats(er) kvar"


def pass2_label(variant: str, time: str) -> str:
    return f"Pass {variant.upper()} · {time}"


def _distance_to_lunch(anchor_min: int, track: Literal["2a", "2b"]) -> int:
    if track == "2a":
        lunch_start, lunch_end = 12 * 60 + 15, 13 * 60
    else:
        lunch_start, lunch_end = 11 * 60 + 30, 12 * 60 + 15
    if anchor_min < lunch_start:
        return lunch_start - anchor_min
    if anchor_min > lunch_end:
        return anchor_min - lunch_end
    return 0


def inspirator_lunch_track_from_pass2(slots: list[SessionSlot]) -> Literal["2a", "2b"] | None:
    pass2a = next((s for s in slots if s.pass_type == "pass2a"), None)
    pass2b = next((s for s in slots if s.pass_type == "pass2b"), None)
    if is_booked(pass2a):
        return "2a"
    if is_booked(pass2b):
        return "2b"
    if pass2a:
        return "2a"
    if pass2b:
        return "2b"
    return None


def suggested_lunch_track(slots: list[SessionSlot]) -> Literal["2a", "2b"] | None:
    from_pass2 = inspirator_lunch_track_from_pass2(slots)
    if from_pass2:
        return from_pass2

    booked = [s for s in slots if is_booked(s)]
    if not booked:
        return None

    anchors: list[int] = []
    for s in booked:
        if s.pass_type == "pass1":
            anchors.append(11 * 60 + 30)
        elif s.pass_type == "pass3":
            anchors.append(13 * 60 + 15)
    if not anchors:
        return None

    best: Literal["2a", "2b"] = "2b"
    best_dist = float("inf")
    for track in ("2a", "2b"):
        total = sum(_distance_to_lunch(a, track) for a in anchors)
        if total < best_dist:
            best_dist = total
            best = track
    return best


def pass2_blocks_for_display(slots: list[SessionSlot]) -> tuple[dict, ...]:
    pass2a = next((s for s in slots if s.pass_type == "pass2a"), None)
    pass2b = next((s for s in slots if s.pass_type == "pass2b"), None)
    a_booked = is_booked(pass2a)
    b_booked = is_booked(pass2b)

    if a_booked and b_booked:
        return PASS2_BLOCKS
    if a_booked:
        return tuple(b for b in PASS2_BLOCKS if b["variant"] == "2a")
    if b_booked:
        return tuple(b for b in PASS2_BLOCKS if b["variant"] == "2b")

    track = suggested_lunch_track(slots)
    if track == "2a":
        return tuple(b for b in PASS2_BLOCKS if b["variant"] == "2a")
    if track == "2b":
        return tuple(b for b in PASS2_BLOCKS if b["variant"] == "2b")
    return (PASS2_BLOCKS[0],)


def slot_map(slots: list[SessionSlot]) -> dict[tuple[int, str], SessionSlot]:
    return {(s.room_id, s.pass_type): s for s in slots}


def overview_rows(
    rooms: list[Room], slots: list[SessionSlot]
) -> list[tuple[Room, SessionSlot | None, SessionSlot | None, list[tuple[dict, SessionSlot]]]]:
    """Rum med minst ett bokat pass."""
    sm = slot_map(slots)
    rows: list[
        tuple[Room, SessionSlot | None, SessionSlot | None, list[tuple[dict, SessionSlot]]]
    ] = []
    for room in rooms:
        pass1 = sm.get((room.id, "pass1"))
        pass3 = sm.get((room.id, "pass3"))
        room_slots = [
            sm.get((room.id, pt))
            for pt in ("pass1", "pass2a", "pass2b", "pass3")
        ]
        room_slots = [s for s in room_slots if s is not None]
        pass2_booked: list[tuple[dict, SessionSlot]] = []
        for b in pass2_blocks_for_display(room_slots):
            slot = sm.get((room.id, b["pass_type"]))
            if is_booked(slot):
                pass2_booked.append((b, slot))
        has_any = is_booked(pass1) or is_booked(pass3) or len(pass2_booked) > 0
        if has_any:
            rows.append((room, pass1, pass3, pass2_booked))
    return rows


def rooms_with_bookings(
    rooms: list[Room], slots: list[SessionSlot]
) -> list[tuple[Room, list[SessionSlot]]]:
    by_room: dict[int, list[SessionSlot]] = {}
    for s in slots:
        by_room.setdefault(s.room_id, []).append(s)
    out: list[tuple[Room, list[SessionSlot]]] = []
    for room in rooms:
        room_slots = by_room.get(room.id, [])
        if any(is_booked(s) for s in room_slots):
            out.append((room, room_slots))
    return out


def inspirators_with_bookings(slots: list[SessionSlot]) -> list[tuple[str, list[SessionSlot]]]:
    by_insp: dict[str, list[SessionSlot]] = {}
    for s in slots:
        if not s.inspiration:
            continue
        by_insp.setdefault(s.inspiration, []).append(s)
    names = sorted(
        (name for name, lst in by_insp.items() if any(is_booked(s) for s in lst)),
        key=lambda n: n.casefold(),
    )
    return [(name, by_insp[name]) for name in names]


@dataclass(frozen=True)
class InspiratorScheduleRow:
    kind: Literal["pass", "lunch"]
    key: str
    label: str
    pass_type: str | None = None
    track: Literal["2a", "2b"] | None = None


def inspirator_schedule_rows(slots: list[SessionSlot]) -> list[InspiratorScheduleRow]:
    track = suggested_lunch_track(slots)
    pass2_blocks = pass2_blocks_for_display(slots)
    pass2_rows = [
        InspiratorScheduleRow(
            kind="pass",
            key=b["pass_type"],
            pass_type=b["pass_type"],
            label=pass2_label(b["variant"], b["time"]),
        )
        for b in pass2_blocks
    ]
    lunch_row = (
        InspiratorScheduleRow(
            kind="lunch",
            key="lunch",
            label=f"Lunch · {LUNCH_TIMES[track]}",
            track=track,
        )
        if track
        else None
    )

    rows: list[InspiratorScheduleRow] = [
        InspiratorScheduleRow(
            kind="pass",
            key="pass1",
            pass_type="pass1",
            label="Pass 1 · 11:00–11:30",
        )
    ]

    if track == "2b":
        if lunch_row:
            rows.append(lunch_row)
        for pass_type in ("pass2b", "pass2a"):
            row = next((r for r in pass2_rows if r.pass_type == pass_type), None)
            if row:
                rows.append(row)
    elif track == "2a":
        for pass_type in ("pass2a", "pass2b"):
            row = next((r for r in pass2_rows if r.pass_type == pass_type), None)
            if row:
                rows.append(row)
        if lunch_row:
            rows.append(lunch_row)
    else:
        rows.extend(pass2_rows)

    rows.append(
        InspiratorScheduleRow(
            kind="pass",
            key="pass3",
            pass_type="pass3",
            label="Pass 3 · 13:15–13:45",
        )
    )
    return rows
