from dataclasses import dataclass
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.helpers import get_slot_for_pass
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
MARGIN = 10 * mm
CARD_W = (PAGE_W - 3 * MARGIN) / 2
CARD_H = (PAGE_H - 3 * MARGIN) / 2

ROW_FILL_ODD = colors.HexColor("#E8E8E8")
ROW_FILL_EVEN = colors.white
TEXT_FONT = "Helvetica"
TEXT_SIZE = 6.5
TIME_SIZE = 7
LINE_LEADING = 3.2 * mm
MIN_ROW_H = 7 * mm


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


def _content_lines(c: canvas.Canvas, row: ScheduleRow, max_w: float) -> list[str]:
    if row.slot:
        room = row.slot.room.name if row.slot.room else "?"
        inspiration = row.slot.inspiration or "—"
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


def _draw_card(c: canvas.Canvas, student: Student, x: float, y: float):
    """Draw one schedule card; (x,y) is bottom-left of card."""
    c.saveState()

    pad = 4 * mm
    top = y + CARD_H - pad
    time_w = 22 * mm
    text_x = x + pad + time_w
    max_text_w = CARD_W - 2 * pad - time_w - 2 * mm

    c.setFont(TEXT_FONT, TIME_SIZE - 0.5)
    header = f"{student.school}, {student.first_name} {student.last_name}"
    c.drawRightString(x + CARD_W - pad, top, header)

    c.setFont("Helvetica-Bold", 22)
    c.drawString(x + pad, top - 10 * mm, "KARRIÄR")

    c.setFont(TEXT_FONT, 8)
    c.drawString(x + pad, top - 16 * mm, f"{EVENT_DATE.upper()}, {EVENT_PLACE.upper()}")

    table_top = top - 22 * mm
    rows = _build_schedule_rows(student)
    y_cursor = table_top

    for i, row in enumerate(rows):
        content = _content_lines(c, row, max_text_w)
        row_h = max(MIN_ROW_H, len(content) * LINE_LEADING + 2.5 * mm)
        y_cursor -= row_h
        ry = y_cursor

        fill = ROW_FILL_ODD if i % 2 == 1 else ROW_FILL_EVEN
        c.setFillColor(fill)
        c.rect(x + pad, ry, CARD_W - 2 * pad, row_h, stroke=0, fill=1)
        c.setFillColor(colors.black)

        c.setFont(TEXT_FONT, TIME_SIZE)
        c.drawString(x + pad + 1 * mm, ry + row_h - LINE_LEADING - 0.5 * mm, row.time)

        c.setFont(TEXT_FONT, TEXT_SIZE)
        text_y = ry + row_h - LINE_LEADING - 0.5 * mm
        for line in content:
            c.drawString(text_x, text_y, line)
            text_y -= LINE_LEADING

    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(colors.HexColor("#8B2252"))
    c.drawString(x + pad, y + 3 * mm, "Vi7")
    c.setFillColor(colors.black)
    c.setFont(TEXT_FONT, 6)
    c.drawString(x + pad + 10 * mm, y + 3.5 * mm, "GYMNASIER I SAMARBETE")

    c.restoreState()


def generate_school_pdf(students: list[Student]) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    sorted_students = sorted(students, key=lambda s: (s.last_name, s.first_name))
    per_page = 4

    for page_start in range(0, len(sorted_students), per_page):
        batch = sorted_students[page_start:page_start + per_page]
        positions = [
            (MARGIN, PAGE_H / 2 + MARGIN / 2),
            (MARGIN + CARD_W + MARGIN, PAGE_H / 2 + MARGIN / 2),
            (MARGIN, MARGIN),
            (MARGIN + CARD_W + MARGIN, MARGIN),
        ]
        for i, student in enumerate(batch):
            _draw_card(c, student, positions[i][0], positions[i][1])
        c.showPage()

    c.save()
    buf.seek(0)
    return buf.read()
