import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    cookie_secure,
    create_session_token,
    get_password,
    is_authenticated,
    verify_password,
)
from app.database import SessionLocal, get_db, init_db
from app.helpers import (
    purge_empty_session_slots,
    purge_invalid_placements,
    suppressed_inspirations,
    collect_all_inspirations,
    has_placement_at_pass,
    inspirator_pass2_variant_locked,
    is_placed_with_inspirator,
    schedule_pass_key,
    schedule_pass_keys_from_types,
    count_unique_unplaced_students,
    effective_required_choices_list,
    student_chose,
    student_chose_for_placement,
    student_chose_required,
    student_has_full_schedule,
    would_conflict_inspirator_pass2,
    would_exceed_inspirator_pass_limit,
)
from app.auto_placer import (
    RoomRef,
    SlotRef,
    StudentRef,
    _compute_suppressed,
    apply_solution_to_db,
    run_on_orm,
    solve_auto_placement,
)
from app.fi_ip import finland_only_enabled, is_request_from_finland, load_fi_networks
from app.import_excel import import_students_from_excel
from app.models import Placement, Room, SessionSlot, Student
from app.retention import (
    check_and_purge_if_due,
    purge_student_data,
    retention_status,
    retention_worker,
    schedule_purge_after_import,
)
from app.pdf_generator import generate_school_pdf
from app.inspirator_room_locks import (
    clear_room_locks,
    list_room_locks,
    lock_all_inspirators_to_current_rooms,
)
from app.schemas import (
    AutoSolveOut,
    AutoSolveRequest,
    PreviewInspiratorStatusOut,
    BulkPlaceRequest,
    PlaceAtCellRequest,
    ClearStudentsResult,
    ImportResult,
    RetentionStatus,
    UnplacedNeedOut,
    InspiratorRoomLockOut,
    InspiratorRoomLocksOut,
    InspiratorRoomLocksSetResult,
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

PUBLIC_API_PATHS = frozenset({
    "/api/health",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/status",
})

GEO_EXEMPT_PATHS = frozenset({"/api/health"})

_GEO_FORBIDDEN_MSG = "Åtkomst tillåten endast från finska IP-adresser."


def _geo_forbidden_response(request: Request) -> Response:
    if "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(
            status_code=403,
            content=(
                "<!DOCTYPE html><html lang=sv><meta charset=utf-8>"
                f"<title>403</title><p>{_GEO_FORBIDDEN_MSG}</p></html>"
            ),
        )
    return JSONResponse(status_code=403, content={"detail": _GEO_FORBIDDEN_MSG})


class FinlandIpMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not finland_only_enabled():
            return await call_next(request)
        path = request.url.path
        if path in GEO_EXEMPT_PATHS:
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)
        if not is_request_from_finland(request):
            return _geo_forbidden_response(request)
        return await call_next(request)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        if path.startswith("/api/") and path not in PUBLIC_API_PATHS:
            if not is_authenticated(request):
                return JSONResponse(status_code=401, content={"detail": "Ej inloggad"})
        return await call_next(request)


app.add_middleware(AuthMiddleware)
app.add_middleware(FinlandIpMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginBody(BaseModel):
    password: str


@app.on_event("startup")
async def startup():
    get_password()
    load_fi_networks()
    init_db()
    db = SessionLocal()
    try:
        check_and_purge_if_due(db)
    finally:
        db.close()
    asyncio.create_task(retention_worker())


@app.post("/api/auth/login")
def auth_login(body: LoginBody, response: Response):
    if not verify_password(body.password):
        raise HTTPException(status_code=401, detail="Fel lösenord")
    token = create_session_token()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
        max_age=SESSION_MAX_AGE,
        path="/",
    )
    return {"ok": True}


@app.post("/api/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/status")
def auth_status(request: Request):
    return {"authenticated": is_authenticated(request)}


@app.get("/api/retention", response_model=RetentionStatus)
def get_retention(db: Session = Depends(get_db)):
    return RetentionStatus(**retention_status(db))


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


@app.get("/api/gdpr/export")
def gdpr_export(db: Session = Depends(get_db)):
    """Registerutdrag / dataportabilitet (GDPR art. 15 och 20)."""
    students = (
        db.query(Student)
        .options(
            joinedload(Student.placements)
            .joinedload(Placement.session_slot)
            .joinedload(SessionSlot.room)
        )
        .order_by(Student.school, Student.last_name, Student.first_name)
        .all()
    )
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Karriär-evenemanget – placering och scheman",
        "student_count": len(students),
        "students": [_student_out(s).model_dump() for s in students],
    }


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


@app.get("/api/inspirator-room-locks", response_model=InspiratorRoomLocksOut)
def get_inspirator_room_locks(db: Session = Depends(get_db)):
    rows = list_room_locks(db)
    locks = [InspiratorRoomLockOut(**r) for r in rows]
    return InspiratorRoomLocksOut(locks=locks, count=len(locks))


@app.post(
    "/api/inspirator-room-locks/from-current",
    response_model=InspiratorRoomLocksSetResult,
)
def lock_inspirators_to_current_rooms(db: Session = Depends(get_db)):
    """Lås varje inspiratör till rummet med flest elever i nuvarande schema."""
    count = lock_all_inspirators_to_current_rooms(db)
    db.commit()
    return InspiratorRoomLocksSetResult(count=count)


@app.delete("/api/inspirator-room-locks", response_model=InspiratorRoomLocksSetResult)
def delete_inspirator_room_locks(db: Session = Depends(get_db)):
    count = clear_room_locks(db)
    db.commit()
    return InspiratorRoomLocksSetResult(count=count)


def _inspirator_pass_types(
    db: Session, inspiration: str, *, exclude_slot_id: int | None = None
) -> list[str]:
    q = db.query(SessionSlot.pass_type).filter(
        SessionSlot.inspiration == inspiration
    )
    if exclude_slot_id is not None:
        q = q.filter(SessionSlot.id != exclude_slot_id)
    return [row[0] for row in q.all()]


def _global_pass2_placement_counts(db: Session) -> tuple[int, int]:
    n2a = (
        db.query(Placement)
        .join(SessionSlot)
        .filter(SessionSlot.pass_type == "pass2a")
        .count()
    )
    n2b = (
        db.query(Placement)
        .join(SessionSlot)
        .filter(SessionSlot.pass_type == "pass2b")
        .count()
    )
    return n2a, n2b


def _resolve_inspirator_pass2_placement(db: Session, inspiration: str) -> str:
    """Välj pass2a eller pass2b för inspiratör (låst om redan satt)."""
    pass_types = _inspirator_pass_types(db, inspiration)
    locked = inspirator_pass2_variant_locked(pass_types)
    if locked:
        return locked
    n2a, n2b = _global_pass2_placement_counts(db)
    return "pass2a" if n2a <= n2b else "pass2b"


def _ensure_inspirator_not_double_booked(
    db: Session,
    inspiration: str,
    pass_type: str,
    room_id: int,
    *,
    exclude_slot_id: int | None = None,
) -> None:
    q = (
        db.query(SessionSlot)
        .options(joinedload(SessionSlot.room))
        .filter(
            SessionSlot.inspiration == inspiration,
            SessionSlot.pass_type == pass_type,
            SessionSlot.room_id != room_id,
        )
    )
    if exclude_slot_id is not None:
        q = q.filter(SessionSlot.id != exclude_slot_id)
    other = q.first()
    if other:
        room_name = other.room.name if other.room else f"rum {other.room_id}"
        raise HTTPException(
            400,
            (
                f"«{inspiration}» har redan ett pass i {room_name} denna tid. "
                "En inspiratör kan bara vara på ett ställe åt gången."
            ),
        )


def _ensure_inspirator_pass_allowed(
    db: Session,
    inspiration: str,
    pass_type: str,
    *,
    exclude_slot_id: int | None = None,
) -> None:
    pass_types = _inspirator_pass_types(
        db, inspiration, exclude_slot_id=exclude_slot_id
    )
    keys = schedule_pass_keys_from_types(pass_types)
    if would_exceed_inspirator_pass_limit(keys, pass_type):
        raise HTTPException(
            400,
            (
                f"«{inspiration}» har redan tre tidspass (pass 1, pass 2 och pass 3). "
                "Välj ett annat tidspass."
            ),
        )
    if would_conflict_inspirator_pass2(pass_types, pass_type):
        locked = inspirator_pass2_variant_locked(pass_types)
        track = "2a" if locked == "pass2a" else "2b"
        raise HTTPException(
            400,
            (
                f"«{inspiration}» har redan pass {track}. "
                "En inspiratör kan bara ligga på antingen 2a eller 2b, inte båda."
            ),
        )


# --- Session slots ---
@app.get("/api/session-slots", response_model=list[SessionSlotOut])
def list_session_slots(pass_type: str | None = None, db: Session = Depends(get_db)):
    purge_invalid_placements(db)
    purge_empty_session_slots(db)
    db.commit()
    db.commit()
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
    if data.pass_type not in ("pass1", "pass2", "pass2a", "pass2b", "pass3"):
        raise HTTPException(400, "Ogiltig passtyp")
    pass_type = data.pass_type
    if pass_type == "pass2":
        pass_type = _resolve_inspirator_pass2_placement(db, data.inspiration)
    room = db.query(Room).filter(Room.id == data.room_id).first()
    if not room:
        raise HTTPException(404, "Rummet hittades inte")
    _ensure_inspirator_not_double_booked(
        db, data.inspiration, pass_type, data.room_id
    )
    _ensure_inspirator_pass_allowed(db, data.inspiration, pass_type)
    slot = SessionSlot(
        room_id=data.room_id,
        pass_type=pass_type,
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


@app.delete("/api/students", response_model=ClearStudentsResult)
def clear_all_students(db: Session = Depends(get_db)):
    result = purge_student_data(db)
    return ClearStudentsResult(**result)


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
    schedule_purge_after_import(db)
    total = db.query(Student).count()
    return ImportResult(
        imported=imported,
        skipped_duplicates=skipped,
        total_students=total,
        retention=RetentionStatus(**retention_status(db)),
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
    pass_types_by_insp: dict[str, list[str]] = {}
    for inspiration, pass_type in (
        db.query(SessionSlot.inspiration, SessionSlot.pass_type)
        .join(Placement, Placement.session_slot_id == SessionSlot.id)
        .distinct()
        .all()
    ):
        pass_types_by_insp.setdefault(inspiration, []).append(pass_type)
    result = []

    for inspiration in sorted(inspirations):
        required = [s for s in students if student_chose_required(s, inspiration)]
        placed_n = sum(
            1 for s in required if is_placed_with_inspirator(s, inspiration)
        )
        unplaced_n = sum(
            1
            for s in required
            if not is_placed_with_inspirator(s, inspiration)
            and not student_has_full_schedule(s)
        )
        result.append(
            InspiratorStat(
                inspiration=inspiration,
                count=len(required),
                placed=placed_n,
                unplaced=unplaced_n,
                pass_count=len(
                    schedule_pass_keys_from_types(
                        pass_types_by_insp.get(inspiration, [])
                    )
                ),
            )
        )

    result.sort(key=lambda x: (-x.count, x.inspiration))
    return result


def _place_students_in_slot(
    db: Session,
    slot: SessionSlot,
    student_ids: list[int],
    *,
    expected_inspiration: str | None = None,
    min_students_threshold: int = 0,
) -> dict:
    inspiration = expected_inspiration or slot.inspiration
    if slot.inspiration != inspiration:
        raise HTTPException(
            400,
            f"Rutan har inspiratör «{slot.inspiration}», inte «{inspiration}».",
        )

    current = len(slot.placements)
    remaining = slot.room.capacity - current
    if remaining <= 0:
        raise HTTPException(400, f"Rummet är fullt ({slot.room.capacity} platser)")

    to_place = student_ids[:remaining]
    skipped = len(student_ids) - len(to_place)
    placed = 0
    skip_already_at_pass = 0
    skip_already_with_inspirator = 0
    skip_not_chose = 0

    suppressed: set[str] = set()
    if min_students_threshold > 0:
        all_students = db.query(Student).all()
        suppressed = suppressed_inspirations(all_students, min_students_threshold)

    for sid in to_place:
        student = (
            db.query(Student)
            .options(joinedload(Student.placements).joinedload(Placement.session_slot))
            .filter(Student.id == sid)
            .first()
        )
        if not student:
            continue
        if not student_chose_for_placement(
            student, inspiration, suppressed=suppressed or None
        ):
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
    if data.pass_type not in ("pass1", "pass2", "pass2a", "pass2b", "pass3"):
        raise HTTPException(400, "Ogiltig passtyp")
    pass_type = data.pass_type
    if pass_type == "pass2":
        pass_type = _resolve_inspirator_pass2_placement(db, data.inspiration)
    room = db.query(Room).filter(Room.id == data.room_id).first()
    if not room:
        raise HTTPException(404, "Rummet hittades inte")

    slot = (
        db.query(SessionSlot)
        .options(joinedload(SessionSlot.room), joinedload(SessionSlot.placements))
        .filter(
            SessionSlot.room_id == data.room_id,
            SessionSlot.pass_type == pass_type,
        )
        .first()
    )

    if slot and slot.inspiration != data.inspiration:
        if len(slot.placements) == 0:
            _ensure_inspirator_not_double_booked(
                db,
                data.inspiration,
                pass_type,
                data.room_id,
                exclude_slot_id=slot.id,
            )
            _ensure_inspirator_pass_allowed(
                db,
                data.inspiration,
                pass_type,
                exclude_slot_id=slot.id,
            )
            slot.inspiration = data.inspiration
        else:
            raise HTTPException(
                400,
                (
                    f"Rummet har redan «{slot.inspiration}» detta pass. "
                    "Välj annat rum eller pass."
                ),
            )

    if not slot:
        _ensure_inspirator_not_double_booked(
            db, data.inspiration, pass_type, data.room_id
        )
        _ensure_inspirator_pass_allowed(db, data.inspiration, pass_type)
        slot = SessionSlot(
            room_id=data.room_id,
            pass_type=pass_type,
            inspiration=data.inspiration,
        )
        db.add(slot)
        db.flush()
        slot.room = room
    else:
        _ensure_inspirator_not_double_booked(
            db, data.inspiration, pass_type, data.room_id, exclude_slot_id=slot.id
        )

    result = _place_students_in_slot(
        db,
        slot,
        data.student_ids,
        expected_inspiration=data.inspiration,
        min_students_threshold=data.min_students_threshold,
    )
    db.flush()
    purge_invalid_placements(db)
    if result["placed"] == 0 and len(slot.placements) == 0:
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
            raise HTTPException(
                400, "Eleven har inte valt denna inspiratör i val 1–3 eller reserv"
            )
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


def _ref_placed_with_inspirator(student: StudentRef, inspiration: str) -> bool:
    return inspiration in student.placement_inspirations


def _ref_has_full_schedule(student: StudentRef) -> bool:
    return len(student.placement_pass_keys) >= 3


def _ref_unplaced_for_inspirator(
    student: StudentRef, inspiration: str, suppressed: set[str]
) -> bool:
    if not student_chose_for_placement(student, inspiration, suppressed=suppressed):
        return False
    if _ref_placed_with_inspirator(student, inspiration):
        return False
    if _ref_has_full_schedule(student):
        return False
    return True


def _preview_slots_out(slots: list[SlotRef], rooms_orm: list[Room]) -> list[SessionSlotOut]:
    room_by_id = {r.id: r for r in rooms_orm}
    out: list[SessionSlotOut] = []
    temp_id = -1
    for sl in slots:
        if not sl.student_ids:
            continue
        room = room_by_id.get(sl.room_id)
        if not room:
            continue
        slot_id = sl.id if sl.id is not None else temp_id
        if sl.id is None:
            temp_id -= 1
        out.append(
            SessionSlotOut(
                id=slot_id,
                room_id=sl.room_id,
                pass_type=sl.pass_type,
                inspiration=sl.inspiration,
                room_name=room.name,
                room_capacity=sl.capacity or room.capacity,
                placed_count=len(sl.student_ids),
            )
        )
    return out


def _preview_inspirator_status(
    students: list[StudentRef],
    slots: list[SlotRef],
    min_students_threshold: int,
) -> list[PreviewInspiratorStatusOut]:
    suppressed = _compute_suppressed(students, min_students_threshold)
    inspirations: set[str] = set()
    for s in students:
        for insp in effective_required_choices_list(s, suppressed):
            inspirations.add(insp)
    for sl in slots:
        if sl.student_ids:
            inspirations.add(sl.inspiration)

    rows: list[PreviewInspiratorStatusOut] = []
    for inspiration in sorted(inspirations):
        required = sum(
            1
            for s in students
            if student_chose_for_placement(s, inspiration, suppressed=suppressed)
        )
        placed = sum(
            1 for s in students if _ref_placed_with_inspirator(s, inspiration)
        )
        unplaced = sum(
            1
            for s in students
            if _ref_unplaced_for_inspirator(s, inspiration, suppressed)
        )
        capacity = sum(sl.capacity for sl in slots if sl.inspiration == inspiration)
        rows.append(
            PreviewInspiratorStatusOut(
                inspiration=inspiration,
                placed=placed,
                unplaced=unplaced,
                capacity=capacity,
            )
        )
    return rows


def _patch_auto_solve_summary_students(summary: str, student_count: int) -> str:
    """Ersätt elevräkning i sammanfattningen med siffra som matchar Placering-vyn."""
    import re

    if student_count <= 0:
        return re.sub(
            r" \d+ elever saknar fortfarande ett tidspass\.",
            "",
            summary,
        )
    phrase = (
        " 1 elev saknar fortfarande pass enligt schemat "
        "(samma som oplacerade grupper)."
        if student_count == 1
        else (
            f" {student_count} elever saknar fortfarande pass enligt schemat "
            "(samma som oplacerade grupper)."
        )
    )
    if re.search(r" elever saknar fortfarande ett tidspass\.", summary):
        return re.sub(
            r" \d+ elever saknar fortfarande ett tidspass\.",
            phrase,
            summary,
            count=1,
        )
    if re.search(r" 1 elev saknar fortfarande ett tidspass", summary):
        return re.sub(
            r" 1 elev saknar fortfarande ett tidspass[^.]*\.",
            phrase,
            summary,
            count=1,
        )
    return summary + phrase


@app.post("/api/placements/auto-solve", response_model=AutoSolveOut)
def auto_solve(data: AutoSolveRequest, db: Session = Depends(get_db)):
    if data.mode not in ("fill", "replace"):
        raise HTTPException(400, "mode måste vara fill eller replace")

    rooms_orm = db.query(Room).order_by(Room.name).all()
    if not rooms_orm:
        raise HTTPException(400, "Skapa minst ett rum innan automatisk placering.")

    exclusive_rooms = data.same_room_per_inspirator
    room_locks = None

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
        slots = []
        result = solve_auto_placement(
            students,
            rooms,
            slots,
            min_students_threshold=data.min_students_threshold,
            try_reserve_for_unplaced=data.try_reserve_for_unplaced,
            balance_lunch_tracks=data.balance_lunch_tracks,
            consolidate_small_groups=data.consolidate_small_groups,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_rooms,
            prioritize_high_demand=data.prioritize_high_demand,
        )
    else:
        students, slots, result = run_on_orm(
            students_orm,
            rooms_orm,
            slots_orm,
            min_students_threshold=data.min_students_threshold,
            try_reserve_for_unplaced=data.try_reserve_for_unplaced,
            balance_lunch_tracks=data.balance_lunch_tracks,
            consolidate_small_groups=data.consolidate_small_groups,
            room_locks=room_locks,
            exclusive_one_inspirator_per_room=exclusive_rooms,
            prioritize_high_demand=data.prioritize_high_demand,
        )

    if not data.dry_run:
        apply_solution_to_db(db, students_orm, slots)
        purge_invalid_placements(db)
        purge_empty_session_slots(db)
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
        board_unplaced_students = count_unique_unplaced_students(
            students_orm, data.min_students_threshold
        )
    else:
        # Förhandsgranskning: visa utfallet efter simulering (samma som efter Verkställ).
        board_unplaced_students = result.unplaced_student_count

    student_by_id = {s.id: s for s in students_orm}
    sample = [
        UnplacedNeedOut(
            student_id=n.student_id,
            student_name=(
                f"{s.first_name} {s.last_name}"
                if (s := student_by_id.get(n.student_id))
                else str(n.student_id)
            ),
            inspiration=n.inspiration,
            choice_field=n.field,
            rank=n.rank,
        )
        for n in result.unplaced_needs[:80]
    ]

    preview_slots = None
    preview_inspirator_status = None
    if data.dry_run:
        preview_slots = _preview_slots_out(slots, rooms_orm)
        preview_inspirator_status = _preview_inspirator_status(
            students, slots, data.min_students_threshold
        )

    return AutoSolveOut(
        placed_new=result.placed_new,
        slots_created=result.slots_created,
        unplaced_count=len(result.unplaced_needs),
        missing_pass_count=board_unplaced_students,
        unplaced_student_count=board_unplaced_students,
        unplaced_sample=sample,
        score=result.score,
        by_choice_field=result.by_choice_field,
        summary=_patch_auto_solve_summary_students(
            result.summary, board_unplaced_students
        ),
        dry_run=data.dry_run,
        suppressed_inspirators=result.suppressed_inspirators,
        lunch_2a=result.lunch_2a,
        lunch_2b=result.lunch_2b,
        rooms_relocated=result.rooms_relocated,
        reserve_placed_count=result.reserve_placed_count,
        preview_slots=preview_slots,
        preview_inspirator_status=preview_inspirator_status,
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
