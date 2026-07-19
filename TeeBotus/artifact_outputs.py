from __future__ import annotations

import os
from pathlib import Path


DEFAULT_OBSIDIAN_VAULT_DIR = (
    Path.home()
    / "Dokumente"
    / "Obsidian_Vaults"
    / "Teladi_Programming"
)


def _default_incoming_dir() -> Path:
    configured = os.environ.get("TEEBOTUS_OBSIDIAN_INCOMING_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_OBSIDIAN_VAULT_DIR / "incomming"


DEFAULT_OBSIDIAN_INCOMING_DIR = _default_incoming_dir()


def obsidian_incoming_path(*parts: str) -> Path:
    return DEFAULT_OBSIDIAN_INCOMING_DIR.joinpath(*parts)


def legacy_import_preflight_path(artifact_name: str, *, ext: str) -> Path:
    return obsidian_incoming_path(f"teebotus-legacy-import-preflight-{artifact_name}{ext}")
