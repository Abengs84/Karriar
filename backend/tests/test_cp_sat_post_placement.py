"""In-memory test: saknat pass 3 för inspiratör med pass 1+2."""

from app.auto_placer import (
    RoomRef,
    SlotRef,
    StudentRef,
    _pending_needs,
    _rebuild_student_placement_indexes,
    run_post_placement_finalize,
)


def test_missing_pass3_filled_after_finalize():
    inspiration = "BRANDMAN - ANDERS NORDLUND"
    room = RoomRef(id=1, name="D302", capacity=18)
    students = [
        StudentRef(
            id=i,
            choice1=inspiration,
            choice2=f"INSP2-{i}",
            choice3=f"INSP3-{i}",
            reserve=None,
            lunch_track=None,
            placements=[("pass1", f"INSP2-{i}"), ("pass2a", f"INSP3-{i}")],
        )
        for i in range(1, 8)
    ]
    for s in students:
        _rebuild_student_placement_indexes(s)

    slots = [
        SlotRef(
            id=None,
            room_id=1,
            pass_type="pass1",
            inspiration=inspiration,
            student_ids=list(range(1, 16)),
            capacity=18,
        ),
        SlotRef(
            id=None,
            room_id=1,
            pass_type="pass2a",
            inspiration=inspiration,
            student_ids=list(range(1, 17)),
            capacity=18,
        ),
    ]
    rooms = [room]
    suppressed: set[str] = set()

    assert len(_pending_needs(students, suppressed)) == 7
    left = run_post_placement_finalize(
        students,
        slots,
        rooms,
        suppressed=suppressed,
        room_locks={inspiration: 1},
        exclusive_one_inspirator_per_room=True,
    )
    assert left == 0, f"expected 0 pending, got {left}"
    pass3 = [s for s in slots if s.pass_type == "pass3" and s.inspiration == inspiration]
    assert pass3, "pass3 slot should exist"
    assert all(s.has_inspirator(inspiration) for s in students)
