"""Markdown dosyalarindaki GORELI baglantilari ve gorsel yollarini denetler (kirik baglanti raporu).

Kullanim: python scripts/check_links.py [README.md docs ...]
"""

import re
import sys
from pathlib import Path

LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|!\[[^\]]*\]\(([^)\s]+)\)|<img[^>]+src=\"([^\"]+)\"")
targets = [Path(a) for a in sys.argv[1:]] or [Path("README.md"), Path("docs"), Path("BACKLOG.md"), Path("PLAN.md")]
files = []
for t in targets:
    files += sorted(t.rglob("*.md")) if t.is_dir() else [t]

broken = 0
checked = 0
for f in files:
    text = f.read_text(encoding="utf-8")
    for m in LINK.finditer(text):
        link = next(g for g in m.groups() if g)
        if re.match(r"^(https?:|mailto:|#)", link):
            continue
        path = link.split("#")[0]
        if not path:
            continue
        checked += 1
        if not (f.parent / path).exists():
            print(f"KIRIK: {f}: {link}")
            broken += 1
print(f"{checked} goreli baglanti denetlendi, {broken} kirik")
sys.exit(1 if broken else 0)
