from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.models import Student


def _cell(row, idx: int) -> str | None:
    val = row[idx] if idx < len(row) else None
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _capitalize_name_part(part: str) -> str:
    """Ett ord eller bindestrecksdelat namn: 'cajsa' / 'anna-maria' -> 'Cajsa' / 'Anna-Maria'."""
    return "-".join(p.capitalize() for p in part.split("-"))


def capitalize_person_name(name: str) -> str:
    """För- eller efternamn: 'cajsa maris' -> 'Cajsa Maris'."""
    return " ".join(_capitalize_name_part(part) for part in name.split())


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

    # Skip header if column B or C looks like a name label
    name_header_labels = (
        "förnamn", "fornamn", "firstname", "etunimi",
        "efternamn", "efternamn", "lastname", "sukunimi",
    )
    col_b = str(first[1]).lower().strip() if first[1] else ""
    col_c = str(first[2]).lower().strip() if len(first) > 2 and first[2] else ""
    if col_b in name_header_labels or col_c in name_header_labels:
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
        last_name = _cell(row, 1)
        first_name = _cell(row, 2)
        school = _cell(row, 3)
        if not first_name or not last_name or not school:
            continue

        first_name = capitalize_person_name(first_name)
        last_name = capitalize_person_name(last_name)

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
