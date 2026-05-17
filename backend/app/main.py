import os
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db, init_db
from app.helpers import (
    collect_all_inspirations,
    has_placement_at_pass,
    is_placed_with_inspirator,
    schedule_pass_key,
    student_chose,
)
from app.auto_placer import (
    RoomRef,
    StudentRef,
    apply_solution_to_db,
    run_on_orm,
    solve_auto_placement,
)
from app.import_excel import import_students_from_excel
from app.models import Placement, Room, SessionSlot, Student
from app.pdf_generator import generate_school_pdf
from app.schemas import (
    AutoSolveOut,
    AutoSolveRequest,
    BulkPlaceRequest,
    PlaceAtCellRequest,
    ImportResult,
    UnplacedNeedOut,
    InspiratorStat,
    LunchTrackUpdate,
    PlacementOut,
    RoomCreate,
    RoomOut,
    RoomUpdate,
    SessionSlotCreate,
    SessionSlotOut,
    SetStudentPassRequest,
    StudentOut,
)

app = FastAPI(title="Karriär")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


def _slot_out(slot: SessionSlot) -> SessionSlotOut:
    return SessionSlotOut(
        id=slot.id,
        room_id=slot.room_id,
        pass_type=slot.pass_type,
        inspiration=slot.inspiration,
        room_name=slot.room.name,
        room_capacity=slot.room.capacity,
        placed_count=len(slot.placements),
    )


def _student_out(s: Student) -> StudentOut:
    placements = []
    for p in s.placements:
        placements.append(
            PlacementOut(
                id=p.id,
                session_slot_id=p.session_slot_id,
                inspiration=p.session_slot.inspiration if p.session_slot else None,
                pass_type=p.session_slot.pass_type if p.session_slot else None,
                room_name=(
                    p.session_slot.room.name
                    if p.session_slot and p.session_slot.room
                    else None
                ),
            )
        )
    return StudentOut(
        id=s.id,
        first_name=s.first_name,
        last_name=s.last_name,
        school=s.school,
        choice1=s.choice1,
        choice2=s.choice2,
        choice3=s.choice3,
        reserve=s.reserve,
        lunch_track=s.lunch_track,
        placements=placements,
    )


# --- Rooms ---
@app.get("/api/rooms", response_model=list[RoomOut])
def list_rooms(db: Session = Depends(get_db)):
    return db.query(Room).order_by(Room.name).all()


@app.post("/api/rooms", response_model=RoomOut)
def create_room(data: RoomCreate, db: Session = Depends(get_db)):
    room = Room(name=data.name, capacity=data.capacity)
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


@app.patch("/api/rooms/{room_id}", response_model=RoomOut)
def update_room(room_id: int, data: RoomUpdate, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(404, "Rummet hittades inte")
    if data.name is not None:
        room.name = data.name
    if data.capacity is not None:
        room.capacity = data.capacity
    db.commit()
    db.refresh(room)
    return room


@app.delete("/api/rooms/{room_id}")
def delete_room(room_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(404, "Rummet hittades inte")
    slots = db.query(SessionSlot).filter(SessionSlot.room_id == room_id).count()
    if slots:
        raise HTTPException(400, "Rummet har sessioner – ta bort dem först")
    db.delete(room)
    db.commit()
    return {"ok": True}


# --- Session slots ---
@app.get("/api/session-slots", response_model=list[SessionSlotOut])
def list_session_slots(pass_type: str | None = None, db: Session = Depends(get_db)):
    q = db.query(SessionSlot).options(
        joinedload(SessionSlot.room),
        joinedload(SessionSlot.placements),
    )
    if pass_type:
        q = q.filter(SessionSlot.pass_type == pass_type)
    slots = q.order_by(SessionSlot.inspiration, SessionSlot.pass_type).all()
    return [_slot_out(s) for s in slots]


@app.post("/api/session-slots", response_model=SessionSlotOut)
def create_session_slot(data: SessionSlotCreate, db: Session = Depends(get_db)):
    if data.pass_type not in ("pass1", "pass2a", "pass2b", "pass3"):
        raise HTTPException(400, "Ogiltig passtyp")
    room = db.query(Room).filter(Room.id == data.room_id).first()
    if not room:
        raise HTTPException(404, "Rummet hittades inte")
    slot = SessionSlot(
        room_id=data.room_id,
        pass_type=data.pass_type,
        inspiration=data.inspiration,
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    slot.room = room
    return _slot_out(slot)


@app.delete("/api/session-slots/{slot_id}")
def delete_session_slot(slot_id: int, db: Session = Depends(get_db)):
    slot = (
        db.query(SessionSlot)
        .options(joinedload(SessionSlot.placements))
        .filter(SessionSlot.id == slot_id)
        .first()
    )
    if not slot:
        raise HTTPException(404, "Sessionen hittades inte")
    was_pass2 = slot.pass_type in ("pass2a", "pass2b")
    student_ids = [p.student_id for p in slot.placements]
    db.delete(slot)
    db.commit()
    if was_pass2:
        for sid in student_ids:
            _clear_lunch_if_no_pass2(db, sid)
        db.commit()
    return {"ok": True, "removed_placements": len(student_ids)}


# --- Students ---
@app.get("/api/students", response_model=list[StudentOut])
def list_students(school: str | None = None, db: Session = Depends(get_db)):
    q = (
        db.query(Student)
        .options(
            joinedload(Student.placements)
            .joinedload(Placement.session_slot)
            .joinedload(SessionSlot.room)
        )
        .order_by(Student.school, Student.last_name, Student.first_name)
    )
    if school:
        q = q.filter(Student.school == school)
    return [_student_out(s) for s in q.all()]


@app.get("/api/schools")
def list_schools(db: Session = Depends(get_db)):
    rows = (
        db.query(Student.school, func.count(Student.id))
        .group_by(Student.school)
        .order_by(Student.school)
    )
    return [{"school": r[0], "count": r[1]} for r in rows.all()]


@app.patch("/api/students/{student_id}/lunch-track")
def update_lunch_track(
    student_id: int, data: LunchTrackUpdate, db: Session = Depends(get_db)
):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(404, "Eleven hittades inte")
    if data.lunch_track is not None and data.lunch_track not in ("2a", "2b"):
        raise HTTPException(400, "lunch_track måste vara 2a, 2b eller null")
    student.lunch_track = data.lunch_track
    db.commit()
    return {"ok": True}


# --- Import ---
@app.post("/api/import/excel", response_model=ImportResult)
async def import_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Ladda upp en Excel-fil (.xlsx)")
    content = await file.read()
    imported, skipped = import_students_from_excel(db, content)
    total = db.query(Student).count()
    return ImportResult(
        imported=imported,
        skipped_duplicates=skipped,
        total_students=total,
    )


# --- Stats ---
@app.get("/api/stats/inspirators", response_model=list[InspiratorStat])
def inspirator_stats(db: Session = Depends(get_db)):
    students = (
        db.query(Student)
        .options(
            joinedload(Student.placements).joinedload(Placement.session_slot)
        )
        .all()
    )
    inspirations = collect_all_inspirations(students)
    result = []

    for inspiration in sorted(inspirations):
        chose = [s for s in students if student_chose(s, inspiration)]
        placed = [s for s in chose if is_placed_with_inspirator(s, inspiration)]
        count = len(chose)
        placed_n = len(placed)
        result.append(
            InspiratorStat(
                inspiration=inspiration,
                count=count,
                placed=placed_n,
                unplaced=count - placed_n,
            )
        )

    result.sort(key=lambda x: (-x.count, x.inspiration))
    return result


def _place_students_in_slot(
    db: Session,
    slot: SessionSlot,
    student_ids: list[int],
) -> dict:
    current = len(slot.placements)
    remaining = slot.room.capacity - current
    if remaining <= 0:
        raise HTTPException(400, f"Rummet är fullt ({slot.room.capacity} platser)")

    to_place = student_ids[:remaining]
    skipped = len(student_ids) - len(to_place)
    inspiration = slot.inspiration
    placed = 0
    skip_already_at_pass = 0
    skip_already_with_inspirator = 0
    skip_not_chose = 0

    for sid in to_place:
        student = (
            db.query(Student)
            .options(joinedload(Student.placements).joinedload(Placement.session_slot))
            .filter(Student.id == sid)
            .first()
        )
        if not student:
            continue
        if not student_chose(student, inspiration):
            skip_not_chose += 1
            continue
        if is_placed_with_inspirator(student, inspiration):
            skip_already_with_inspirator += 1
            continue
        if has_placement_at_pass(student, slot.pass_type):
            skip_already_at_pass += 1
            continue

        db.add(Placement(student_id=sid, session_slot_id=slot.id))

        if slot.pass_type in ("pass2a", "pass2b"):
            student.lunch_track = "2a" if slot.pass_type == "pass2a" else "2b"
        placed += 1

    skipped_ineligible = (
        skip_already_at_pass
        + skip_already_with_inspirator
        + skip_not_chose
    )
    return {
        "placed": placed,
        "skipped_capacity": skipped,
        "skipped_ineligible": skipped_ineligible,
        "skip_already_at_pass": skip_already_at_pass,
        "skip_already_with_inspirator": skip_already_with_inspirator,
        "skip_not_chose": skip_not_chose,
    }


# --- Placements ---
@app.post("/api/placements/at-cell")
def place_at_cell(data: PlaceAtCellRequest, db: Session = Depends(get_db)):
    if data.pass_type not in ("pass1", "pass2a", "pass2b", "pass3"):
        raise HTTPException(400, "Ogiltig passtyp")
    room = db.query(Room).filter(Room.id == data.room_id).first()
    if not room:
        raise HTTPException(404, "Rummet hittades inte")

    slot = (
        db.query(SessionSlot)
        .options(joinedload(SessionSlot.room), joinedload(SessionSlot.placements))
        .filter(
            SessionSlot.room_id == data.room_id,
            SessionSlot.pass_type == data.pass_type,
        )
        .first()
    )

    if slot and slot.inspiration != data.inspiration:
        raise HTTPException(
            400,
            (
                f"Rummet har redan «{slot.inspiration}» detta pass. "
                "Välj annat rum eller pass."
            ),
        )

    if not slot:
        slot = SessionSlot(
            room_id=data.room_id,
            pass_type=data.pass_type,
            inspiration=data.inspiration,
        )
        db.add(slot)
        db.flush()
        slot.room = room

    result = _place_students_in_slot(db, slot, data.student_ids)
    db.flush()
    if result["placed"] == 0:
        db.delete(slot)
    db.commit()
    return result


@app.post("/api/placements/bulk")
def bulk_place(data: BulkPlaceRequest, db: Session = Depends(get_db)):
    slot = (
        db.query(SessionSlot)
        .options(joinedload(SessionSlot.room), joinedload(SessionSlot.placements))
        .filter(SessionSlot.id == data.session_slot_id)
        .first()
    )
    if not slot:
        raise HTTPException(404, "Sessionen hittades inte")

    result = _place_students_in_slot(db, slot, data.student_ids)
    db.commit()
    return result


def _clear_lunch_if_no_pass2(db: Session, student_id: int):
    student = (
        db.query(Student)
        .options(joinedload(Student.placements).joinedload(Placement.session_slot))
        .filter(Student.id == student_id)
        .first()
    )
    if student and not has_placement_at_pass(student, "pass2a"):
        student.lunch_track = None


PASS_SCHEDULE = frozenset({"pass1", "pass2", "pass3"})


@app.put("/api/placements/student-pass")
def set_student_pass(data: SetStudentPassRequest, db: Session = Depends(get_db)):
    if data.pass_type not in PASS_SCHEDULE:
        raise HTTPException(400, "pass_type måste vara pass1, pass2 eller pass3")

    student = (
        db.query(Student)
        .options(joinedload(Student.placements).joinedload(Placement.session_slot))
        .filter(Student.id == data.student_id)
        .first()
    )
    if not student:
        raise HTTPException(404, "Eleven hittades inte")

    target_key = "pass2" if data.pass_type == "pass2" else data.pass_type
    removed_pass2 = False
    for p in list(student.placements):
        slot = p.session_slot
        if not slot:
            continue
        if schedule_pass_key(slot.pass_type) == target_key:
            if slot.pass_type in ("pass2a", "pass2b"):
                removed_pass2 = True
            db.delete(p)

    if data.session_slot_id is not None:
        slot = (
            db.query(SessionSlot)
            .options(joinedload(SessionSlot.room), joinedload(SessionSlot.placements))
            .filter(SessionSlot.id == data.session_slot_id)
            .first()
        )
        if not slot:
            raise HTTPException(404, "Sessionen hittades inte")
        if schedule_pass_key(slot.pass_type) != target_key:
            raise HTTPException(400, "Sessionen matchar inte det valda passet")
        if len(slot.placements) >= slot.room.capacity:
            raise HTTPException(400, f"Rummet är fullt ({slot.room.capacity} platser)")
        if not student_chose(student, slot.inspiration):
            raise HTTPException(400, "Eleven har inte valt denna inspiratör")
        db.add(Placement(student_id=student.id, session_slot_id=slot.id))
        if slot.pass_type in ("pass2a", "pass2b"):
            student.lunch_track = "2a" if slot.pass_type == "pass2a" else "2b"

    db.commit()
    if removed_pass2 or data.pass_type == "pass2":
        _clear_lunch_if_no_pass2(db, student.id)
        db.commit()

    student = (
        db.query(Student)
        .options(
            joinedload(Student.placements)
            .joinedload(Placement.session_slot)
            .joinedload(SessionSlot.room)
        )
        .filter(Student.id == data.student_id)
        .first()
    )
    return _student_out(student)


@app.post("/api/placements/auto-solve", response_model=AutoSolveOut)
def auto_solve(data: AutoSolveRequest, db: Session = Depends(get_db)):
    if data.mode not in ("fill", "replace"):
        raise HTTPException(400, "mode måste vara fill eller replace")

    rooms_orm = db.query(Room).order_by(Room.name).all()
    if not rooms_orm:
        raise HTTPException(400, "Skapa minst ett rum innan automatisk placering.")

    if data.mode == "replace" and not data.dry_run:
        db.query(Placement).delete()
        db.query(SessionSlot).delete()
        db.commit()

    students_orm = (
        db.query(Student)
        .options(
            joinedload(Student.placements)
            .joinedload(Placement.session_slot)
            .joinedload(SessionSlot.room)
        )
        .all()
    )
    slots_orm = (
        db.query(SessionSlot)
        .options(
            joinedload(SessionSlot.room),
            joinedload(SessionSlot.placements),
        )
        .all()
    )

    if data.mode == "replace" and data.dry_run:
        students = [
            StudentRef(
                id=s.id,
                choice1=s.choice1,
                choice2=s.choice2,
                choice3=s.choice3,
                reserve=s.reserve,
                lunch_track=None,
                placements=[],
            )
            for s in students_orm
        ]
        rooms = [RoomRef(r.id, r.name, r.capacity) for r in rooms_orm]
        slots: list = []
        result = solve_auto_placement(students, rooms, slots)
    else:
        students, slots, result = run_on_orm(students_orm, rooms_orm, slots_orm)

    if not data.dry_run:
        apply_solution_to_db(db, students_orm, slots)
        db.commit()

    sample = [
        UnplacedNeedOut(
            student_id=n.student_id,
            inspiration=n.inspiration,
            choice_field=n.field,
            rank=n.rank,
        )
        for n in result.unplaced_needs[:80]
    ]

    return AutoSolveOut(
        placed_new=result.placed_new,
        slots_created=result.slots_created,
        unplaced_count=len(result.unplaced_needs),
        unplaced_sample=sample,
        score=result.score,
        by_choice_field=result.by_choice_field,
        summary=result.summary,
        dry_run=data.dry_run,
    )


@app.delete("/api/placements/{placement_id}")
def remove_placement(placement_id: int, db: Session = Depends(get_db)):
    p = (
        db.query(Placement)
        .options(joinedload(Placement.session_slot))
        .filter(Placement.id == placement_id)
        .first()
    )
    if not p:
        raise HTTPException(404, "Placeringen hittades inte")
    student_id = p.student_id
    was_pass2 = p.session_slot and p.session_slot.pass_type in ("pass2a", "pass2b")
    db.delete(p)
    db.commit()
    if was_pass2:
        _clear_lunch_if_no_pass2(db, student_id)
        db.commit()
    return {"ok": True}


# --- PDF ---
@app.get("/api/pdf/school/{school_name}")
def pdf_for_school(school_name: str, db: Session = Depends(get_db)):
    students = (
        db.query(Student)
        .options(
            joinedload(Student.placements)
            .joinedload(Placement.session_slot)
            .joinedload(SessionSlot.room)
        )
        .filter(Student.school == school_name)
        .all()
    )
    if not students:
        raise HTTPException(404, "Inga elever för denna skola")
    pdf_bytes = generate_school_pdf(students)
    safe_name = school_name.replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="karriar_{safe_name}.pdf"'
        },
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve frontend in Docker / production
_frontend = Path(
    os.getenv(
        "FRONTEND_DIR",
        Path(__file__).resolve().parents[2] / "frontend" / "dist",
    )
)
if _frontend.is_dir():
    app.mount("/assets", StaticFiles(directory=_frontend / "assets"), name="assets")

    @app.get("/")
    def spa_index():
        return FileResponse(
            _frontend / "index.html",
            media_type="text/html; charset=utf-8",
        )

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path.startswith("api"):
            raise HTTPException(404)
        if full_path:
            candidate = (_frontend / full_path).resolve()
            try:
                candidate.relative_to(_frontend.resolve())
            except ValueError:
                raise HTTPException(404) from None
            if candidate.is_file():
                return FileResponse(candidate)
        index = _frontend / "index.html"
        if index.is_file():
            return FileResponse(index, media_type="text/html; charset=utf-8")
        raise HTTPException(404)
