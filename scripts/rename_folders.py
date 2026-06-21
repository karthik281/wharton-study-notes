"""One-off: rename existing course + session folders to the standard convention.

Subject folder:  <SHORT> <CODE> - <Course Name>
Session folder:  <NN> <ddMonyy> - <Class Name>
Leaves notes files, .bak files, and the 'Async Modules' folder untouched.
"""
import re
from pathlib import Path

ROOT = Path(r"C:\Users\raoka\Documents\WEMBA\Term 4")
MONTHS = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
          7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}

COURSES = {
    "FNCE 7310 (51 Global) - Summer 2026": "FNCE 7310 - Global Valuation & Risk Analysis",
    "OIDD 6360 (51 Global) - Summer 2026": "OIDD 6360 - Scaling Operations",
    "OIDD-MGMT 6910 & LGST 8060 (51 Global) - Summer 2026": "OIDD-MGMT 6910 & LGST 8060 - Negotiations",
}

# Class-name overrides for sessions that were created with generic placeholder names.
OVERRIDES = {
    "04 110626 FNCE Session 4": "Jaguar Case & Hedging Transaction Exposure",
    "05 120626 FNCE Session 5": "Managing FX Risk",
    "05 130626 Negotiation Session 5": "Multi-Issue Negotiation & CMO Debrief",
}

SESSION_RE = re.compile(r"^(\d+)\s+(\d{2})(\d{2})(\d{2})\s+(.*)$")


def new_session_name(old: str) -> str | None:
    m = SESSION_RE.match(old)
    if not m:
        return None
    num, dd, mm, yy, rest = m.groups()
    rest = OVERRIDES.get(old, rest)
    return f"{num} {dd}{MONTHS[int(mm)]}{yy} - {rest}"


for old_course, new_course in COURSES.items():
    cdir = ROOT / old_course
    if not cdir.exists():
        print(f"MISSING course dir: {old_course}")
        continue
    # 1. rename session subfolders first (parent path still old)
    for sub in sorted(cdir.iterdir()):
        if not sub.is_dir():
            continue
        nn = new_session_name(sub.name)
        if nn and nn != sub.name:
            sub.rename(sub.with_name(nn))
            print(f"  session: {sub.name}  ->  {nn}")
        elif not nn:
            print(f"  (left): {sub.name}")
    # 2. rename the course folder
    cdir.rename(cdir.with_name(new_course))
    print(f"COURSE:  {old_course}  ->  {new_course}\n")

print("done")
