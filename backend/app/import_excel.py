from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.models import Student


def _cell(row, idx: int) -> str | None:
    val = row[idx] if idx < len(row) else None
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def import_students_from_excel(db: Session, file_bytes: bytes) -> tuple[int, int]:
    from io import BytesIO

    wb = load_workbook(BytesIO(file_bytes), data_only=True, read_only=True)
    ws = wb.active

    imported = 0
    skipped = 0
    rows = ws.iter_rows(values_only=True)

    first = next(rows, None)
    if first is None:
        return 0, 0

    # Skip header if column B looks like a label
    header_labels = ("förnamn", "fornamn", "firstname", "etunimi")
    if first[1] and str(first[1]).lower() in header_labels:
        pass
    else:
        rows = iter([first, *rows])

    existing_keys = {
        (s.first_name.lower(), s.last_name.lower(), s.school.lower())
        for s in db.query(Student).all()
    }

    for row in rows:
        if not row or len(row) < 4:
            continue
        first_name = _cell(row, 1)
        last_name = _cell(row, 2)
        school = _cell(row, 3)
        if not first_name or not last_name or not school:
            continue

        key = (first_name.lower(), last_name.lower(), school.lower())
        if key in existing_keys:
            skipped += 1
            continue

        student = Student(
            first_name=first_name,
            last_name=last_name,
            school=school,
            choice1=_cell(row, 4),
            choice2=_cell(row, 5),
            choice3=_cell(row, 6),
            reserve=_cell(row, 7),
        )
        db.add(student)
        existing_keys.add(key)
        imported += 1

    db.commit()
    wb.close()
    return imported, skipped
