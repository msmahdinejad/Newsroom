"""Guard: no active runtime path uses eval() or imports removed V1 modules."""

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def _python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_no_eval_in_active_src():
    """No src/ file contains eval()."""
    offenders = []
    for p in _python_files(SRC):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            offenders.append(str(p))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "eval":
                offenders.append(f"{p}:{node.lineno}")
    assert not offenders, f"eval() found in active src: {offenders}"


def test_removed_v1_modules_not_importable():
    """Removed V1 modules must not resolve as newsroom submodules."""
    for mod in ("newsroom.editorial.hermes", "newsroom.digest.preview", "newsroom.delivery.bot_commands"):
        # ensure not present on path
        assert mod not in sys.modules, f"{mod} unexpectedly imported"
    # files physically absent from src tree
    for rel in ("editorial/hermes.py", "digest/preview.py", "delivery/bot_commands.py"):
        assert not (SRC / "newsroom" / rel).exists(), f"V1 file still in src: {rel}"
def test_no_v1_imports_in_active_code():
    """No active src/ file imports the V1 legacy symbols."""
    bad = []
    for p in _python_files(SRC):
        text = p.read_text(encoding="utf-8")
        for needle in ("digest.preview", "editorial.hermes", "delivery.bot_commands", "PreviewGenerator", "HermesEditorial"):
            if needle in text:
                bad.append(f"{p}: {needle}")
    assert not bad, f"V1 references in active code: {bad}"
