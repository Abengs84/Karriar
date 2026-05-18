from pydantic import BaseModel, Field


class RoomCreate(BaseModel):
    name: str
    capacity: int = Field(ge=1, le=500)


class RoomUpdate(BaseModel):
    name: str | None = None
    capacity: int | None = Field(default=None, ge=1, le=500)


class RoomOut(BaseModel):
    id: int
    name: str
    capacity: int

    model_config = {"from_attributes": True}


class SessionSlotCreate(BaseModel):
    room_id: int
    pass_type: str
    inspiration: str


class SessionSlotOut(BaseModel):
    id: int
    room_id: int
    pass_type: str
    inspiration: str
    room_name: str
    room_capacity: int
    placed_count: int

    model_config = {"from_attributes": True}


class StudentOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    school: str
    choice1: str | None
    choice2: str | None
    choice3: str | None
    reserve: str | None
    lunch_track: str | None
    placements: list["PlacementOut"] = []

    model_config = {"from_attributes": True}


class PlacementOut(BaseModel):
    id: int
    session_slot_id: int
    inspiration: str | None = None
    pass_type: str | None = None
    room_name: str | None = None

    model_config = {"from_attributes": True}


class BulkPlaceRequest(BaseModel):
    student_ids: list[int]
    session_slot_id: int


class PlaceAtCellRequest(BaseModel):
    student_ids: list[int]
    room_id: int
    pass_type: str
    inspiration: str


class InspiratorStat(BaseModel):
    inspiration: str
    count: int
    placed: int
    unplaced: int
    pass_count: int


class RetentionStatus(BaseModel):
    enabled: bool
    purge_at: str | None = None
    seconds_remaining: int | None = None
    retention_hours: int = 3


class ImportResult(BaseModel):
    imported: int
    skipped_duplicates: int
    total_students: int
    retention: RetentionStatus


class ClearStudentsResult(BaseModel):
    ok: bool
    removed_placements: int
    removed_students: int
    removed_session_slots: int


class LunchTrackUpdate(BaseModel):
    lunch_track: str | None  # "2a" | "2b" | null


class SetStudentPassRequest(BaseModel):
    student_id: int
    pass_type: str  # pass1 | pass2 | pass3 (pass2 = pass2a eller pass2b)
    session_slot_id: int | None = None  # None = ta bort placering på passet


class AutoSolveRequest(BaseModel):
    mode: str = "fill"  # fill | replace
    dry_run: bool = True
    minimize_sessions_per_inspirator: bool = False
    min_students_threshold: int = Field(default=0, ge=0, le=500)


class UnplacedNeedOut(BaseModel):
    student_id: int
    inspiration: str
    choice_field: str
    rank: int


class AutoSolveOut(BaseModel):
    placed_new: int
    slots_created: int
    unplaced_count: int
    unplaced_sample: list[UnplacedNeedOut]
    score: int
    by_choice_field: dict[str, int]
    summary: str
    dry_run: bool
    suppressed_inspirators: list[str] = []
