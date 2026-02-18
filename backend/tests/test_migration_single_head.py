from __future__ import annotations

import ast
from pathlib import Path


def _read_revision_and_down_revisions(path: Path) -> tuple[str | None, set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    revision: str | None = None
    down_revisions: set[str] = set()

    for node in tree.body:
        target_name: str | None = None
        value_node: ast.AST | None = None

        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                target_name = target.id
                value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value_node = node.value

        if target_name not in {"revision", "down_revision"} or value_node is None:
            continue

        value = ast.literal_eval(value_node)
        if target_name == "revision":
            if isinstance(value, str):
                revision = value
            continue

        if value is None:
            continue
        if isinstance(value, str):
            down_revisions.add(value)
            continue
        if isinstance(value, (list, tuple, set)):
            down_revisions.update(item for item in value if isinstance(item, str))

    return revision, down_revisions


def test_alembic_has_single_head() -> None:
    revisions: set[str] = set()
    referenced_revisions: set[str] = set()

    for path in Path("alembic/versions").glob("*.py"):
        revision, down_revisions = _read_revision_and_down_revisions(path)
        if revision is None:
            continue
        revisions.add(revision)
        referenced_revisions.update(down_revisions)

    heads = sorted(revisions - referenced_revisions)
    assert len(heads) == 1, f"Expected exactly one Alembic head, got: {heads}"
