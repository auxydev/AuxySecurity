"""Basit AST taramasi: modulde iceri aktarilip hic kullanilmayan adlari listeler (ruff F401 benzeri).

Kullanim: python scripts/unused_imports.py [kok=src]
"""

import ast
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "src")
found = 0
for path in sorted(root.rglob("*.py")):
    if path.name == "__init__.py":
        continue
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported[(a.asname or a.name).split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            for a in node.names:
                imported[a.asname or a.name] = node.lineno
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    text = path.read_text(encoding="utf-8")
    for name, line in imported.items():
        if name not in used and f'"{name}"' not in text.replace(f"import {name}", ""):
            print(f"{path}:{line}: kullanilmayan import '{name}'")
            found += 1
print(f"{found} kullanilmayan import")
