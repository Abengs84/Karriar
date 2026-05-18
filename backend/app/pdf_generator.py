from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.helpers import get_slot_for_pass, student_required_choices
from app.models import Student

EVENT_DATE = "Fredag 23.8.2026"
EVENT_PLACE = "Åbo Akademi, Vasa"
LUNCH_TEXT = "LUNCH, Restaurang Alexander"

PASS_LABELS = {
    "pass1": "11:00-11:30",
    "pass2a": "11:45-12:15",
    "pass2b": "12:30-13:00",
    "pass3": "13:15-13:45",
}

PAGE_W, PAGE_H = A4
MARGIN_X = 10 * mm
MARGIN_TOP = 12 * mm
MARGIN_BOTTOM = 12 * mm
GAP_V = 11 * mm
CARD_W = (PAGE_W - 3 * MARGIN_X) / 2
CARD_H = (PAGE_H - MARGIN_TOP - MARGIN_BOTTOM - GAP_V) / 2

ROW_FILL_ODD = colors.HexColor("#E8E8E8")
ROW_FILL_EVEN = colors.white
TEXT_FONT = "Helvetica"
TEXT_SIZE = 6.5
TIME_SIZE = 7
LINE_LEADING = 3.2 * mm
MIN_ROW_H = 7 * mm

_IMG_DIR = Path(__file__).resolve().parent.parent.parent / "img"
FOOTER_IMG = _IMG_DIR / "Vi7_bredd.png"
SILHOUETTE_IMG = _IMG_DIR / "karriar-yrken-silhuet_karriar.png"
FOOTER_GAP = 5 * mm
EVENT_ABOVE_TABLE = 1 * mm
SIL_ABOVE_EVENT = 2 * mm
FOOTER_SCALE = 0.648  # 0.72 × 0.9
# karriar-yrken-silhuet_karriar.png (1471×608, text baked as alpha cutout)
SILHOUETTE_ASPECT = 608 / 1471
SIL_TOP_OFFSET = 4 * mm
PAD_H = 4 * mm
PAD_TOP = 5 * mm
PAD_BOTTOM = 3 * mm


@dataclass
class ScheduleRow:
    time: str
    slot: Optional[object] = None
    text: Optional[str] = None


def _wrap_text(c: canvas.Canvas, text: str, max_w: float) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        if c.stringWidth(test, TEXT_FONT, TEXT_SIZE) <= max_w:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _inspiration_label(student: Student, inspiration: str) -> str:
    if (
        student.reserve
        and inspiration == student.reserve
        and inspiration not in student_required_choices(student)
    ):
        return f"{inspiration} (reserv)"
    return inspiration


def _content_lines(
    c: canvas.Canvas, row: ScheduleRow, max_w: float, student: Student | None = None
) -> list[str]:
    if row.slot:
        room = row.slot.room.name if row.slot.room else "?"
        inspiration = row.slot.inspiration or "—"
        if student:
            inspiration = _inspiration_label(student, inspiration)
        return _wrap_text(c, inspiration, max_w) + [room]
    text = row.text or "—"
    if c.stringWidth(text, TEXT_FONT, TEXT_SIZE) <= max_w:
        return [text]
    return _wrap_text(c, text, max_w)


def _build_schedule_rows(student: Student) -> list[ScheduleRow]:
    rows: list[ScheduleRow] = [
        ScheduleRow("10:00-10:45", text="ÖPPNING I AKADEMISALEN"),
    ]

    p1 = get_slot_for_pass(student, "pass1")
    rows.append(ScheduleRow("11:00-11:30", slot=p1))

    p2 = get_slot_for_pass(student, "pass2")
    p3 = get_slot_for_pass(student, "pass3")

    track = student.lunch_track
    if not track and p2:
        track = "2a" if p2.pass_type == "pass2a" else "2b"

    if track == "2b":
        rows.append(ScheduleRow("11:30-12:15", text=LUNCH_TEXT))
        rows.append(ScheduleRow(PASS_LABELS.get("pass2b", "12:30-13:00"), slot=p2))
    else:
        rows.append(ScheduleRow(PASS_LABELS.get("pass2a", "11:45-12:15"), slot=p2))
        rows.append(ScheduleRow("12:15-13:00", text=LUNCH_TEXT))

    rows.append(ScheduleRow("13:15-13:45", slot=p3))
    rows.append(ScheduleRow("14:00", text="HEMFÄRD"))
    return rows


def _table_height(
    c: canvas.Canvas,
    rows: list[ScheduleRow],
    max_text_w: float,
    student: Student | None = None,
) -> float:
    total = 0.0
    for row in rows:
        content = _content_lines(c, row, max_text_w, student)
        row_h = max(MIN_ROW_H, len(content) * LINE_LEADING + 2.5 * mm)
        total += row_h
    return total


def _draw_card(c: canvas.Canvas, student: Student, x: float, y: float):
    """Draw one schedule card; (x,y) is bottom-left of card."""
    c.saveState()

    content_w = CARD_W - 2 * PAD_H
    top = y + CARD_H - PAD_TOP
    time_w = 22 * mm
    text_x = x + PAD_H + time_w
    max_text_w = content_w - time_w - 2 * mm
    content_x = x + PAD_H

    rows = _build_schedule_rows(student)
    table_h = _table_height(c, rows, max_text_w, student)

    footer_h = 0.0
    if FOOTER_IMG.is_file():
        footer_h = content_w * (656 / 1943) * FOOTER_SCALE

    # Bottom-anchored: footer → table → date (tight) → silhouette fills top
    table_bottom = y + PAD_BOTTOM + footer_h + FOOTER_GAP
    table_top = table_bottom + table_h
    event_baseline = table_top + EVENT_ABOVE_TABLE

    c.setFont(TEXT_FONT, TIME_SIZE - 0.5)
    header = f"{student.school}, {student.first_name} {student.last_name}"
    c.drawRightString(x + CARD_W - PAD_H, top, header)

    sil_top = top - SIL_TOP_OFFSET
    sil_w = content_w
    sil_h_natural = sil_w * SILHOUETTE_ASPECT
    sil_bottom = event_baseline - SIL_ABOVE_EVENT
    sil_h = min(sil_h_natural, max(0.0, sil_top - sil_bottom))
    sil_y = sil_top - sil_h

    if SILHOUETTE_IMG.is_file():
        c.drawImage(
            str(SILHOUETTE_IMG),
            content_x,
            sil_y,
            width=sil_w,
            height=sil_h,
            preserveAspectRatio=True,
            anchor="sw",
            mask="auto",
        )

    c.setFont("Helvetica-Bold", 8)
    c.drawString(
        content_x,
        event_baseline,
        f"{EVENT_DATE.upper()}, {EVENT_PLACE.upper()}",
    )

    y_cursor = table_top

    for i, row in enumerate(rows):
        content = _content_lines(c, row, max_text_w, student)
        row_h = max(MIN_ROW_H, len(content) * LINE_LEADING + 2.5 * mm)
        y_cursor -= row_h
        ry = y_cursor

        fill = ROW_FILL_ODD if i % 2 == 1 else ROW_FILL_EVEN
        c.setFillColor(fill)
        c.rect(content_x, ry, content_w, row_h, stroke=0, fill=1)
        c.setFillColor(colors.black)

        c.setFont(TEXT_FONT, TIME_SIZE)
        c.drawString(content_x + 1 * mm, ry + row_h - LINE_LEADING - 0.5 * mm, row.time)

        c.setFont(TEXT_FONT, TEXT_SIZE)
        text_y = ry + row_h - LINE_LEADING - 0.5 * mm
        for line in content:
            c.drawString(text_x, text_y, line)
            text_y -= LINE_LEADING

    if FOOTER_IMG.is_file():
        c.drawImage(
            str(FOOTER_IMG),
            content_x,
            y + PAD_BOTTOM,
            width=content_w,
            height=footer_h,
            preserveAspectRatio=True,
            mask="auto",
        )

    c.restoreState()


def generate_school_pdf(students: list[Student]) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    sorted_students = sorted(students, key=lambda s: (s.last_name, s.first_name))
    per_page = 4

    for page_start in range(0, len(sorted_students), per_page):
        batch = sorted_students[page_start:page_start + per_page]
        top_row_y = MARGIN_BOTTOM + CARD_H + GAP_V
        positions = [
            (MARGIN_X, top_row_y),
            (MARGIN_X + CARD_W + MARGIN_X, top_row_y),
            (MARGIN_X, MARGIN_BOTTOM),
            (MARGIN_X + CARD_W + MARGIN_X, MARGIN_BOTTOM),
        ]
        for i, student in enumerate(batch):
            _draw_card(c, student, positions[i][0], positions[i][1])
        c.showPage()

    c.save()
    buf.seek(0)
    return buf.read()
