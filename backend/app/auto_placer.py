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
    student_chose_required,
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
    placement_pass_keys: set[str] = field(init=False, default_factory=set)
    placement_inspirations: set[str] = field(init=False, default_factory=set)
    pass_type_by_schedule_key: dict[str, str] = field(
        init=False, default_factory=dict
    )
    _choices_ordered_cache: list[ChoiceRef] = field(init=False, default_factory=list)
    _required_choices_cache: list[ChoiceRef] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self._choices_ordered_cache = []
        for field_name in ("choice1", "choice2", "choice3", "reserve"):
            val = getattr(self, field_name)
            if val:
                self._choices_ordered_cache.append(
                    ChoiceRef(val, CHOICE_RANK[field_name], field_name)
                )
        self._required_choices_cache = [
            ChoiceRef(insp, CHOICE_RANK[field], field)
            for field, insp in iter_required_choice_fields(self)
        ]
        _rebuild_student_placement_indexes(self)

    def choices_ordered(self) -> list[ChoiceRef]:
        return self._choices_ordered_cache

    def has_pass(self, schedule_pass: SchedulePass) -> bool:
        key = "pass2" if schedule_pass == "pass2" else schedule_pass
        return key in self.placement_pass_keys

    def has_inspirator(self, inspiration: str) -> bool:
        return inspiration in self.placement_inspirations

    def pass_type_for(self, schedule_pass: SchedulePass) -> str | None:
        key = "pass2" if schedule_pass == "pass2" else schedule_pass
        return self.pass_type_by_schedule_key.get(key)


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
    missing_pass_count: int
    unplaced_student_count: int
    score: int
    by_choice_field: dict[str, int]
    summary: str
    suppressed_inspirators: list[str] = field(default_factory=list)
    lunch_2a: int = 0
    lunch_2b: int = 0
    rooms_relocated: int = 0
    reserve_placed_count: int = 0
    pass2_room_share_count: int = 0


def _rebuild_student_placement_indexes(student: StudentRef) -> None:
    student.placement_pass_keys = set()
    student.placement_inspirations = set()
    student.pass_type_by_schedule_key = {}
    for pass_type, inspiration in student.placements:
        key = schedule_pass_key(pass_type)
        student.placement_pass_keys.add(key)
        student.placement_inspirations.add(inspiration)
        student.pass_type_by_schedule_key[key] = pass_type


def _student_choices_list(s: StudentRef) -> list[ChoiceRef]:
    return s.choices_ordered()


def _choice_field_by_inspiration(s: StudentRef) -> dict[str, tuple[str, int]]:
    lookup: dict[str, tuple[str, int]] = {}
    for choice in _student_choices_list(s):
        # Första förekomst (högst rank) ska vinna vid dubletter.
        if choice.inspiration not in lookup:
            lookup[choice.inspiration] = (choice.field, choice.rank)
    return lookup


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
    return s._required_choices_cache


def _compute_suppressed(students: list[StudentRef], threshold: int) -> set[str]:
    if threshold <= 0:
        return set()
    counts: dict[str, int] = {}
    for s in students:
        for insp in _student_required_inspirations(s):
            counts[insp] = counts.get(insp, 0) + 1
    return {insp for insp, n in counts.items() if n <= threshold}


def _inspirator_demand_counts(
    students: list[StudentRef],
    suppressed: set[str] | None = None,
    *,
    include_reserve: bool = False,
) -> dict[str, int]:
    """Antal elever som valt inspiratören (val 1–3, högst en gång per elev; + reserv vid behov)."""
    sup = suppressed or set()
    counts: dict[str, int] = {}
    for s in students:
        seen: set[str] = set()
        for choice_field in ("choice1", "choice2", "choice3"):
            insp = getattr(s, choice_field)
            if insp and insp not in sup and insp not in seen:
                counts[insp] = counts.get(insp, 0) + 1
                seen.add(insp)
        if (
            include_reserve
            and s.reserve
            and s.reserve not in sup
            and s.reserve not in seen
        ):
            counts[s.reserve] = counts.get(s.reserve, 0) + 1
    return counts


def locks_by_demand(
    rooms: list[RoomRef],
    demand_counts: dict[str, int],
    *,
    max_locks: int | None = None,
) -> dict[str, int]:
    """Tilldelar största lediga rummet till inspiratörer med flest val (högst max_locks)."""
    limit = len(rooms) if max_locks is None else min(max_locks, len(rooms))
    rooms_sorted = sorted(rooms, key=lambda r: (-r.capacity, r.name))
    used_rooms: set[int] = set()
    locks: dict[str, int] = {}
    ranked = sorted(demand_counts.items(), key=lambda x: (-x[1], x[0]))
    for inspiration, demand in ranked:
        if len(locks) >= limit:
            break
        if demand <= 0:
            continue
        chosen: int | None = None
        for room in rooms_sorted:
            if room.id in used_rooms:
                continue
            if room.capacity >= demand:
                chosen = room.id
                break
        if chosen is None:
            for room in rooms_sorted:
                if room.id not in used_rooms:
                    chosen = room.id
                    break
        if chosen is not None:
            locks[inspiration] = chosen
            used_rooms.add(chosen)
    return locks


def _exclusive_for_inspiration(
    inspiration: str,
    *,
    exclusive_one_inspirator_per_room: bool,
    exclusive_inspirators: set[str] | None = None,
) -> bool:
    """Exklusivt rum gäller alla inspiratörer, eller bara de i exclusive_inspirators."""
    if exclusive_inspirators is not None:
        return inspiration in exclusive_inspirators
    return exclusive_one_inspirator_per_room


def compute_room_policy(
    rooms: list[RoomRef],
    demand_counts: dict[str, int],
    *,
    same_room_exclusive: bool,
    hybrid_when_short: bool,
) -> tuple[dict[str, int], bool, set[str] | None, int]:
    """Rumslås och exklusivitet vid «ett rum per inspiratör».

    Returnerar (room_locks, exclusive_all, exclusive_only, n_shared_inspirators).
    hybrid: topp len(rooms) inspiratörer får eget rum; övriga delar rum (ej exklusivt).
    """
    if not same_room_exclusive:
        return {}, False, None, 0

    ranked = sorted(
        ((insp, n) for insp, n in demand_counts.items() if n > 0),
        key=lambda x: (-x[1], x[0]),
    )
    n_rooms = len(rooms)
    n_insp = len(ranked)

    if hybrid_when_short and n_insp > n_rooms:
        top = dict(ranked[:n_rooms])
        locks = locks_by_demand(rooms, top, max_locks=n_rooms)
        exclusive_only = set(locks.keys())
        n_shared = max(0, n_insp - len(exclusive_only))
        return locks, False, exclusive_only, n_shared

    locks = locks_by_demand(rooms, demand_counts, max_locks=n_rooms)
    if hybrid_when_short:
        return locks, False, set(locks.keys()), 0
    return locks, True, None, max(0, n_insp - len(locks))


def _displace_low_demand_from_locked_rooms(
    slots: list[SlotRef],
    rooms: list[RoomRef],
    room_locks: dict[str, int],
    demand_counts: dict[str, int],
    *,
    low_demand_ceiling: int = 0,
) -> int:
    """Flyttar bort låg-efterfrågade inspiratörer från rum reserverade för populära."""
    if not room_locks:
        return 0

    priority = set(room_locks.keys())
    owners = _room_owners_from_slots(slots)
    occ = _room_pass_occupant(slots)
    moved = 0

    for holder, locked_rid in room_locks.items():
        holder_demand = demand_counts.get(holder, 0)
        owner = owners.get(locked_rid)
        if owner is None or owner == holder:
            continue
        owner_demand = demand_counts.get(owner, 0)
        if owner in priority and owner_demand >= holder_demand:
            continue
        should_displace = owner_demand < holder_demand or (
            low_demand_ceiling > 0 and owner_demand <= low_demand_ceiling
        )
        if not should_displace:
            continue
        for slot in list(slots):
            if slot.room_id != locked_rid or slot.inspiration != owner:
                continue
            n = len(slot.student_ids)
            if n == 0:
                continue
            candidates = sorted(
                [r for r in rooms if r.capacity >= n and r.id != locked_rid],
                key=lambda r: (r.capacity, r.name),
            )
            for room in candidates:
                key = (room.id, slot.pass_type)
                occupant = occ.get(key)
                if occupant is not None and occupant != owner:
                    continue
                lock_holder = next(
                    (insp for insp, rid in room_locks.items() if rid == room.id),
                    None,
                )
                if (
                    lock_holder
                    and lock_holder != owner
                    and demand_counts.get(lock_holder, 0) > owner_demand
                ):
                    continue
                old_key = slot.key
                if occ.get(old_key) == owner:
                    del occ[old_key]
                slot.room_id = room.id
                slot.capacity = room.capacity
                occ[slot.key] = owner
                moved += 1
                break
    return moved


def _relocate_slots_to_locked_rooms(
    slots: list[SlotRef],
    rooms: list[RoomRef],
    room_locks: dict[str, int],
) -> int:
    """Flyttar befintliga sessioner till låst rum om passtypen är ledig där."""
    if not room_locks:
        return 0
    room_map = {r.id: r for r in rooms}
    occ = _room_pass_occupant(slots)
    moved = 0
    for slot in slots:
        target_rid = room_locks.get(slot.inspiration)
        if target_rid is None or slot.room_id == target_rid:
            continue
        room = room_map.get(target_rid)
        if not room:
            continue
        key = (target_rid, slot.pass_type)
        owner = occ.get(key)
        if owner is not None and owner != slot.inspiration:
            continue
        old_key = slot.key
        if old_key in occ:
            del occ[old_key]
        slot.room_id = target_rid
        slot.capacity = room.capacity
        occ[key] = slot.inspiration
        moved += 1
    return moved


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


def _missing_schedule_pass_count(student: StudentRef) -> int:
    return sum(1 for p in PASS_ORDER if not student.has_pass(p))


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


def _room_owners_from_slots(slots: list[SlotRef]) -> dict[int, str]:
    """Vilken inspiratör som äger rummet (flest elever över alla pass i rummet)."""
    weight: dict[int, dict[str, int]] = {}
    for slot in slots:
        n = len(slot.student_ids)
        if n == 0:
            continue
        weight.setdefault(slot.room_id, {})
        by_insp = weight[slot.room_id]
        by_insp[slot.inspiration] = by_insp.get(slot.inspiration, 0) + n
    return {
        rid: max(counts, key=counts.get) for rid, counts in weight.items()
    }


def _room_usable_for_inspiration(
    room_id: int,
    inspiration: str,
    slots: list[SlotRef],
    *,
    exclusive_room: bool,
    owners_by_room: dict[int, str] | None = None,
    room_locks: dict[str, int] | None = None,
) -> bool:
    """Med exklusivt rum: bara ägaren (eller tomt rum) får använda rummet."""
    if room_locks:
        for holder, locked_rid in room_locks.items():
            if locked_rid == room_id and holder != inspiration:
                return False
    if not exclusive_room:
        return True
    owners = owners_by_room if owners_by_room is not None else _room_owners_from_slots(slots)
    owner = owners.get(room_id)
    return owner is None or owner == inspiration


def _seed_locked_inspirator_sessions(
    slots: list[SlotRef],
    rooms: list[RoomRef],
    room_locks: dict[str, int],
    *,
    inspirator_pass2_targets: dict[str, str] | None = None,
    demand_counts: dict[str, int] | None = None,
) -> int:
    """Öppnar pass 1/2/3 i låsta rum först – populära inspiratörer blockeras inte av små grupper."""
    room_map = {r.id: r for r in rooms}
    occ = _room_pass_occupant(slots)
    created = 0
    ranked = sorted(
        room_locks.keys(),
        key=lambda i: (-(demand_counts or {}).get(i, 0), i),
    )
    for inspiration in ranked:
        rid = room_locks[inspiration]
        room = room_map.get(rid)
        if not room:
            continue
        locked_p2 = _inspirator_pass2_variant_locked(slots, inspiration)
        if locked_p2:
            pass2_type = locked_p2
        elif inspirator_pass2_targets and inspiration in inspirator_pass2_targets:
            pass2_type = inspirator_pass2_targets[inspiration]
        else:
            pass2_type = "pass2a"
        for pass_type in ("pass1", pass2_type, "pass3"):
            key = (rid, pass_type)
            if key in occ:
                continue
            if not can_add_inspirator_schedule_pass(
                _inspirator_schedule_pass_keys(slots, inspiration), pass_type
            ):
                continue
            slots.append(
                SlotRef(
                    id=None,
                    room_id=rid,
                    pass_type=pass_type,
                    inspiration=inspiration,
                    capacity=room.capacity,
                )
            )
            occ[key] = inspiration
            created += 1
    return created


def _ensure_sessions_for_high_demand(
    slots: list[SlotRef],
    rooms: list[RoomRef],
    demand_counts: dict[str, int],
    students: list[StudentRef],
    *,
    suppressed: set[str] | None = None,
    inspirator_pass2_targets: dict[str, str] | None = None,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    min_demand: int = 8,
) -> int:
    """Skapar minst en session för populära inspiratörer som annars får 0 pass."""
    created = 0
    for inspiration, demand in sorted(
        demand_counts.items(), key=lambda x: (-x[1], x[0])
    ):
        if demand < min_demand:
            break
        if any(s.inspiration == inspiration for s in slots):
            continue
        probe = next(
            (
                s
                for s in students
                if any(
                    c.inspiration == inspiration
                    for c in _required_choices(s, suppressed)
                )
            ),
            None,
        )
        if probe is None:
            continue
        for schedule_pass in PASS_ORDER:
            pass_type = _pick_pass_type(
                slots,
                rooms,
                inspiration,
                schedule_pass,
                probe,
                students,
                suppressed=suppressed,
                inspirator_pass2_targets=inspirator_pass2_targets,
                room_locks=room_locks,
                exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                exclusive_inspirators=exclusive_inspirators,
            )
            if not pass_type:
                if schedule_pass == "pass2":
                    pass_type = (
                        inspirator_pass2_targets.get(inspiration, "pass2a")
                        if inspirator_pass2_targets
                        else "pass2a"
                    )
                else:
                    pass_type = schedule_pass
            slot = _find_slot_for(
                slots,
                rooms,
                inspiration,
                pass_type,
                students,
                suppressed=suppressed,
                room_locks=room_locks,
                exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                exclusive_inspirators=exclusive_inspirators,
                demand_counts=demand_counts,
            )
            if slot:
                created += 1
                break
    return created


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
    return max(candidates, key=lambda s: (len(s.student_ids), -s.remaining))


def _inspirator_preferred_room_id(
    slots: list[SlotRef],
    inspiration: str,
    room_locks: dict[str, int] | None = None,
) -> int | None:
    """Låst rum, annars rum där inspiratören redan har flest pass."""
    if room_locks and inspiration in room_locks:
        return room_locks[inspiration]
    weight: dict[int, int] = {}
    for s in slots:
        if s.inspiration == inspiration:
            weight[s.room_id] = weight.get(s.room_id, 0) + max(1, len(s.student_ids))
    if not weight:
        return None
    return max(weight, key=lambda rid: weight[rid])


def _ordered_rooms_for_inspiration(
    rooms: list[RoomRef],
    inspiration: str,
    slots: list[SlotRef],
    group_size: int,
    *,
    minimize_sessions: bool,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
) -> list[RoomRef]:
    """Rum att prova vid ny session; strikt låst rum om det finns i room_locks."""
    exclusive = _exclusive_for_inspiration(
        inspiration,
        exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
        exclusive_inspirators=exclusive_inspirators,
    )
    owners_by_room = _room_owners_from_slots(slots) if exclusive else None
    locked_id = room_locks.get(inspiration) if room_locks else None
    if locked_id is not None:
        locked_rooms = [
            r
            for r in rooms
            if r.id == locked_id
            and _room_usable_for_inspiration(
                r.id,
                inspiration,
                slots,
                exclusive_room=exclusive,
                owners_by_room=owners_by_room,
                room_locks=room_locks,
            )
        ]
        if not locked_rooms:
            return []
        return _rooms_ordered_for_new_session(
            locked_rooms,
            group_size,
            minimize_sessions=minimize_sessions,
            preferred_room_id=locked_id,
        )
    preferred = _inspirator_preferred_room_id(slots, inspiration, room_locks)
    if demand_counts and locked_id is None:
        demand_pref = _preferred_room_for_demand(
            inspiration,
            demand_counts,
            rooms,
            slots,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            room_locks=room_locks,
        )
        if demand_pref is not None:
            preferred = demand_pref
    pool = [
        r
        for r in rooms
        if _room_usable_for_inspiration(
            r.id,
            inspiration,
            slots,
            exclusive_room=exclusive,
            owners_by_room=owners_by_room,
            room_locks=room_locks,
        )
    ]
    eff_group = group_size
    if demand_counts:
        eff_group = max(group_size, demand_counts.get(inspiration, 0))
    return _rooms_ordered_for_new_session(
        pool,
        eff_group,
        minimize_sessions=minimize_sessions,
        preferred_room_id=preferred,
    )


def _preferred_room_for_demand(
    inspiration: str,
    demand_counts: dict[str, int],
    rooms: list[RoomRef],
    slots: list[SlotRef],
    *,
    exclusive_one_inspirator_per_room: bool,
    exclusive_inspirators: set[str] | None = None,
    room_locks: dict[str, int] | None = None,
) -> int | None:
    """Största lediga rummet för populära inspiratörer (mjuk prioritering utan lås)."""
    demand = demand_counts.get(inspiration, 0)
    if demand < 8:
        return None
    exclusive = _exclusive_for_inspiration(
        inspiration,
        exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
        exclusive_inspirators=exclusive_inspirators,
    )
    owners_by_room = _room_owners_from_slots(slots) if exclusive else None
    pool = [
        r
        for r in rooms
        if _room_usable_for_inspiration(
            r.id,
            inspiration,
            slots,
            exclusive_room=exclusive,
            owners_by_room=owners_by_room,
            room_locks=room_locks,
        )
    ]
    if not pool:
        return None
    fitting = [r for r in pool if r.capacity >= demand]
    pick_from = fitting if fitting else pool
    return max(pick_from, key=lambda r: r.capacity).id


def _rooms_ordered_for_new_session(
    rooms: list[RoomRef],
    group_size: int,
    *,
    minimize_sessions: bool,
    preferred_room_id: int | None = None,
) -> list[RoomRef]:
    """Större rum först om gruppen är stor; annars minska parallella sessioner."""
    def sort_key(r: RoomRef) -> tuple:
        pref = 0 if preferred_room_id is not None and r.id == preferred_room_id else 1
        if minimize_sessions or group_size >= 8:
            return (pref, -r.capacity, r.name)
        return (pref, r.capacity, r.name)

    return sorted(rooms, key=sort_key)


def _try_move_session_to_larger_room(
    slot: SlotRef,
    slots: list[SlotRef],
    rooms: list[RoomRef],
    *,
    extra_needed: int,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
) -> bool:
    """Flyttar eller byter rum så sessionen får plats för fler elever."""
    if room_locks and slot.inspiration in room_locks:
        return False
    if extra_needed <= 0 or slot.remaining >= extra_needed:
        return False
    room_map = {r.id: r for r in rooms}
    need_capacity = len(slot.student_ids) + extra_needed
    current = room_map.get(slot.room_id)
    if current and current.capacity >= need_capacity:
        return False

    exclusive = _exclusive_for_inspiration(
        slot.inspiration,
        exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
        exclusive_inspirators=exclusive_inspirators,
    )
    owners_by_room = _room_owners_from_slots(slots) if exclusive else None
    candidates = [
        r
        for r in rooms
        if r.id != slot.room_id
        and r.capacity >= need_capacity
        and _room_usable_for_inspiration(
            r.id,
            slot.inspiration,
            slots,
            exclusive_room=exclusive,
            owners_by_room=owners_by_room,
            room_locks=room_locks,
        )
    ]
    candidates.sort(
        key=lambda r: (
            0
            if _inspirator_preferred_room_id(slots, slot.inspiration, room_locks) == r.id
            else 1,
            -r.capacity,
            r.name,
        )
    )
    occ = _room_pass_occupant(slots)
    pass_type = slot.pass_type

    for room in candidates:
        key = (room.id, pass_type)
        occupant = occ.get(key)
        if occupant is None:
            slot.room_id = room.id
            slot.capacity = room.capacity
            return True
        if occupant == slot.inspiration:
            continue
        other_slot = next(
            (s for s in slots if s.key == key and s.inspiration == occupant),
            None,
        )
        if not other_slot or not current:
            continue
        if len(other_slot.student_ids) <= current.capacity:
            old_rid = slot.room_id
            slot.room_id = room.id
            slot.capacity = room.capacity
            other_slot.room_id = old_rid
            other_slot.capacity = current.capacity
            return True
    return False


def _find_slot_for(
    slots: list[SlotRef],
    rooms: list[RoomRef],
    inspiration: str,
    pass_type: str,
    students: list[StudentRef] | None = None,
    *,
    minimize_sessions: bool = False,
    suppressed: set[str] | None = None,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
) -> SlotRef | None:
    existing_for_insp = [
        s for s in slots if s.inspiration == inspiration and s.pass_type == pass_type
    ]
    if existing_for_insp:
        candidates = [s for s in existing_for_insp if s.remaining > 0]
        if candidates:
            return _pick_existing_slot(candidates, minimize_sessions=minimize_sessions)
        pending = _estimate_group_size(students, inspiration, suppressed)
        for slot in existing_for_insp:
            if _try_move_session_to_larger_room(
                slot,
                slots,
                rooms,
                extra_needed=max(1, pending),
                room_locks=room_locks,
                exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                exclusive_inspirators=exclusive_inspirators,
                demand_counts=demand_counts,
            ):
                candidates = [s for s in existing_for_insp if s.remaining > 0]
                if candidates:
                    return _pick_existing_slot(
                        candidates, minimize_sessions=minimize_sessions
                    )
        return None

    exclusive = _exclusive_for_inspiration(
        inspiration,
        exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
        exclusive_inspirators=exclusive_inspirators,
    )
    group_size = _estimate_group_size(students, inspiration, suppressed)
    if demand_counts:
        group_size = max(group_size, demand_counts.get(inspiration, 0))
    occ = _room_pass_occupant(slots)
    slot_by_key = {s.key: s for s in slots}
    owners_by_room = _room_owners_from_slots(slots) if exclusive else None
    ordered = _ordered_rooms_for_inspiration(
        rooms,
        inspiration,
        slots,
        group_size,
        minimize_sessions=minimize_sessions,
        room_locks=room_locks,
        exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
        exclusive_inspirators=exclusive_inspirators,
        demand_counts=demand_counts,
    )
    insp_pass_keys = _inspirator_schedule_pass_keys(slots, inspiration)
    for min_capacity in (group_size, 1):
        for room in ordered:
            if room.capacity < min_capacity:
                continue
            if not _room_usable_for_inspiration(
                room.id,
                inspiration,
                slots,
                exclusive_room=exclusive,
                owners_by_room=owners_by_room,
                room_locks=room_locks,
            ):
                continue
            key = (room.id, pass_type)
            if key in occ and occ[key] != inspiration:
                continue
            existing = slot_by_key.get(key)
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
            slot_by_key[key] = new_slot
            insp_pass_keys.add(schedule_pass_key(pass_type))
            return new_slot
    return None


def _plan_inspirator_pass2_variants(
    students: list[StudentRef],
    slots: list[SlotRef],
    suppressed: set[str] | None,
) -> dict[str, str]:
    """Fördelar olåsta inspiratörer till pass2a/2b utifrån förväntad elevefterfrågan."""
    load_2a, load_2b = _pass2_lunch_counts(students, slots)
    demand: dict[str, int] = {}

    for s in students:
        if s.has_pass("pass2"):
            continue
        unplaced = [
            c
            for c in _required_choices(s, suppressed)
            if not s.has_inspirator(c.inspiration)
        ]
        if not unplaced:
            continue
        unplaced.sort(key=lambda c: (-c.rank, c.inspiration))
        insp = unplaced[0].inspiration
        demand[insp] = demand.get(insp, 0) + 1

    targets: dict[str, str] = {}
    for insp, count in sorted(demand.items(), key=lambda x: (-x[1], x[0])):
        if _inspirator_pass2_variant_locked(slots, insp):
            continue
        # Välj sida som minskar obalansen mest (inte bara vilken som är lägst just nu).
        skew_if_a = abs((load_2a + count) - load_2b)
        skew_if_b = abs(load_2a - (load_2b + count))
        if skew_if_a <= skew_if_b:
            targets[insp] = "pass2a"
            load_2a += count
        else:
            targets[insp] = "pass2b"
            load_2b += count
    return targets


def _prebalance_pass2_lunch(
    students: list[StudentRef],
    slots: list[SlotRef],
    suppressed: set[str] | None = None,
) -> None:
    """Sätter lunch_track i förväg för elever som saknar pass 2 (utan inspiratörsplan).

    Används bara när balansera lunchspår är av. Med balansering styrs pass 2a/2b
    per inspiratör via inspirator_pass2_targets – förplanerat lunch_track utifrån
    elevens högsta val gav ofta fel spår och sämre fördelning.
    """
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
    inspirator_pass2_targets: dict[str, str] | None = None,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
) -> str | None:
    locked = _inspirator_pass2_variant_locked(slots, inspiration)
    if locked:
        order = (locked,)
    elif inspirator_pass2_targets and inspiration in inspirator_pass2_targets:
        preferred = inspirator_pass2_targets[inspiration]
        other = "pass2b" if preferred == "pass2a" else "pass2a"
        order = (preferred, other)
    elif student.lunch_track == "2a":
        order = ("pass2a", "pass2b")
    elif student.lunch_track == "2b":
        order = ("pass2b", "pass2a")
    else:
        count_2a, count_2b = _pass2_lunch_counts(students, slots)
        if count_2a <= count_2b:
            order = ("pass2a", "pass2b")
        else:
            order = ("pass2b", "pass2a")

    for variant in order:
        if _find_slot_for(
            slots, rooms, inspiration, variant, students,
            minimize_sessions=minimize_sessions,
            suppressed=suppressed,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
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
    inspirator_pass2_targets: dict[str, str] | None = None,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
) -> str | None:
    if schedule_pass == "pass2":
        return _pick_pass2_variant(
            slots, rooms, inspiration, student, students,
            minimize_sessions=minimize_sessions,
            suppressed=suppressed,
            inspirator_pass2_targets=inspirator_pass2_targets,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
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
    pass_key = schedule_pass_key(pass_type)
    student.placement_pass_keys.add(pass_key)
    student.placement_inspirations.add(slot.inspiration)
    student.pass_type_by_schedule_key[pass_key] = pass_type
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
    inspirator_pass2_targets: dict[str, str] | None = None,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
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
            inspirator_pass2_targets=inspirator_pass2_targets,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
        )
        if not pass_type:
            continue
        if not _can_assign(student, choice.inspiration, pass_type):
            continue
        slot = _find_slot_for(
            slots, rooms, choice.inspiration, pass_type, students,
            minimize_sessions=minimize_sessions,
            suppressed=suppressed,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
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


def _students_missing_schedule_pass(students: list[StudentRef]) -> list[StudentRef]:
    return [s for s in students if not _student_has_full_schedule(s)]


def _is_unplaced_for_inspirator_ref(
    student: StudentRef,
    inspiration: str,
    suppressed: set[str] | None = None,
) -> bool:
    """Samma logik som oplacerade grupper i Placering (helpers.is_unplaced_for_inspirator)."""
    sup = suppressed or set()
    if not any(c.inspiration == inspiration for c in _required_choices(student, sup)):
        return False
    if student.has_inspirator(inspiration):
        return False
    if _student_has_full_schedule(student):
        return False
    return True


def count_unique_unplaced_students_ref(
    students: list[StudentRef], suppressed: set[str] | None = None
) -> int:
    """Unika elever som syns i oplacerade grupper – samma som Placering-fliken."""
    sup = suppressed or set()
    ids: set[int] = set()
    inspirations: set[str] = set()
    for s in students:
        for c in _required_choices(s, sup):
            inspirations.add(c.inspiration)
    for inspiration in inspirations:
        for s in students:
            if _is_unplaced_for_inspirator_ref(s, inspiration, sup):
                ids.add(s.id)
    return len(ids)


def count_students_needing_placement_attention(
    students: list[StudentRef], suppressed: set[str] | None = None
) -> int:
    """Alias – använd count_unique_unplaced_students_ref (samma som Placering-vyn)."""
    return count_unique_unplaced_students_ref(students, suppressed)


def _collect_pass2_complement_room_opportunities(
    slots: list[SlotRef],
) -> list[tuple[int, str]]:
    """Rum där ett pass-2-spår är upptaget och det andra (2a/2b) är ledigt."""
    occ = _room_pass_occupant(slots)
    seen: set[tuple[int, str]] = set()
    opportunities: list[tuple[int, str]] = []
    for slot in slots:
        if slot.pass_type not in PASS2_VARIANTS:
            continue
        complement = "pass2b" if slot.pass_type == "pass2a" else "pass2a"
        key = (slot.room_id, complement)
        if key in seen or key in occ:
            continue
        seen.add(key)
        opportunities.append(key)
    return opportunities


def _pending_count_for_inspiration(
    students: list[StudentRef],
    inspiration: str,
    suppressed: set[str] | None,
) -> int:
    n = 0
    for s in students:
        if s.has_inspirator(inspiration):
            continue
        for c in _required_choices(s, suppressed):
            if c.inspiration == inspiration:
                n += 1
                break
    return n


def _try_place_unplaced_in_pass2_room_share(
    students: list[StudentRef],
    slots: list[SlotRef],
    rooms: list[RoomRef],
    *,
    suppressed: set[str] | None = None,
) -> int:
    """Placerar oplacerade inspiratörer i pass 2 genom att dela rum (2a/2b).

    Om ett rum redan har pass 2a bokat öppnas pass 2b för en oplacerad grupp
    (och tvärtom). Gäller även rum som annars är låsta till en annan inspiratör.
    """
    room_map = {r.id: r for r in rooms}
    opportunities = _collect_pass2_complement_room_opportunities(slots)
    if not opportunities:
        return 0

    inspirations: set[str] = set()
    for need in _pending_needs(students, suppressed):
        inspirations.add(need.inspiration)

    ranked = sorted(
        inspirations,
        key=lambda i: (-_pending_count_for_inspiration(students, i, suppressed), i),
    )
    placed = 0
    occ = _room_pass_occupant(slots)

    for inspiration in ranked:
        pending = _pending_count_for_inspiration(students, inspiration, suppressed)
        if pending <= 0:
            continue
        locked_p2 = _inspirator_pass2_variant_locked(slots, inspiration)
        insp_keys = _inspirator_schedule_pass_keys(slots, inspiration)

        existing_p2 = [
            s
            for s in slots
            if s.inspiration == inspiration and s.pass_type in PASS2_VARIANTS
        ]
        slot: SlotRef | None = None
        if existing_p2:
            slot = next((s for s in existing_p2 if s.remaining > 0), None)
        if not slot:
            candidates: list[tuple[int, str, int]] = []
            for room_id, pass_type in opportunities:
                if (room_id, pass_type) in occ:
                    continue
                if locked_p2 and locked_p2 != pass_type:
                    continue
                if not can_add_inspirator_schedule_pass(insp_keys, pass_type):
                    continue
                room = room_map.get(room_id)
                if not room or room.capacity < 1:
                    continue
                candidates.append((room.capacity, room_id, pass_type))
            if not candidates:
                continue
            candidates.sort(
                key=lambda x: (
                    0 if x[0] >= pending else 1,
                    x[0] if x[0] >= pending else -x[0],
                    x[1],
                    x[2],
                )
            )
            _, room_id, pass_type = candidates[0]
            room = room_map[room_id]
            slot = SlotRef(
                id=None,
                room_id=room_id,
                pass_type=pass_type,
                inspiration=inspiration,
                capacity=room.capacity,
            )
            slots.append(slot)
            occ[slot.key] = inspiration
            opportunities = _collect_pass2_complement_room_opportunities(slots)

        if not slot:
            continue

        ordered = sorted(
            (
                s
                for s in students
                if not s.has_inspirator(inspiration)
                and not _student_has_full_schedule(s)
                and not s.has_pass("pass2")
                and any(
                    c.inspiration == inspiration
                    for c in _required_choices(s, suppressed)
                )
            ),
            key=lambda s: (
                -max(
                    (
                        c.rank
                        for c in _required_choices(s, suppressed)
                        if c.inspiration == inspiration
                    ),
                    default=0,
                ),
                s.id,
            ),
        )
        for student in ordered:
            if slot.remaining <= 0:
                break
            if _assign(student, slot, slot.pass_type):
                placed += 1

    return placed


def _try_fill_empty_schedule_passes(
    students: list[StudentRef],
    slots: list[SlotRef],
    rooms: list[RoomRef],
    *,
    suppressed: set[str] | None = None,
    inspirator_pass2_targets: dict[str, str] | None = None,
    minimize_sessions: bool = False,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
) -> bool:
    """Fyller lediga tidspass (pass 1/2/3) med kvarvarande val."""
    improved = False
    ordered = sorted(
        students,
        key=lambda s: (-_missing_schedule_pass_count(s), s.id),
    )
    for schedule_pass in PASS_ORDER:
        for student in ordered:
            if student.has_pass(schedule_pass):
                continue
            for choice in _required_choices(student, suppressed):
                if student.has_inspirator(choice.inspiration):
                    continue
                pass_type = _pick_pass_type(
                    slots,
                    rooms,
                    choice.inspiration,
                    schedule_pass,
                    student,
                    students,
                    minimize_sessions=minimize_sessions,
                    suppressed=suppressed,
                    inspirator_pass2_targets=inspirator_pass2_targets,
                    room_locks=room_locks,
                    exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                    exclusive_inspirators=exclusive_inspirators,
                    demand_counts=demand_counts,
                )
                if not pass_type or not _can_assign(
                    student, choice.inspiration, pass_type
                ):
                    continue
                slot = _find_slot_for(
                    slots,
                    rooms,
                    choice.inspiration,
                    pass_type,
                    students,
                    minimize_sessions=minimize_sessions,
                    suppressed=suppressed,
                    room_locks=room_locks,
                    exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                    exclusive_inspirators=exclusive_inspirators,
                    demand_counts=demand_counts,
                )
                if slot and _assign(student, slot, pass_type):
                    improved = True
                    break
    return improved


def _try_complete_partial_schedules(
    students: list[StudentRef],
    slots: list[SlotRef],
    rooms: list[RoomRef],
    *,
    suppressed: set[str] | None = None,
    inspirator_pass2_targets: dict[str, str] | None = None,
    minimize_sessions: bool = False,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
) -> bool:
    """Sista försök: elever utan tre pass får lägre val (3→2→1) om det ger ett tidspass."""
    improved = False
    partial = sorted(
        [s for s in students if not _student_has_full_schedule(s)],
        key=lambda s: (-_missing_schedule_pass_count(s), s.id),
    )
    for student in partial:
        for schedule_pass in PASS_ORDER:
            if student.has_pass(schedule_pass):
                continue
            choices = sorted(
                _required_choices(student, suppressed),
                key=lambda c: (c.rank, c.inspiration),
            )
            for choice in choices:
                if student.has_inspirator(choice.inspiration):
                    continue
                pass_type = _pick_pass_type(
                    slots,
                    rooms,
                    choice.inspiration,
                    schedule_pass,
                    student,
                    students,
                    minimize_sessions=minimize_sessions,
                    suppressed=suppressed,
                    inspirator_pass2_targets=inspirator_pass2_targets,
                    room_locks=room_locks,
                    exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                    exclusive_inspirators=exclusive_inspirators,
                    demand_counts=demand_counts,
                )
                if not pass_type or not _can_assign(
                    student, choice.inspiration, pass_type
                ):
                    continue
                slot = _find_slot_for(
                    slots,
                    rooms,
                    choice.inspiration,
                    pass_type,
                    students,
                    minimize_sessions=minimize_sessions,
                    suppressed=suppressed,
                    room_locks=room_locks,
                    exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                    exclusive_inspirators=exclusive_inspirators,
                    demand_counts=demand_counts,
                )
                if slot and _assign(student, slot, pass_type):
                    improved = True
                    break
    return improved


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
    _rebuild_student_placement_indexes(student)
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


def _unassign_from_slot(
    student: StudentRef,
    slots: list[SlotRef],
    pass_type: str,
    inspiration: str,
) -> bool:
    for i, (pt, insp) in enumerate(student.placements):
        if pt == pass_type and insp == inspiration:
            for slot in slots:
                if (
                    slot.pass_type == pass_type
                    and slot.inspiration == inspiration
                    and student.id in slot.student_ids
                ):
                    slot.student_ids.remove(student.id)
                    break
            del student.placements[i]
            _rebuild_student_placement_indexes(student)
            if pass_type in PASS2_VARIANTS and not student.has_pass("pass2"):
                student.lunch_track = None
            return True
    return False


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
    _rebuild_student_placement_indexes(student)
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
    inspirator_pass2_targets: dict[str, str] | None = None,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
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
        inspirator_pass2_targets=inspirator_pass2_targets,
        room_locks=room_locks,
        exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
        exclusive_inspirators=exclusive_inspirators,
        demand_counts=demand_counts,
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
        room_locks=room_locks,
        exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
        exclusive_inspirators=exclusive_inspirators,
        demand_counts=demand_counts,
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
    inspirator_pass2_targets: dict[str, str] | None = None,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
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
            inspirator_pass2_targets=inspirator_pass2_targets,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
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
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
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
    inspirator_pass2_targets: dict[str, str] | None = None,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
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
            inspirator_pass2_targets=inspirator_pass2_targets,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
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
            inspirator_pass2_targets=inspirator_pass2_targets,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
        ):
            return True
        _restore_student_slots(student, slots, snap)
    return False


def _inspirator_counts_by_schedule_pass(
    group: list[StudentRef], inspiration: str
) -> dict[str, int]:
    counts = {"pass1": 0, "pass2": 0, "pass3": 0}
    for s in group:
        for pt, insp in s.placements:
            if insp == inspiration:
                counts[schedule_pass_key(pt)] = counts.get(schedule_pass_key(pt), 0) + 1
    return counts


def _movable_to_consolidation_target(
    group: list[StudentRef],
    inspiration: str,
    target: SlotRef,
) -> int:
    target_key = schedule_pass_key(target.pass_type)
    n = 0
    for s in group:
        on_target = any(
            insp == inspiration and schedule_pass_key(pt) == target_key
            for pt, insp in s.placements
        )
        if on_target:
            n += 1
            continue
        if has_placement_at_pass_orm(s, target.pass_type):
            continue
        n += 1
    return n


def _best_schedule_pass_to_consolidate(
    group: list[StudentRef],
    inspiration: str,
    slots: list[SlotRef],
    rooms: list[RoomRef],
    all_students: list[StudentRef],
    n: int,
    *,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
) -> SchedulePass | None:
    """Tidspass där flest elever kan samlas (redan där eller ledigt pass)."""
    best_pass: SchedulePass | None = None
    best_score = 0
    for schedule_pass in PASS_ORDER:
        target = _pick_consolidation_target_slot(
            inspiration,
            schedule_pass,
            slots,
            rooms,
            group,
            all_students,
            n,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
        )
        if not target:
            continue
        score = _movable_to_consolidation_target(group, inspiration, target)
        if score > best_score:
            best_score = score
            best_pass = schedule_pass
    if best_score < 2:
        return None
    return best_pass


def _pick_consolidation_target_slot(
    insp: str,
    schedule_pass: SchedulePass,
    slots: list[SlotRef],
    rooms: list[RoomRef],
    group: list[StudentRef],
    all_students: list[StudentRef],
    n: int,
    *,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
) -> SlotRef | None:
    """Befintlig eller ny session för inspiratör på valt tidspass."""
    exclusive = _exclusive_for_inspiration(
        insp,
        exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
        exclusive_inspirators=exclusive_inspirators,
    )
    owners_by_room = _room_owners_from_slots(slots) if exclusive else None
    matching = [
        s
        for s in slots
        if s.inspiration == insp
        and schedule_pass_key(s.pass_type) == schedule_pass
        and _room_usable_for_inspiration(
            s.room_id,
            insp,
            slots,
            exclusive_room=exclusive,
            owners_by_room=owners_by_room,
            room_locks=room_locks,
        )
    ]
    if matching:
        fitting = [s for s in matching if s.capacity >= n]
        if fitting:
            preferred = _inspirator_preferred_room_id(slots, insp, room_locks)
            return min(
                fitting,
                key=lambda sl: (
                    0 if preferred is not None and sl.room_id == preferred else 1,
                    sl.capacity,
                    -len(sl.student_ids),
                ),
            )
        return max(matching, key=lambda sl: len(sl.student_ids))
    anchor = group[0] if group else all_students[0]
    pass_type = _pick_pass_type(
        slots, rooms, insp, schedule_pass, anchor, all_students,
        room_locks=room_locks,
        exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
        exclusive_inspirators=exclusive_inspirators,
        demand_counts=demand_counts,
    )
    if not pass_type:
        return None
    return _find_slot_for(
        slots,
        rooms,
        insp,
        pass_type,
        all_students,
        room_locks=room_locks,
        exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
        exclusive_inspirators=exclusive_inspirators,
        demand_counts=demand_counts,
    )


def _try_consolidate_small_inspirator_groups(
    students: list[StudentRef],
    slots: list[SlotRef],
    rooms: list[RoomRef],
    *,
    max_students: int = 40,
    suppressed: set[str] | None = None,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
) -> bool:
    """Flyttar alla elever till en session om gruppen är liten men utspridd."""
    by_id = {s.id: s for s in students}
    by_insp: dict[str, list[tuple[int, str, str]]] = {}
    for s in students:
        for pt, insp in s.placements:
            by_insp.setdefault(insp, []).append((s.id, pt, insp))

    improved = False
    for insp, entries in by_insp.items():
        student_ids = {e[0] for e in entries}
        n = len(student_ids)
        if n < 2 or n > max_students:
            continue
        pass_types = {e[1] for e in entries}
        if len(pass_types) < 2:
            continue

        group = [by_id[sid] for sid in student_ids]
        schedule_pass = _best_schedule_pass_to_consolidate(
            group,
            insp,
            slots,
            rooms,
            students,
            n,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
        )
        if not schedule_pass:
            continue

        target = _pick_consolidation_target_slot(
            insp, schedule_pass, slots, rooms, group, students, n,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
        )
        if not target:
            continue

        needed = n - len(target.student_ids)
        if needed > target.remaining:
            _try_move_session_to_larger_room(
                target,
                slots,
                rooms,
                extra_needed=needed,
                room_locks=room_locks,
                exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                exclusive_inspirators=exclusive_inspirators,
                demand_counts=demand_counts,
            )

        for sid in student_ids:
            s = by_id[sid]
            current = next(
                (pt for s_id, pt, i in entries if s_id == sid and i == insp),
                None,
            )
            if not current:
                continue
            if schedule_pass_key(current) == schedule_pass_key(target.pass_type):
                continue
            if has_placement_at_pass_orm(s, target.pass_type):
                continue
            if not _unassign_from_slot(s, slots, current, insp):
                continue
            if _assign(s, target, target.pass_type):
                improved = True

        # Ta bort tomma sessioner för inspiratören efter sammanslagning.
        slots[:] = [
            sl
            for sl in slots
            if sl.inspiration != insp or len(sl.student_ids) > 0
        ]

    return improved


def _try_expand_full_sessions_for_pending(
    students: list[StudentRef],
    slots: list[SlotRef],
    rooms: list[RoomRef],
    *,
    suppressed: set[str] | None = None,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
) -> bool:
    """Flyttar fulla sessioner till större rum när elever fortfarande väntar på inspiratören."""
    needs = _pending_needs(students, suppressed)
    if not needs:
        return False
    pending_by_insp: dict[str, int] = {}
    for n in needs:
        pending_by_insp[n.inspiration] = pending_by_insp.get(n.inspiration, 0) + 1
    improved = False
    for insp, count in sorted(
        pending_by_insp.items(), key=lambda x: -x[1]
    ):
        full_slots = [
            s
            for s in slots
            if s.inspiration == insp and s.remaining == 0 and len(s.student_ids) > 0
        ]
        for slot in full_slots:
            if _try_move_session_to_larger_room(
                slot,
                slots,
                rooms,
                extra_needed=count,
                room_locks=room_locks,
                exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                exclusive_inspirators=exclusive_inspirators,
                demand_counts=demand_counts,
            ):
                improved = True
                break
    return improved


def _try_reserve_for_unplaced(
    students: list[StudentRef],
    slots: list[SlotRef],
    rooms: list[RoomRef],
    *,
    suppressed: set[str],
    minimize_sessions: bool = False,
    inspirator_pass2_targets: dict[str, str] | None = None,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
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
                inspirator_pass2_targets=inspirator_pass2_targets,
                room_locks=room_locks,
                exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                exclusive_inspirators=exclusive_inspirators,
                demand_counts=demand_counts,
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
                inspirator_pass2_targets=inspirator_pass2_targets,
                room_locks=room_locks,
                exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                exclusive_inspirators=exclusive_inspirators,
                demand_counts=demand_counts,
            )

        if placed:
            placed_ids.add(student.id)

    return placed_ids


def _student_difficulty(
    student: StudentRef,
    suppressed: set[str] | None = None,
    demand_counts: dict[str, int] | None = None,
) -> tuple[int, int, int]:
    unplaced = [
        c
        for c in _required_choices(student, suppressed)
        if not student.has_inspirator(c.inspiration)
    ]
    remaining = len(unplaced)
    max_rank = max((c.rank for c in unplaced), default=0)
    max_demand = 0
    if demand_counts:
        max_demand = max(
            (demand_counts.get(c.inspiration, 0) for c in unplaced),
            default=0,
        )
    return (max_demand, remaining, max_rank)


def solve_auto_placement(
    students: list[StudentRef],
    rooms: list[RoomRef],
    slots: list[SlotRef],
    *,
    min_students_threshold: int = 0,
    try_reserve_for_unplaced: bool = False,
    balance_lunch_tracks: bool = False,
    consolidate_small_groups: bool = True,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    hybrid_room_when_short: bool = False,
    prioritize_high_demand: bool = True,
    place_unplaced_pass2_share: bool = False,
) -> AutoSolveResult:
    """Kör heuristiken. Muterar students/slots in-place."""
    minimize_sessions_per_inspirator = consolidate_small_groups
    suppressed = _compute_suppressed(students, min_students_threshold)
    suppressed_list = sorted(suppressed)
    inspirator_pass2_targets: dict[str, str] | None = None
    demand_counts = _inspirator_demand_counts(
        students,
        suppressed,
        include_reserve=try_reserve_for_unplaced,
    )
    displaced_low_demand = 0
    hybrid_shared_count = 0
    if exclusive_one_inspirator_per_room and room_locks is None:
        room_locks, exclusive_all, exclusive_only, hybrid_shared_count = compute_room_policy(
            rooms,
            demand_counts,
            same_room_exclusive=True,
            hybrid_when_short=hybrid_room_when_short,
        )
        if exclusive_only is not None:
            exclusive_inspirators = exclusive_only
            exclusive_one_inspirator_per_room = exclusive_all
    if exclusive_one_inspirator_per_room or exclusive_inspirators:
        if not room_locks:
            room_locks = {}
    if room_locks:
        if prioritize_high_demand:
            displaced_low_demand = _displace_low_demand_from_locked_rooms(
                slots,
                rooms,
                room_locks,
                demand_counts,
                low_demand_ceiling=min_students_threshold,
            )
        moved = _relocate_slots_to_locked_rooms(slots, rooms, room_locks)
        if balance_lunch_tracks:
            inspirator_pass2_targets = _plan_inspirator_pass2_variants(
                students, slots, suppressed
            )
        _seed_locked_inspirator_sessions(
            slots,
            rooms,
            room_locks,
            inspirator_pass2_targets=inspirator_pass2_targets,
            demand_counts=demand_counts,
        )
    else:
        moved = 0

    if not rooms:
        return AutoSolveResult(
            placed_new=0,
            slots_created=0,
            unplaced_needs=_pending_needs(students, suppressed),
            missing_pass_count=0,
            unplaced_student_count=0,
            score=0,
            by_choice_field={},
            summary="Inga rum – skapa rum först.",
            suppressed_inspirators=suppressed_list,
        )

    initial_placed = sum(len(s.placements) for s in students)
    initial_slot_count = len(slots)

    if prioritize_high_demand and demand_counts:
        _ensure_sessions_for_high_demand(
            slots,
            rooms,
            demand_counts,
            students,
            suppressed=suppressed,
            inspirator_pass2_targets=inspirator_pass2_targets,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
        )

    for schedule_pass in PASS_ORDER:
        if schedule_pass == "pass2":
            if balance_lunch_tracks:
                if inspirator_pass2_targets is None:
                    inspirator_pass2_targets = _plan_inspirator_pass2_variants(
                        students, slots, suppressed
                    )
            else:
                _prebalance_pass2_lunch(students, slots, suppressed)
        difficulty_key = (
            (lambda s: _student_difficulty(s, suppressed, demand_counts))
            if prioritize_high_demand
            else (lambda s: _student_difficulty(s, suppressed))
        )
        ordered = sorted(students, key=difficulty_key, reverse=True)
        for student in ordered:
            pick = _best_choice_for_pass(
                student, schedule_pass, slots, rooms, students,
                minimize_sessions=minimize_sessions_per_inspirator,
                suppressed=suppressed,
                inspirator_pass2_targets=inspirator_pass2_targets,
                room_locks=room_locks,
                exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                exclusive_inspirators=exclusive_inspirators,
                demand_counts=demand_counts,
            )
            if not pick:
                continue
            choice, pass_type = pick
            slot = _find_slot_for(
                slots, rooms, choice.inspiration, pass_type, students,
                minimize_sessions=minimize_sessions_per_inspirator,
                suppressed=suppressed,
                room_locks=room_locks,
                exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                exclusive_inspirators=exclusive_inspirators,
                demand_counts=demand_counts,
            )
            if slot:
                _assign(student, slot, pass_type)

    # Andra pass: försök fylla kvarvarande behov på vilken tid som helst
    student_by_id = {s.id: s for s in students}
    for _ in range(3):
        improved = False
        needs = _pending_needs(students, suppressed)
        if prioritize_high_demand:
            needs.sort(
                key=lambda n: (
                    -demand_counts.get(n.inspiration, 0),
                    -n.rank,
                    n.inspiration,
                )
            )
        else:
            needs.sort(key=lambda n: (-n.rank, n.inspiration))
        for need in needs:
            student = student_by_id.get(need.student_id)
            if student is None:
                continue
            if student.has_inspirator(need.inspiration):
                continue
            for schedule_pass in PASS_ORDER:
                if student.has_pass(schedule_pass):
                    continue
                pass_type = _pick_pass_type(
                    slots, rooms, need.inspiration, schedule_pass, student, students,
                    minimize_sessions=minimize_sessions_per_inspirator,
                    suppressed=suppressed,
                    inspirator_pass2_targets=inspirator_pass2_targets,
                    room_locks=room_locks,
                    exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                    exclusive_inspirators=exclusive_inspirators,
                    demand_counts=demand_counts,
                )
                if not pass_type:
                    continue
                slot = _find_slot_for(
                    slots, rooms, need.inspiration, pass_type, students,
                    minimize_sessions=minimize_sessions_per_inspirator,
                    suppressed=suppressed,
                    room_locks=room_locks,
                    exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                    exclusive_inspirators=exclusive_inspirators,
                    demand_counts=demand_counts,
                )
                if slot and _assign(student, slot, pass_type):
                    improved = True
                    break
        if not improved:
            break

    for _ in range(3):
        if not _try_expand_full_sessions_for_pending(
            students,
            slots,
            rooms,
            suppressed=suppressed,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
        ):
            break

    if consolidate_small_groups:
        for _ in range(3):
            if not _try_consolidate_small_inspirator_groups(
                students,
                slots,
                rooms,
                suppressed=suppressed,
                room_locks=room_locks,
                exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                exclusive_inspirators=exclusive_inspirators,
                demand_counts=demand_counts,
            ):
                break

    for _ in range(3):
        if not _try_fill_empty_schedule_passes(
            students,
            slots,
            rooms,
            suppressed=suppressed,
            inspirator_pass2_targets=inspirator_pass2_targets,
            minimize_sessions=minimize_sessions_per_inspirator,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
        ):
            break

    pass2_room_share_count = 0
    if place_unplaced_pass2_share:
        for _ in range(3):
            n = _try_place_unplaced_in_pass2_room_share(
                students,
                slots,
                rooms,
                suppressed=suppressed,
            )
            if n <= 0:
                break
            pass2_room_share_count += n
            for _ in range(2):
                if not _try_fill_empty_schedule_passes(
                    students,
                    slots,
                    rooms,
                    suppressed=suppressed,
                    inspirator_pass2_targets=inspirator_pass2_targets,
                    minimize_sessions=minimize_sessions_per_inspirator,
                    room_locks=room_locks,
                    exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
                    exclusive_inspirators=exclusive_inspirators,
                    demand_counts=demand_counts,
                ):
                    break

    reserve_fallback_ids: set[int] = set()
    if try_reserve_for_unplaced:
        reserve_fallback_ids = _try_reserve_for_unplaced(
            students,
            slots,
            rooms,
            suppressed=suppressed,
            minimize_sessions=minimize_sessions_per_inspirator,
            inspirator_pass2_targets=inspirator_pass2_targets,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
        )

    for _ in range(2):
        if not _try_fill_empty_schedule_passes(
            students,
            slots,
            rooms,
            suppressed=suppressed,
            inspirator_pass2_targets=inspirator_pass2_targets,
            minimize_sessions=minimize_sessions_per_inspirator,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
        ):
            break

    for _ in range(4):
        if not _try_complete_partial_schedules(
            students,
            slots,
            rooms,
            suppressed=suppressed,
            inspirator_pass2_targets=inspirator_pass2_targets,
            minimize_sessions=minimize_sessions_per_inspirator,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
            exclusive_inspirators=exclusive_inspirators,
            demand_counts=demand_counts,
        ):
            break

    # Ta bort tomma celler som skapats under sökning men aldrig fylldes.
    slots[:] = [s for s in slots if len(s.student_ids) > 0]
    _prune_student_placements_to_slots(students, slots)

    final_placed = sum(len(s.placements) for s in students)
    placed_new = final_placed - initial_placed
    slots_created = len(slots) - initial_slot_count
    unplaced = _pending_needs(students, suppressed)
    if reserve_fallback_ids:
        unplaced = [n for n in unplaced if n.student_id not in reserve_fallback_ids]
    score = 0
    by_field: dict[str, int] = {f: 0 for f in CHOICE_RANK}
    for s in students:
        for choice in _student_choices_list(s):
            if choice.inspiration in s.placement_inspirations:
                score += choice.rank
        choice_lookup = _choice_field_by_inspiration(s)
        for insp in s.placement_inspirations:
            field_rank = choice_lookup.get(insp)
            if not field_rank:
                continue
            field, _rank = field_rank
            by_field[field] = by_field.get(field, 0) + 1

    unplaced_count = len(unplaced)
    missing_pass = _students_missing_schedule_pass(students)
    missing_pass_count = len(missing_pass)
    unplaced_student_count = count_students_needing_placement_attention(
        students, suppressed
    )
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
    if missing_pass_count > 0:
        if missing_pass_count == 1:
            unplaced_part += " 1 elev saknar fortfarande ett tidspass (pass 1, 2 eller 3)."
        else:
            unplaced_part += (
                f" {missing_pass_count} elever saknar fortfarande ett tidspass."
            )
    summary = (
        f"{placed_new} val placerade "
        f"(totalt {final_placed} pass på {len(students)} elever). "
        f"{unplaced_part}"
    )
    if suppressed_list:
        summary += (
            f" {len(suppressed_list)} inspiratör(er) under tröskel – elever dirigeras till reserv."
        )
    if balance_lunch_tracks:
        lunch_2a, lunch_2b = _pass2_lunch_counts(students, slots)
        summary += f" Lunch: {lunch_2a} elever på 2a, {lunch_2b} på 2b."
    if room_locks:
        n = len(room_locks)
        if hybrid_shared_count > 0:
            summary += (
                f" Ett rum per inspiratör, hybrid: {n} egna rum,"
                f" {hybrid_shared_count} med minst val delar rum"
                + (f", {moved} sessioner flyttade" if moved else "")
                + (
                    f", {displaced_low_demand} låg-efterfrågade omplacerade"
                    if displaced_low_demand
                    else ""
                )
                + "."
            )
        else:
            summary += (
                f" Ett rum per inspiratör ({n} tilldelade efter efterfrågan"
                + (f", {moved} sessioner flyttade" if moved else "")
                + (
                    f", {displaced_low_demand} låg-efterfrågade sessioner omplacerade"
                    if displaced_low_demand
                    else ""
                )
                + ")."
            )
            if (
                not hybrid_room_when_short
                and prioritize_high_demand
                and n < len(rooms)
            ):
                summary += (
                    f" Bara {len(rooms)} rum – endast de {n} mest valda inspiratörerna"
                    " får eget rum."
                )
    elif try_reserve_for_unplaced and demand_counts:
        top = max(demand_counts.values(), default=0)
        if top >= 8:
            summary += " Populära inspiratörer prioriterar större rum."
    if pass2_room_share_count:
        if pass2_room_share_count == 1:
            summary += " 1 elev placerad via delat pass-2-rum (2a/2b)."
        else:
            summary += (
                f" {pass2_room_share_count} elever placerade via delat pass-2-rum (2a/2b)."
            )

    lunch_2a, lunch_2b = _pass2_lunch_counts(students, slots)
    return AutoSolveResult(
        placed_new=placed_new,
        slots_created=slots_created,
        unplaced_needs=unplaced,
        missing_pass_count=missing_pass_count,
        unplaced_student_count=unplaced_student_count,
        score=score,
        by_choice_field=by_field,
        summary=summary,
        suppressed_inspirators=suppressed_list,
        lunch_2a=lunch_2a,
        lunch_2b=lunch_2b,
        rooms_relocated=moved,
        reserve_placed_count=len(reserve_fallback_ids),
        pass2_room_share_count=pass2_room_share_count,
    )


def run_on_orm(
    students_orm,
    rooms_orm,
    slots_orm,
    *,
    min_students_threshold: int = 0,
    try_reserve_for_unplaced: bool = False,
    balance_lunch_tracks: bool = False,
    consolidate_small_groups: bool = True,
    room_locks: dict[str, int] | None = None,
    exclusive_one_inspirator_per_room: bool = False,
    exclusive_inspirators: set[str] | None = None,
    hybrid_room_when_short: bool = False,
    prioritize_high_demand: bool = True,
    place_unplaced_pass2_share: bool = False,
) -> tuple[list[StudentRef], list[SlotRef], AutoSolveResult]:
    students = [_load_student_from_orm(s) for s in students_orm]
    rooms = [RoomRef(r.id, r.name, r.capacity) for r in rooms_orm]
    slots = [_load_slot_from_orm(s) for s in slots_orm]
    result = solve_auto_placement(
        students, rooms, slots,
        min_students_threshold=min_students_threshold,
        try_reserve_for_unplaced=try_reserve_for_unplaced,
        balance_lunch_tracks=balance_lunch_tracks,
        consolidate_small_groups=consolidate_small_groups,
        room_locks=room_locks,
        exclusive_one_inspirator_per_room=exclusive_one_inspirator_per_room,
        exclusive_inspirators=exclusive_inspirators,
        hybrid_room_when_short=hybrid_room_when_short,
        prioritize_high_demand=prioritize_high_demand,
        place_unplaced_pass2_share=place_unplaced_pass2_share,
    )
    return students, slots, result


def _prune_student_placements_to_slots(
    students: list[StudentRef], slots: list[SlotRef]
) -> None:
    """Tar bort elevplaceringar vars session tagits bort (tomma rutor)."""
    valid = {(s.inspiration, s.pass_type) for s in slots}
    for student in students:
        student.placements = [
            (pt, insp)
            for pt, insp in student.placements
            if (insp, pt) in valid
        ]
        _rebuild_student_placement_indexes(student)


def _rebuild_slot_student_ids_from_placements(
    students: list[StudentRef], slots: list[SlotRef]
) -> None:
    """Synkar slot.student_ids från elevlistan (samma sanning som apply ska skriva)."""
    for slot in slots:
        slot.student_ids.clear()
    slot_map = {(s.inspiration, s.pass_type): s for s in slots}
    for student in students:
        for pass_type, inspiration in student.placements:
            slot = slot_map.get((inspiration, pass_type))
            if slot is not None and student.id not in slot.student_ids:
                slot.student_ids.append(student.id)


def _find_slot_ref(
    slots: list[SlotRef], inspiration: str, pass_type: str
) -> SlotRef | None:
    for slot in slots:
        if slot.inspiration == inspiration and slot.pass_type == pass_type:
            return slot
    return None


def _merge_slots_for_apply(slots: list[SlotRef]) -> list[SlotRef]:
    """En DB-ruta per (rum, passtyp); slår ihop elevlistor."""
    merged: dict[tuple[int, str], SlotRef] = {}
    for slot in slots:
        key = slot.key
        if key not in merged:
            merged[key] = SlotRef(
                id=slot.id,
                room_id=slot.room_id,
                pass_type=slot.pass_type,
                inspiration=slot.inspiration,
                capacity=slot.capacity,
                student_ids=list(slot.student_ids),
            )
        else:
            existing = merged[key]
            if existing.inspiration != slot.inspiration:
                continue
            for sid in slot.student_ids:
                if sid not in existing.student_ids:
                    existing.student_ids.append(sid)
    return list(merged.values())


def apply_fill_solution_to_db(db, students_orm, slots: list[SlotRef]) -> int:
    """Lägger till nya slots och placeringar; befintliga behålls (läge fill)."""
    from app.models import Placement, SessionSlot

    student_by_id = {s.id: s for s in students_orm}
    existing_pairs: set[tuple[int, int]] = set()
    for s in students_orm:
        for p in s.placements:
            existing_pairs.add((p.student_id, p.session_slot_id))

    new_placements = 0

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

        existing_n = (
            db.query(Placement)
            .filter(Placement.session_slot_id == db_slot.id)
            .count()
        )
        if existing_n == 0 and db_slot.inspiration != slot.inspiration:
            db_slot.inspiration = slot.inspiration

        for sid in slot.student_ids:
            key = (sid, db_slot.id)
            if key in existing_pairs:
                continue
            student = student_by_id.get(sid)
            if not student:
                continue
            if not student_chose_required(student, db_slot.inspiration):
                continue
            db.add(Placement(student_id=sid, session_slot_id=db_slot.id))
            if slot.pass_type in PASS2_VARIANTS:
                student.lunch_track = "2a" if slot.pass_type == "pass2a" else "2b"
            existing_pairs.add(key)
            new_placements += 1

    return new_placements


def apply_replace_solution_to_db(
    db,
    students_orm,
    students_ref: list[StudentRef],
    slots: list[SlotRef],
) -> tuple[int, int]:
    """Skriver hela lösningen till databasen (kräver tomma placements/session_slots)."""
    from app.models import Placement, SessionSlot

    from app.helpers import student_chose

    _prune_student_placements_to_slots(students_ref, slots)
    _rebuild_slot_student_ids_from_placements(students_ref, slots)

    student_by_id = {s.id: s for s in students_orm}
    written = 0
    skipped = 0
    seen_schedule: set[tuple[int, str]] = set()

    for slot in _merge_slots_for_apply(slots):
        if not slot.student_ids:
            continue

        db_slot = SessionSlot(
            room_id=slot.room_id,
            pass_type=slot.pass_type,
            inspiration=slot.inspiration,
        )
        db.add(db_slot)
        db.flush()

        for sid in slot.student_ids:
            schedule_key = schedule_pass_key(slot.pass_type)
            dedupe = (sid, schedule_key)
            if dedupe in seen_schedule:
                skipped += 1
                continue
            seen_schedule.add(dedupe)

            student = student_by_id.get(sid)
            if not student:
                skipped += 1
                continue
            if not student_chose(student, slot.inspiration):
                skipped += 1
                continue

            db.add(Placement(student_id=sid, session_slot_id=db_slot.id))
            written += 1

    for student_ref in students_ref:
        student = student_by_id.get(student_ref.id)
        if student is None:
            continue
        pass2_type = student_ref.pass_type_for("pass2")
        if pass2_type in PASS2_VARIANTS:
            student.lunch_track = "2a" if pass2_type == "pass2a" else "2b"
        else:
            student.lunch_track = None

    return written, skipped
