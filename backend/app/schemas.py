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
    min_students_threshold: int = 0


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


class LunchRebalanceRequest(BaseModel):
    dry_run: bool = True


class LunchRebalanceMoveOut(BaseModel):
    kind: str
    session_slot_id: int
    session_slot_id_b: int | None = None
    inspiration: str
    inspiration_b: str | None = None
    room_name: str
    from_track: str
    to_track: str
    student_count: int
    student_count_b: int = 0
    net_delta: int


class LunchRebalanceOut(BaseModel):
    dry_run: bool
    lunch_2a_before: int
    lunch_2b_before: int
    lunch_2a_after: int
    lunch_2b_after: int
    moves: list[LunchRebalanceMoveOut]
    summary: str
    applied: bool = False
    blocked_reason: str | None = None


class SetStudentPassRequest(BaseModel):
    student_id: int
    pass_type: str  # pass1 | pass2 | pass3 (pass2 = pass2a eller pass2b)
    session_slot_id: int | None = None  # None = ta bort placering på passet


class InspiratorRoomLockOut(BaseModel):
    inspiration: str
    room_id: int
    room_name: str


class InspiratorRoomLocksOut(BaseModel):
    locks: list[InspiratorRoomLockOut]
    count: int


class InspiratorRoomLocksSetResult(BaseModel):
    count: int


class AutoSolveRequest(BaseModel):
    mode: str = "fill"  # fill | replace
    solver: str = "heuristic"  # heuristic | cp_sat
    dry_run: bool = True
    min_session_size: int = Field(default=5, ge=1, le=500)
    min_students_threshold: int = Field(default=0, ge=0, le=500)
    try_reserve_for_unplaced: bool = False
    balance_lunch_tracks: bool = False
    consolidate_small_groups: bool = True
    same_room_per_inspirator: bool = False
    hybrid_room_when_short: bool = False
    prioritize_high_demand: bool = True
    place_unplaced_pass2_share: bool = False


class UnplacedNeedOut(BaseModel):
    student_id: int
    student_name: str
    inspiration: str
    choice_field: str
    rank: int


class PreviewInspiratorStatusOut(BaseModel):
    inspiration: str
    placed: int
    unplaced: int
    capacity: int


class AutoSolveOut(BaseModel):
    placed_new: int
    slots_created: int
    unplaced_count: int
    missing_pass_count: int = 0
    unplaced_student_count: int = 0
    unplaced_sample: list[UnplacedNeedOut]
    score: int
    by_choice_field: dict[str, int]
    summary: str
    dry_run: bool
    suppressed_inspirators: list[str] = []
    lunch_2a: int = 0
    lunch_2b: int = 0
    rooms_relocated: int = 0
    reserve_placed_count: int = 0
    preview_slots: list[SessionSlotOut] | None = None
    preview_inspirator_status: list[PreviewInspiratorStatusOut] | None = None
    # Vid dry_run: oplacerade i nuvarande databas (Placering-fliken före Verkställ).
    db_unplaced_student_count: int | None = None
