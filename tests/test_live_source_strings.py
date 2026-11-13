"""Guard user-facing live Python strings against lost text."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEAD_UI_DIRS = {"pages", "windows", "widgets", "components"}


def test_live_python_string_literals_have_no_double_question_marks():
    paths = [ROOT / "run_ui.py", ROOT / "api_server.py"]
    for path in (ROOT / "src").rglob("*.py"):
        parts = path.relative_to(ROOT / "src").parts
        if len(parts) >= 3 and parts[0] == "ui" and parts[1] in DEAD_UI_DIRS:
            continue
        paths.append(path)
    marker = "?" * 2
    bad = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and marker in node.value:
                bad.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.value!r}")
    assert not bad, "Damaged string literals:\n" + "\n".join(bad)
