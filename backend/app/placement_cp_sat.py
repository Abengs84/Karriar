"""
Global placering med Google OR-Tools CP-SAT.

Till skillnad från heuristiken i auto_placer.py söker denna modul efter en
tillåten lösning (eller bevisar att ingen finns) under angivna hårda regler:

- Varje elev får exakt sina val 1–3 (efter dedup/reserv) på pass 1, 2 och 3.
- Högst ett möte per inspiratör och elev.
- Högst tre tidspass per inspiratör (pass 1, 2, 3).
- Straff för sessioner med färre än min_session_size elever (mjuk regel).
- Rumskapacitet och högst en inspiratör per (rum, passtyp) samtidigt.
- Ett rum per inspiratör när det räcker; vid rumsbrist delar minst valda rum.
- Lunchspår 2a/2b per inspiratör (låst) med balansering i målfunktionen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ortools.sat.python import cp_model

from app.auto_placer import (
    CHOICE_RANK,
    PASS2_VARIANTS,
    AutoSolveResult,
    RoomRef,
    SlotRef,
    StudentRef,
    _choice_field_by_inspiration,
    _compute_suppressed,
    _load_student_from_orm,
    _pass2_lunch_counts,
    _pending_needs,
    _rebuild_student_placement_indexes,
    _student_choices_list,
    count_students_needing_placement_attention,
    iter_required_choice_fields,
)
SchedulePassIdx = Literal[0, 1, 2]
PASS_LABELS: tuple[str, str, str] = ("pass1", "pass2", "pass3")
ALL_PASS_TYPES = ("pass1", "pass2a", "pass2b", "pass3")


@dataclass
class CpSatConfig:
    min_session_size: int = 5
    time_limit_seconds: float = 120.0
    balance_lunch_tracks: bool = True
    same_room_per_inspirator: bool = True
    hybrid_room_when_short: bool = True
    lunch_imbalance_weight: int = 50
    small_session_penalty_weight: int = 200
    room_sharing_penalty: int = 10
    minimize_sessions_weight: int = 500
    minimize_sessions_for: frozenset[str] = frozenset()
    room_locks: dict[str, int] = field(default_factory=dict)
    place_unplaced_pass2_share: bool = True
    try_reserve_for_unplaced: bool = True


@dataclass
class CpSatDiagnostics:
    status: str
    wall_time: float
    placed_required: int
    required_total: int
    small_sessions: list[tuple[str, str, int]] = field(default_factory=list)
    infeasible_hints: list[str] = field(default_factory=list)


def _required_triples(student: StudentRef) -> list[str]:
    return [insp for _, insp in iter_required_choice_fields(student)]


def _choice_rank(student: StudentRef, inspiration: str) -> int:
    for c in _student_choices_list(student):
        if c.inspiration == inspiration:
            return c.rank
    return 0


def _pass2_targets_from_slots(slots: list[SlotRef]) -> dict[str, str]:
    targets: dict[str, str] = {}
    for slot in slots:
        if slot.pass_type in PASS2_VARIANTS:
            targets[slot.inspiration] = slot.pass_type
    return targets


def _cp_sat_post_placement_kwargs(
    students: list[StudentRef],
    slots: list[SlotRef],
    rooms: list[RoomRef],
    *,
    suppressed: set[str],
    cfg: CpSatConfig,
) -> dict:
    from app.auto_placer import _inspirator_demand_counts, compute_room_policy

    pass2_targets = _pass2_targets_from_slots(slots) or None
    demand_counts = _inspirator_demand_counts(
        students, suppressed, include_reserve=cfg.try_reserve_for_unplaced
    )
    room_locks = dict(cfg.room_locks)
    exclusive_inspirators: set[str] | None = None
    if cfg.same_room_per_inspirator:
        policy_locks, _exclusive_all, exclusive_only, _ = compute_room_policy(
            rooms,
            demand_counts,
            same_room_exclusive=True,
            hybrid_when_short=cfg.hybrid_room_when_short,
        )
        for insp, rid in policy_locks.items():
            room_locks.setdefault(insp, rid)
        if cfg.hybrid_room_when_short and exclusive_only is not None:
            exclusive_inspirators = exclusive_only

    return dict(
        suppressed=suppressed,
        inspirator_pass2_targets=pass2_targets,
        room_locks=room_locks or None,
        exclusive_one_inspirator_per_room=cfg.same_room_per_inspirator,
        exclusive_inspirators=exclusive_inspirators,
        demand_counts=demand_counts,
        minimize_sessions=False,
        place_unplaced_pass2_share=cfg.place_unplaced_pass2_share,
        seed_locked_sessions=True,
        min_session_size=cfg.min_session_size,
    )


def _apply_cp_sat_post_placement(
    students: list[StudentRef],
    slots: list[SlotRef],
    rooms: list[RoomRef],
    *,
    suppressed: set[str],
    cfg: CpSatConfig,
) -> None:
    """Fyll kvarvarande val/slot som CP-SAT lämnat (samma steg som heuristiken)."""
    from app.auto_placer import run_post_placement_finalize

    run_post_placement_finalize(
        students,
        slots,
        rooms,
        **_cp_sat_post_placement_kwargs(students, slots, rooms, suppressed=suppressed, cfg=cfg),
    )


def finalize_cp_sat_before_db_apply(
    students: list[StudentRef],
    slots: list[SlotRef],
    rooms: list[RoomRef],
    *,
    suppressed: set[str],
    cfg: CpSatConfig,
) -> int:
    """Kör post-placering igen före DB-skrivning (t.ex. efter reservsteg)."""
    from app.auto_placer import run_post_placement_finalize

    return run_post_placement_finalize(
        students,
        slots,
        rooms,
        **_cp_sat_post_placement_kwargs(students, slots, rooms, suppressed=suppressed, cfg=cfg),
    )


def _apply_reserve_fallback(
    students: list[StudentRef],
    slots: list[SlotRef],
    rooms: list[RoomRef],
    *,
    suppressed: set[str],
    cfg: CpSatConfig,
) -> set[int]:
    """Placera reserv på ledigt pass (eller via omflyttning) efter CP-SAT."""
    from app.auto_placer import (
        _inspirator_demand_counts,
        _try_reserve_for_unplaced,
    )

    demand_counts = _inspirator_demand_counts(
        students,
        suppressed,
        include_reserve=True,
    )
    return _try_reserve_for_unplaced(
        students,
        slots,
        rooms,
        suppressed=suppressed,
        minimize_sessions=True,
        inspirator_pass2_targets=_pass2_targets_from_slots(slots) or None,
        exclusive_one_inspirator_per_room=cfg.same_room_per_inspirator,
        demand_counts=demand_counts,
    )


def _build_auto_solve_result(
    students: list[StudentRef],
    slots: list[SlotRef],
    *,
    suppressed: set[str],
    suppressed_list: list[str],
    incomplete_count: int,
    diag: CpSatDiagnostics,
    cfg: CpSatConfig,
    placed_count: int,
    reserve_ids: set[int],
    n_insp: int,
    n_rooms: int,
) -> AutoSolveResult:
    unplaced = _pending_needs(students, suppressed)
    if reserve_ids:
        unplaced = [n for n in unplaced if n.student_id not in reserve_ids]

    score = 0
    by_field: dict[str, int] = {f: 0 for f in CHOICE_RANK}
    for s in students:
        for choice in _student_choices_list(s):
            if choice.inspiration in s.placement_inspirations:
                score += choice.rank
        choice_lookup = _choice_field_by_inspiration(s)
        for insp in s.placement_inspirations:
            field_rank = choice_lookup.get(insp)
            if field_rank:
                by_field[field_rank[0]] = by_field.get(field_rank[0], 0) + 1

    lunch_2a, lunch_2b = _pass2_lunch_counts(students, slots)
    unplaced_count = len(unplaced)
    reserve_count = len(reserve_ids)

    if unplaced_count == 0:
        if reserve_count:
            unplaced_part = (
                f"Alla val 1–3 har pass eller reserv ({reserve_count} på reserv)."
            )
        else:
            unplaced_part = "Alla val 1–3 har fått pass."
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
        f"CP-SAT ({diag.status}, {diag.wall_time:.1f}s): "
        f"{placed_count} placeringar på {len(students)} elever. {unplaced_part}"
    )
    if cfg.min_session_size > 0:
        summary += f" Min {cfg.min_session_size} elever/session."
    if cfg.balance_lunch_tracks:
        summary += f" Lunch: {lunch_2a} på 2a, {lunch_2b} på 2b."
    if cfg.same_room_per_inspirator:
        if n_insp <= n_rooms:
            summary += " Eget rum per inspiratör."
        elif cfg.hybrid_room_when_short:
            summary += (
                f" Hybrid: {n_rooms} egna rum för mest valda, övriga kan dela."
            )
    if diag.small_sessions:
        summary += f" Varning: {len(diag.small_sessions)} session(er) under tröskel."
    if cfg.minimize_sessions_for:
        n = len(cfg.minimize_sessions_for)
        summary += (
            f" Mål: färre sessioner för {n} vald{'a' if n != 1 else ''} "
            f"inspiratör{'er' if n != 1 else ''}."
        )
    if cfg.room_locks:
        n = len(cfg.room_locks)
        summary += f" {n} rumslås aktiv{'a' if n != 1 else 't'}."

    return AutoSolveResult(
        placed_new=placed_count,
        slots_created=len(slots),
        unplaced_needs=unplaced,
        missing_pass_count=incomplete_count,
        unplaced_student_count=count_students_needing_placement_attention(
            students, suppressed
        ),
        score=score,
        by_choice_field=by_field,
        summary=summary,
        suppressed_inspirators=suppressed_list,
        lunch_2a=lunch_2a,
        lunch_2b=lunch_2b,
        reserve_placed_count=reserve_count,
    )


def _inspirator_demand(students: list[StudentRef], suppressed: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in students:
        seen: set[str] = set()
        for insp in _required_triples(s):
            if insp in suppressed or insp in seen:
                continue
            seen.add(insp)
            counts[insp] = counts.get(insp, 0) + 1
    return counts


def _pass_type_for(inspiration: str, pass_idx: int, pass2_variant: str) -> str:
    if pass_idx == 0:
        return "pass1"
    if pass_idx == 1:
        return pass2_variant
    return "pass3"


def solve_cp_sat(
    students: list[StudentRef],
    rooms: list[RoomRef],
    slots: list[SlotRef],
    *,
    min_students_threshold: int = 0,
    config: CpSatConfig | None = None,
) -> tuple[list[StudentRef], list[SlotRef], AutoSolveResult, CpSatDiagnostics]:
    """
    Kör CP-SAT. Tömmer och ersätter slots; uppdaterar student.placements.
    """
    cfg = config or CpSatConfig()
    suppressed = _compute_suppressed(students, min_students_threshold)
    suppressed_list = sorted(suppressed)

    diag = CpSatDiagnostics(
        status="UNKNOWN",
        wall_time=0.0,
        placed_required=0,
        required_total=0,
    )

    if not rooms:
        result = AutoSolveResult(
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
        diag.status = "NO_ROOMS"
        return students, slots, result, diag

    active_students = [
        s for s in students if len(_required_triples(s)) == 3
    ]
    incomplete = [s for s in students if s not in active_students]
    if incomplete:
        diag.infeasible_hints.append(
            f"{len(incomplete)} elev(er) har färre än tre giltiga val 1–3."
        )

    inspirations = sorted(
        {
            insp
            for s in active_students
            for insp in _required_triples(s)
            if insp not in suppressed
        }
    )
    if not inspirations:
        result = AutoSolveResult(
            placed_new=0,
            slots_created=0,
            unplaced_needs=_pending_needs(students, suppressed),
            missing_pass_count=0,
            unplaced_student_count=0,
            score=0,
            by_choice_field={},
            summary="Inga inspiratörer att placera.",
            suppressed_inspirators=suppressed_list,
        )
        diag.status = "NO_INSPIRATIONS"
        return students, slots, result, diag

    demand = _inspirator_demand(active_students, suppressed)
    diag.required_total = sum(len(_required_triples(s)) for s in active_students)

    for insp, n in demand.items():
        # Detta var tidigare en hård INFEASIBLE-orsak. Nu är min_session_size en mjuk regel
        # (straff i målfunktionen), så vi lägger bara en hint.
        if 0 < cfg.min_session_size and 0 < n < cfg.min_session_size:
            diag.infeasible_hints.append(
                f"{insp}: bara {n} val 1–3 – under min {cfg.min_session_size} "
                "(tillåts men straffas)."
            )

    room_by_idx = {i: r for i, r in enumerate(rooms)}
    n_rooms = len(rooms)
    insp_idx = {name: i for i, name in enumerate(inspirations)}
    n_insp = len(inspirations)

    model = cp_model.CpModel()

    # assign[s, i_idx, p] – elev s träffar inspiratör i på tidspass p (0/1/2)
    assign: dict[tuple[int, int, int], cp_model.IntVar] = {}
    for s in active_students:
        sid = s.id
        triples = [insp for insp in _required_triples(s) if insp not in suppressed]
        if len(triples) != 3:
            continue
        for insp in triples:
            i_idx = insp_idx[insp]
            for p in range(3):
                assign[(sid, i_idx, p)] = model.NewBoolVar(
                    f"a_{sid}_{i_idx}_{p}"
                )

    for s in active_students:
        sid = s.id
        triples = [insp for insp in _required_triples(s) if insp not in suppressed]
        if len(triples) != 3:
            continue
        for insp in triples:
            i_idx = insp_idx[insp]
            model.Add(
                sum(assign[(sid, i_idx, p)] for p in range(3)) == 1
            )
        for p in range(3):
            model.Add(
                sum(
                    assign[(sid, insp_idx[insp], p)]
                    for insp in triples
                )
                == 1
            )

    # sessionsstorlek per (inspiratör, pass)
    session_size: dict[tuple[int, int], cp_model.IntVar] = {}
    session_active: dict[tuple[int, int], cp_model.IntVar] = {}
    session_deficit: dict[tuple[int, int], cp_model.IntVar] = {}
    for i_idx in range(n_insp):
        for p in range(3):
            terms = [
                assign[(s.id, i_idx, p)]
                for s in active_students
                if (s.id, i_idx, p) in assign
            ]
            if not terms:
                continue
            sz = model.NewIntVar(0, len(active_students), f"sz_{i_idx}_{p}")
            model.Add(sz == sum(terms))
            session_size[(i_idx, p)] = sz
            active = model.NewBoolVar(f"sess_{i_idx}_{p}")
            session_active[(i_idx, p)] = active
            # Mjuk minsta sessionsstorlek:
            # - Om sessionen är aktiv: minst 1 elev
            # - Underskott mot min_session_size straffas i målfunktionen
            model.Add(sz >= 1).OnlyEnforceIf(active)
            model.Add(sz == 0).OnlyEnforceIf(active.Not())
            if cfg.min_session_size > 1:
                undershoot = model.NewIntVar(
                    0, cfg.min_session_size, f"under_{i_idx}_{p}"
                )
                deficit = model.NewIntVar(
                    0, cfg.min_session_size, f"def_{i_idx}_{p}"
                )
                # Straffa bara aktiva sessioner (sz >= 1). Inaktiva (sz == 0)
                # får undershoot/deficit = 0 – annars blir modellen INFEASIBLE.
                model.Add(undershoot >= cfg.min_session_size - sz).OnlyEnforceIf(
                    active
                )
                model.Add(undershoot == 0).OnlyEnforceIf(active.Not())
                model.AddMaxEquality(deficit, [undershoot, 0])
                session_deficit[(i_idx, p)] = deficit

    # Rum per inspiratör
    room_of: list[cp_model.IntVar] = []
    for i_idx in range(n_insp):
        room_of.append(
            model.NewIntVar(0, n_rooms - 1, f"room_{i_idx}")
        )

    # Eget rum per inspiratör när det räcker (hårt); annars mjuk straff vid delning.
    if cfg.same_room_per_inspirator and n_insp <= n_rooms:
        model.AddAllDifferent(room_of)

    room_id_to_idx = {r.id: i for i, r in enumerate(rooms)}
    for insp, room_id in cfg.room_locks.items():
        i_idx = insp_idx.get(insp)
        r_idx = room_id_to_idx.get(room_id)
        if i_idx is None or r_idx is None:
            continue
        model.Add(room_of[i_idx] == r_idx)

    # Pass 2-variant per inspiratör (0=2a, 1=2b)
    pass2_is_b: list[cp_model.IntVar] = []
    for i_idx in range(n_insp):
        pass2_is_b.append(model.NewBoolVar(f"p2b_{i_idx}"))

    # Rumskapacitet per inspiratörspass (samma rum alla pass)
    caps = [room_by_idx[r].capacity for r in range(n_rooms)]
    max_cap = max(caps) if caps else 0
    for i_idx in range(n_insp):
        for p in range(3):
            if (i_idx, p) not in session_size:
                continue
            cap_at_room = model.NewIntVar(0, max_cap, f"cap_{i_idx}_{p}")
            model.AddElement(room_of[i_idx], caps, cap_at_room)
            model.Add(session_size[(i_idx, p)] <= cap_at_room)

    for r_idx in range(n_rooms):
        for pt in ALL_PASS_TYPES:
            if pt == "pass1":
                p_idx = 0
            elif pt == "pass3":
                p_idx = 2
            else:
                p_idx = 1

            occupiers: list[cp_model.IntVar] = []
            for i_idx in range(n_insp):
                if (i_idx, p_idx) not in session_active:
                    continue
                uses = model.NewBoolVar(f"use_{i_idx}_{r_idx}_{pt}")
                on_room = model.NewBoolVar(f"onroom_{i_idx}_{r_idx}")
                model.Add(room_of[i_idx] == r_idx).OnlyEnforceIf(on_room)
                model.Add(room_of[i_idx] != r_idx).OnlyEnforceIf(on_room.Not())
                sess_on = session_active[(i_idx, p_idx)]

                factors: list[cp_model.IntVar] = [on_room, sess_on]
                if pt == "pass2a":
                    factors.append(pass2_is_b[i_idx].Not())
                elif pt == "pass2b":
                    factors.append(pass2_is_b[i_idx])

                if len(factors) == 2:
                    model.AddMultiplicationEquality(uses, factors)
                else:
                    model.AddMultiplicationEquality(uses, factors)

                occupiers.append(uses)

            if occupiers:
                model.Add(sum(occupiers) <= 1)

    # Mål: prioritera högre val + färre delade rum + jämn lunch
    objective_terms: list[cp_model.LinearExpr] = []
    for (sid, i_idx, p), var in assign.items():
        student = next(s for s in active_students if s.id == sid)
        insp = inspirations[i_idx]
        objective_terms.append(var * _choice_rank(student, insp))

    if cfg.same_room_per_inspirator:
        for a in range(n_insp):
            for b in range(a + 1, n_insp):
                da = demand.get(inspirations[a], 0)
                db = demand.get(inspirations[b], 0)
                # Straffa delat rum; lägre straff när minst en har få val (hybrid).
                weight = cfg.room_sharing_penalty
                if cfg.hybrid_room_when_short and n_insp > n_rooms:
                    if min(da, db) <= 15:
                        weight = max(1, weight // 4)
                share = model.NewBoolVar(f"share_{a}_{b}")
                model.Add(room_of[a] == room_of[b]).OnlyEnforceIf(share)
                model.Add(room_of[a] != room_of[b]).OnlyEnforceIf(share.Not())
                objective_terms.append(share * (-weight))

    if cfg.min_session_size > 1 and session_deficit:
        for deficit in session_deficit.values():
            objective_terms.append(deficit * (-cfg.small_session_penalty_weight))

    lunch_2a = model.NewIntVar(0, len(active_students), "lunch_2a")
    lunch_2b = model.NewIntVar(0, len(active_students), "lunch_2b")
    terms_2a: list[cp_model.IntVar] = []
    terms_2b: list[cp_model.IntVar] = []
    for (sid, i_idx, p), var in assign.items():
        if p != 1:
            continue
        in_2a = model.NewBoolVar(f"l2a_{sid}_{i_idx}")
        in_2b = model.NewBoolVar(f"l2b_{sid}_{i_idx}")
        model.AddMultiplicationEquality(in_2a, [var, pass2_is_b[i_idx].Not()])
        model.AddMultiplicationEquality(in_2b, [var, pass2_is_b[i_idx]])
        terms_2a.append(in_2a)
        terms_2b.append(in_2b)
    if terms_2a:
        model.Add(lunch_2a == sum(terms_2a))
    else:
        model.Add(lunch_2a == 0)
    if terms_2b:
        model.Add(lunch_2b == sum(terms_2b))
    else:
        model.Add(lunch_2b == 0)

    if cfg.balance_lunch_tracks:
        diff = model.NewIntVar(0, len(active_students), "lunch_diff")
        model.AddAbsEquality(diff, lunch_2a - lunch_2b)
        objective_terms.append(diff * (-cfg.lunch_imbalance_weight))

    if cfg.minimize_sessions_for:
        for i_idx, insp in enumerate(inspirations):
            if insp not in cfg.minimize_sessions_for:
                continue
            for p in range(3):
                active = session_active.get((i_idx, p))
                if active is not None:
                    objective_terms.append(
                        active * (-cfg.minimize_sessions_weight)
                    )

    model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = cfg.time_limit_seconds
    solver.parameters.num_search_workers = 8

    status = solver.Solve(model)
    diag.wall_time = solver.WallTime()
    diag.status = solver.StatusName(status)

    # Bygg slots från lösning
    for s in students:
        s.placements.clear()
        _rebuild_student_placement_indexes(s)
    slots.clear()

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        summary = (
            f"CP-SAT hittade ingen lösning ({diag.status}) på {diag.wall_time:.1f}s. "
            "Det betyder att reglerna inte går att uppfylla samtidigt med nuvarande "
            "rum, kapacitet och krav. Vanliga orsaker: rums-/kapacitetsbrist, för många "
            "val till samma inspiratör, eller elever som saknar tre giltiga val 1–3."
            " Förslag: lägg till fler/större rum, sänk «Minst elever per session», "
            "aktivera «Hybrid vid rumsbrist» (om «Ett rum per inspiratör» är på), "
            "höj/dra ned tröskeln för dolda inspiratörer, eller komplettera elever "
            "med saknade val."
        )
        if diag.infeasible_hints:
            summary += " Indikationer: " + " ".join(diag.infeasible_hints[:3])
        result = AutoSolveResult(
            placed_new=0,
            slots_created=0,
            unplaced_needs=_pending_needs(students, suppressed),
            missing_pass_count=len(incomplete),
            unplaced_student_count=count_students_needing_placement_attention(
                students, suppressed
            ),
            score=0,
            by_choice_field={},
            summary=summary,
            suppressed_inspirators=suppressed_list,
        )
        return students, slots, result, diag

    pass2_variant: dict[int, str] = {}
    for i_idx in range(n_insp):
        pass2_variant[i_idx] = (
            "pass2b" if solver.Value(pass2_is_b[i_idx]) else "pass2a"
        )

    new_slots: dict[tuple[int, str, str], SlotRef] = {}
    placed_count = 0

    for s in active_students:
        sid = s.id
        for insp in _required_triples(s):
            if insp in suppressed:
                continue
            i_idx = insp_idx[insp]
            for p in range(3):
                var = assign.get((sid, i_idx, p))
                if var is None or solver.Value(var) != 1:
                    continue
                r_idx = solver.Value(room_of[i_idx])
                room = room_by_idx[r_idx]
                pt = _pass_type_for(insp, p, pass2_variant[i_idx])
                key = (room.id, pt, insp)
                if key not in new_slots:
                    new_slots[key] = SlotRef(
                        id=None,
                        room_id=room.id,
                        pass_type=pt,
                        inspiration=insp,
                        student_ids=[],
                        capacity=room.capacity,
                    )
                slot = new_slots[key]
                if sid not in slot.student_ids:
                    slot.student_ids.append(sid)
                s.placements.append((pt, insp))
                placed_count += 1
                _rebuild_student_placement_indexes(s)

    for (room_id, pt, insp), slot in new_slots.items():
        n = len(slot.student_ids)
        if 0 < n < cfg.min_session_size:
            diag.small_sessions.append((insp, pt, n))

    slots.extend(new_slots.values())

    _apply_cp_sat_post_placement(
        students, slots, rooms, suppressed=suppressed, cfg=cfg
    )

    diag.placed_required = sum(len(s.placements) for s in students)
    placements_before_reserve = diag.placed_required

    reserve_ids: set[int] = set()
    if cfg.try_reserve_for_unplaced:
        reserve_ids = _apply_reserve_fallback(
            students, slots, rooms, suppressed=suppressed, cfg=cfg
        )
        placed_count = sum(len(s.placements) for s in students)

    result = _build_auto_solve_result(
        students,
        slots,
        suppressed=suppressed,
        suppressed_list=suppressed_list,
        incomplete_count=len(incomplete),
        diag=diag,
        cfg=cfg,
        placed_count=placed_count,
        reserve_ids=reserve_ids,
        n_insp=n_insp,
        n_rooms=n_rooms,
    )
    if reserve_ids and placed_count > placements_before_reserve:
        result.summary += (
            f" Reserv: {len(reserve_ids)} elev(er) efter huvudlösning."
        )
    return students, slots, result, diag


def run_cp_sat_on_orm(
    students_orm,
    rooms_orm,
    slots_orm,
    *,
    min_students_threshold: int = 0,
    config: CpSatConfig | None = None,
) -> tuple[list[StudentRef], list[SlotRef], AutoSolveResult, CpSatDiagnostics]:
    students = [_load_student_from_orm(s) for s in students_orm]
    rooms = [RoomRef(r.id, r.name, r.capacity) for r in rooms_orm]
    slots: list[SlotRef] = []
    return solve_cp_sat(
        students,
        rooms,
        slots,
        min_students_threshold=min_students_threshold,
        config=config,
    )
