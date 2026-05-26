"""PDF för schema-vyerna Översikt, Rum och Inspiratör."""

from __future__ import annotations

from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models import Room, SessionSlot
from app.schema_display import (
    inspirator_schedule_rows,
    inspirators_with_bookings,
    is_booked,
    overview_rows,
    pass2_label,
    rooms_with_bookings,
    slot_label,
)

MARGIN = 12 * mm
HEADER_DATE = date.today().strftime("%Y-%m-%d")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "SchemaTitle",
            parent=base["Heading1"],
            fontSize=16,
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "SchemaSubtitle",
            parent=base["Normal"],
            fontSize=9,
            textColor=colors.grey,
            spaceAfter=10,
        ),
        "section": ParagraphStyle(
            "SchemaSection",
            parent=base["Heading2"],
            fontSize=12,
            spaceAfter=6,
        ),
        "cell": ParagraphStyle(
            "SchemaCell",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
        ),
        "cellBold": ParagraphStyle(
            "SchemaCellBold",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            fontName="Helvetica-Bold",
        ),
        "roomHeader": ParagraphStyle(
            "SchemaRoomHeader",
            parent=base["Heading3"],
            fontSize=11,
            spaceAfter=2,
        ),
        "meta": ParagraphStyle(
            "SchemaMeta",
            parent=base["Normal"],
            fontSize=8,
            textColor=colors.grey,
            spaceAfter=6,
        ),
    }


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    safe = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return Paragraph(safe, style)


def _table_style(header_rows: int = 1) -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, header_rows - 1), colors.HexColor("#E8E8E8")),
            ("FONTNAME", (0, 0), (-1, header_rows - 1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
    )


def _doc_header(story: list, subtitle: str, styles: dict) -> None:
    story.append(_p("Karriär – Schema", styles["title"]))
    story.append(_p(f"{subtitle} · {HEADER_DATE}", styles["subtitle"]))


def generate_schema_overview_pdf(rooms: list[Room], slots: list[SessionSlot]) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )
    styles = _styles()
    story: list = []
    _doc_header(story, "Översikt alla rum", styles)
    story.append(_p("Översikt – rum och pass", styles["section"]))

    rows = overview_rows(rooms, slots)
    if not rows:
        story.append(_p("Inga bokade pass ännu.", styles["cell"]))
    else:
        table_data: list[list] = [
            [
                _p("Rum", styles["cellBold"]),
                _p("Pass 1<br/><font size='7'>11:00–11:30</font>", styles["cellBold"]),
                _p(
                    "Pass 2<br/><font size='7'>11:45–12:15 / 12:30–13:00</font>",
                    styles["cellBold"],
                ),
                _p("Pass 3<br/><font size='7'>13:15–13:45</font>", styles["cellBold"]),
            ]
        ]
        for room, pass1, pass3, pass2_booked in rows:
            pass2_parts: list[str] = []
            for block, slot in pass2_booked:
                pass2_parts.append(
                    f"<b>{slot.inspiration}</b><br/>"
                    f"{slot_label(slot, room.capacity)}<br/>"
                    f"<font size='6'>{pass2_label(block['variant'], block['time'])}</font>"
                )
            pass2_cell = "<br/><br/>".join(pass2_parts) if pass2_parts else ""

            table_data.append(
                [
                    _p(
                        f"<b>{room.name}</b><br/>"
                        f"<font size='7'>{room.capacity} platser</font>",
                        styles["cell"],
                    ),
                    _p(
                        (
                            f"<b>{pass1.inspiration}</b><br/>"
                            f"{slot_label(pass1, room.capacity)}"
                        )
                        if is_booked(pass1)
                        else "",
                        styles["cell"],
                    ),
                    _p(pass2_cell, styles["cell"]),
                    _p(
                        (
                            f"<b>{pass3.inspiration}</b><br/>"
                            f"{slot_label(pass3, room.capacity)}"
                        )
                        if is_booked(pass3)
                        else "",
                        styles["cell"],
                    ),
                ]
            )

        col_widths = [55 * mm, 70 * mm, 85 * mm, 70 * mm]
        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(_table_style())
        story.append(table)

    doc.build(story)
    return buf.getvalue()


def _room_pass_lines(room: Room, room_slots: list[SessionSlot], styles: dict) -> list:
    from app.schema_display import pass2_blocks_for_display

    by_pass = {s.pass_type: s for s in room_slots}
    lines: list = []

    pass1 = by_pass.get("pass1")
    if is_booked(pass1):
        lines.append(
            _p(
                f"<b>Pass 1 · 11:00–11:30</b><br/>"
                f"{pass1.inspiration}<br/>{slot_label(pass1, room.capacity)}",
                styles["cell"],
            )
        )
    else:
        lines.append(_p("<b>Pass 1 · 11:00–11:30</b><br/>Ingen bokning", styles["cell"]))

    for block in pass2_blocks_for_display(room_slots):
        slot = by_pass.get(block["pass_type"])
        label = pass2_label(block["variant"], block["time"])
        if is_booked(slot):
            lines.append(
                _p(
                    f"<b>{label}</b><br/>"
                    f"{slot.inspiration}<br/>{slot_label(slot, room.capacity)}",
                    styles["cell"],
                )
            )
        else:
            lines.append(_p(f"<b>{label}</b><br/>Ingen bokning", styles["cell"]))

    pass3 = by_pass.get("pass3")
    if is_booked(pass3):
        lines.append(
            _p(
                f"<b>Pass 3 · 13:15–13:45</b><br/>"
                f"{pass3.inspiration}<br/>{slot_label(pass3, room.capacity)}",
                styles["cell"],
            )
        )
    else:
        lines.append(_p("<b>Pass 3 · 13:15–13:45</b><br/>Ingen bokning", styles["cell"]))

    return lines


def generate_schema_rooms_pdf(rooms: list[Room], slots: list[SessionSlot]) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )
    styles = _styles()
    story: list = []

    room_list = rooms_with_bookings(rooms, slots)
    if not room_list:
        _doc_header(story, "Bokningar per rum", styles)
        story.append(_p("Inga bokade pass ännu.", styles["cell"]))
        doc.build(story)
        return buf.getvalue()

    for i, (room, room_slots) in enumerate(room_list):
        if i > 0:
            story.append(PageBreak())
        _doc_header(story, "Bokningar per rum", styles)
        story.append(_p("Bokningar per rum", styles["section"]))
        story.append(_p(f"<b>{room.name}</b>", styles["roomHeader"]))
        story.append(_p(f"{room.capacity} platser", styles["meta"]))
        for line in _room_pass_lines(room, room_slots, styles):
            story.append(line)
            story.append(Spacer(1, 4))

    doc.build(story)
    return buf.getvalue()


def generate_schema_inspirators_pdf(slots: list[SessionSlot]) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )
    styles = _styles()
    story: list = []

    insp_list = inspirators_with_bookings(slots)
    if not insp_list:
        _doc_header(story, "Schema per inspiratör", styles)
        story.append(_p("Inga bokade pass ännu.", styles["cell"]))
        doc.build(story)
        return buf.getvalue()

    for i, (name, insp_slots) in enumerate(insp_list):
        if i > 0:
            story.append(PageBreak())
        _doc_header(story, "Schema per inspiratör", styles)
        story.append(_p("Schema per inspiratör", styles["section"]))
        booked = sum(1 for s in insp_slots if is_booked(s))
        booked_label = "1 bokat pass" if booked == 1 else f"{booked} bokade pass"
        story.append(_p(f"<b>{name}</b>", styles["roomHeader"]))
        story.append(_p(booked_label, styles["meta"]))

        by_pass = {s.pass_type: s for s in insp_slots}
        for row in inspirator_schedule_rows(insp_slots):
            if row.kind == "lunch":
                story.append(
                    _p(
                        f"<b>{row.label}</b><br/>Restaurang Alexander",
                        styles["cell"],
                    )
                )
            else:
                slot = by_pass.get(row.pass_type or "")
                if is_booked(slot):
                    cap = slot.room.capacity if slot.room else 0
                    story.append(
                        _p(
                            f"<b>{row.label}</b><br/>"
                            f"{slot.room.name if slot.room else '?'}<br/>"
                            f"{slot_label(slot, cap)}",
                            styles["cell"],
                        )
                    )
            story.append(Spacer(1, 4))

    doc.build(story)
    return buf.getvalue()
