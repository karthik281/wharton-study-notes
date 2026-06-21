"""Swap the top two FNCE sections so order is 06/12 (S5) then 06/11 (S4)."""
import re
from pathlib import Path

p = Path(r"C:\Users\raoka\Documents\WEMBA\Term 4\FNCE 7310 (51 Global) - Summer 2026\FNCE 7310 - Notes.md")
text = p.read_text(encoding="utf-8")
matches = list(re.finditer(r"<!-- session: (.+?) -->", text))
sections = []
for i, m in enumerate(matches):
    start = m.start()
    end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
    sections.append((m.group(1), text[start:end]))

names = [s[0] for s in sections]
print("before:", names)
# swap first two only if they are the swapped June pair
if names[0].startswith("06/11") and names[1].startswith("06/12"):
    sections[0], sections[1] = sections[1], sections[0]
    new_text = "".join(s[1] for s in sections)
    p.write_text(new_text, encoding="utf-8")
    print("after: ", [s[0] for s in sections])
    print("reordered.")
else:
    print("no change needed.")
