"""Analysera elevval, rumskapacitet och flaskhalsar. Kör i Docker:

  docker exec karrir-karriar-1 python /app/backend/scripts/analyze_capacity.py
"""

from __future__ import annotations

import os
import sqlite3
from collections import Counter, defaultdict

DB = os.getenv("DATABASE_URL", "sqlite:///./data/karriar.db").replace(
    "sqlite:///", ""
)
if not DB.startswith("/"):
    DB = f"/app/{DB}" if os.path.exists(f"/app/{DB}") else DB


def main() -> None:
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    tables = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    if "students" not in tables:
        print("Ingen elevdata i DB (tabeller:", tables, ")")
        return

    rooms = c.execute(
        "SELECT id, name, capacity FROM rooms ORDER BY capacity DESC"
    ).fetchall()
    n_students = c.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    rows = c.execute(
        "SELECT choice1, choice2, choice3, reserve FROM students"
    ).fetchall()

    demand: Counter[str] = Counter()
    for ch1, ch2, ch3, _res in rows:
        seen: set[str] = set()
        for insp in (ch1, ch2, ch3):
            if insp and insp not in seen:
                demand[insp] += 1
                seen.add(insp)

    ranked = demand.most_common()
    total_cap = sum(r[2] for r in rooms)
    max_cap = max((r[2] for r in rooms), default=0)

    print(f"Elever: {n_students}")
    print(f"Rum: {len(rooms)}, kapacitet per tidspass (summa): {total_cap}")
    print(f"Största sal: {max_cap} platser")
    print(f"Inspiratörer med minst ett val 1–3: {len(demand)}")
    print(f"Totalt val 1–3 (unika per elev/inspiratör): {sum(demand.values())}")
    print(f"Teoretiskt behov placeringar (3 per elev): {n_students * 3}")
    print()

    overflow = len(demand) - len(rooms)
    if overflow > 0:
        print(
            f"⚠ Fler inspiratörer ({len(demand)}) än rum ({len(rooms)}): "
            f"{overflow} måste dela rum (hybrid) eller vänta."
        )
    print()

    print("Topp 15 efterfrågan (antal elever som valt inspiratören):")
    for insp, n in ranked[:15]:
        need_passes = (n + max_cap - 1) // max_cap if max_cap else "?"
        print(f"  {n:3d}  (minst ~{need_passes} fulla pass i största sal)  {insp[:55]}")

    print()
    print("Minst 10 efterfrågan (hybrid-delar rum):")
    for insp, n in ranked[-10:]:
        print(f"  {n:3d}  {insp[:55]}")

    # Per-tid kapacitet vs behov
    print()
    print("Kapacitet per tidspass om alla rum används:")
    for label in ("pass1", "pass2 (2a+2b)", "pass3"):
        print(f"  {label}: max {total_cap} platser, behov {n_students} elever")
    if total_cap < n_students:
        shortfall = n_students - total_cap
        print(
            f"  ⚠ Summa rum räcker inte per tid – minst {shortfall} elever "
            "kan inte få pass samtidigt."
        )

    # DB placement state
    if "placements" in tables:
        pl_by_st: dict[int, set[str]] = defaultdict(set)
        for sid, pt in c.execute(
            """
            SELECT p.student_id, ss.pass_type
            FROM placements p
            JOIN session_slots ss ON ss.id = p.session_slot_id
            """
        ).fetchall():
            key = "pass2" if pt in ("pass2a", "pass2b") else pt
            pl_by_st[sid].add(key)
        # recount properly
        all_ids = [r[0] for r in c.execute("SELECT id FROM students").fetchall()]
        missing_n = sum(1 for sid in all_ids if len(pl_by_st.get(sid, set())) < 3)
        print()
        print(f"Nuvarande DB: {missing_n} elever saknar minst ett tidspass (1/2/3)")

    conn.close()


if __name__ == "__main__":
    main()
