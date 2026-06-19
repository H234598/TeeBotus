from __future__ import annotations

from pathlib import Path

from scripts import check_proactive_agent


def test_instance_dirs_selected_ignores_missing_instances(tmp_path: Path) -> None:
    instances_dir = tmp_path / "instances"
    (instances_dir / "existing").mkdir(parents=True)
    result = check_proactive_agent._instance_dirs(instances_dir, ["existing", "missing"])

    assert result == [instances_dir / "existing"]


def test_instance_dirs_selected_keeps_explicit_order(tmp_path: Path) -> None:
    instances_dir = tmp_path / "instances"
    (instances_dir / "second").mkdir(parents=True)
    (instances_dir / "first").mkdir(parents=True)
    result = check_proactive_agent._instance_dirs(instances_dir, ["second", "first"])

    assert result == [instances_dir / "second", instances_dir / "first"]
