from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None

SUPPORTED_EXPORT_FORMATS = {"pdf", "csv", "cls", "yaml", "json", "txt", "md", "tex", "latex"}
SECRET_FIELD_NAMES = {"account_secret", "secret", "secret_verifier", "verifier", "instance_pepper", "openai_api_key"}
ENCRYPTED_EXPORT_MAGICS = {"TMBMAP1", "TMBMEM1", "TMBKEY1"}
SECRET_FIELD_FRAGMENTS = ("secret", "token", "api_key", "apikey", "passphrase", "pepper", "verifier", "password")
SECRET_FIELD_ALLOWLIST = {"account_id", "linked_identities", "identity_key"}


class ExportError(RuntimeError):
    pass


class ExportVault(Protocol):
    def read_json(self, path: Path, default: dict[str, Any]) -> dict[str, Any]: ...
    def read_jsonl(self, path: Path) -> list[dict[str, Any]]: ...
    def read_text(self, path: Path, default: str = "") -> str: ...


@dataclass(frozen=True)
class ExportResult:
    filename: str
    content_type: str
    data: bytes
    degraded: bool = False
    note: str = ""


def export_account_data(account_id: str, account_dir: Path, fmt: str, *, vault: ExportVault | None = None) -> ExportResult:
    payload = _collect_account_payload(account_id, Path(account_dir), vault=vault)
    return _emit_payload(account_id, payload, fmt)


def _emit_payload(account_id: str, payload: dict[str, Any], fmt: str) -> ExportResult:
    normalized_format = _normalize_format(fmt)
    export_id = _safe_export_slug(account_id)
    if normalized_format == "json":
        data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        return ExportResult(f"TeeBotus_account_{export_id}.json", "application/json", data)
    if normalized_format == "yaml":
        if yaml is not None:
            data = yaml.safe_dump(payload, allow_unicode=True, sort_keys=True).encode("utf-8")
            return ExportResult(f"TeeBotus_account_{export_id}.yaml", "application/x-yaml", data)
        data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        return ExportResult(f"TeeBotus_account_{export_id}.json", "application/json", data, True, "PyYAML unavailable; emitted JSON fallback")
    if normalized_format in {"txt", "md"}:
        text = _payload_to_markdown(payload)
        extension = "md" if normalized_format == "md" else "txt"
        content_type = "text/markdown" if normalized_format == "md" else "text/plain"
        return ExportResult(f"TeeBotus_account_{export_id}.{extension}", content_type, text.encode("utf-8"))
    if normalized_format in {"tex", "latex"}:
        tex = _payload_to_latex(payload)
        return ExportResult(f"TeeBotus_account_{export_id}.tex", "application/x-tex", tex.encode("utf-8"))
    if normalized_format in {"csv", "cls"}:
        data = _payload_to_csv(payload).encode("utf-8")
        extension = "csv" if normalized_format == "csv" else "cls"
        return ExportResult(f"TeeBotus_account_{export_id}.{extension}", "text/csv", data)
    if normalized_format == "pdf":
        md = _payload_to_markdown(payload)
        return ExportResult(
            f"TeeBotus_account_{export_id}.md",
            "text/markdown",
            md.encode("utf-8"),
            True,
            "PDF engine not configured; emitted Markdown fallback",
        )
    raise ExportError(f"unsupported export format: {fmt}")


def _normalize_format(fmt: str) -> str:
    value = str(fmt or "").strip().lower().lstrip(".")
    if value not in SUPPORTED_EXPORT_FORMATS:
        raise ExportError(f"unsupported export format: {fmt}")
    return value


def _safe_export_slug(value: str) -> str:
    slug = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in str(value or "").strip())
    slug = slug.strip("._-")
    if not slug:
        raise ExportError("export account id must not be empty")
    return slug[:160]


def export_account_data_from_store(account_store: Any, account_id: str, fmt: str) -> ExportResult:
    """Export account data through AccountStore so encrypted files are decrypted first."""
    payload = {
        "account_id": account_id,
        "files": {
            "Account_Profile.json": _redact_data(account_store.account_summary(account_id)),
            "User_Memory_Index.json": _redact_data(account_store.read_memory_index(account_id)),
            "User_Memory_Entries.jsonl": _redact_data(account_store.read_memory_entries(account_id)),
            "OpenAI_State.json": _redact_data(account_store.read_openai_state(account_id)),
        },
    }
    habits = account_store.account_dir(account_id) / "User_Habbits_and_behave.md"
    if habits.exists():
        payload["files"]["User_Habbits_and_behave.md"] = habits.read_text(encoding="utf-8", errors="replace")
    return _emit_payload(account_id, payload, fmt)


def _collect_account_payload(account_id: str, account_dir: Path, *, vault: ExportVault | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"account_id": account_id, "files": {}}
    for filename in ["Account_Profile.json", "User_Memory_Index.json", "User_Memory_Entries.jsonl", "User_Habbits_and_behave.md", "OpenAI_State.json"]:
        path = account_dir / filename
        if not path.exists():
            continue
        if path.suffix == ".json":
            payload["files"][filename] = _redact_data(_read_json_export(path, vault=vault))
        elif path.suffix == ".jsonl":
            payload["files"][filename] = [_redact_data(row) for row in _read_jsonl_export(path, vault=vault)]
        else:
            payload["files"][filename] = _read_text_export(path, vault=vault)
    return _redact_data(payload)


def _read_json_export(path: Path, *, vault: ExportVault | None) -> dict[str, Any]:
    if vault is not None:
        try:
            return vault.read_json(path, {})
        except Exception:
            if _looks_like_encrypted_export_payload(path):
                raise ExportError(f"encrypted export file could not be decrypted: {path}")
    if _looks_like_encrypted_export_payload(path):
        raise ExportError(f"encrypted export file requires a working vault: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {"_unparsed_text": path.read_text(encoding="utf-8", errors="replace")}
    return data if isinstance(data, dict) else {"_value": data}


def _read_jsonl_export(path: Path, *, vault: ExportVault | None) -> list[dict[str, Any]]:
    if vault is not None:
        try:
            return vault.read_jsonl(path)
        except Exception:
            if _looks_like_encrypted_export_payload(path):
                raise ExportError(f"encrypted export file could not be decrypted: {path}")
    if _looks_like_encrypted_export_payload(path):
        raise ExportError(f"encrypted export file requires a working vault: {path}")
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            rows.append(payload if isinstance(payload, dict) else {"_value": payload})
        except json.JSONDecodeError:
            rows.append({"_unparsed_line": line})
    return rows


def _read_text_export(path: Path, *, vault: ExportVault | None) -> str:
    if vault is not None:
        try:
            return vault.read_text(path, "")
        except Exception:
            if _looks_like_encrypted_export_payload(path):
                raise ExportError(f"encrypted export file could not be decrypted: {path}")
    if _looks_like_encrypted_export_payload(path):
        raise ExportError(f"encrypted export file requires a working vault: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def _redact_data(data: Any) -> Any:
    if isinstance(data, dict):
        result: dict[str, Any] = {}
        for key, value in data.items():
            lowered = str(key).casefold()
            if lowered not in SECRET_FIELD_ALLOWLIST and (lowered in SECRET_FIELD_NAMES or any(fragment in lowered for fragment in SECRET_FIELD_FRAGMENTS)):
                result[str(key)] = "<REDACTED>"
            else:
                result[str(key)] = _redact_data(value)
        return result
    if isinstance(data, list):
        return [_redact_data(item) for item in data]
    return data


def _looks_like_encrypted_payload(path: Path) -> bool:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return False
    if not raw.lstrip().startswith(b"{"):
        return False
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and str(payload.get("magic") or "") in {"TMBMAP1", "TMBMEM1", "TMBKEY1"}
        and isinstance(payload.get("ciphertext"), str)
    )


def _payload_to_markdown(payload: dict[str, Any]) -> str:
    lines = ["# TeeBotus Account Export", "", f"Account ID: `{payload.get('account_id', '')}`", ""]
    files = payload.get("files", {})
    if isinstance(files, dict):
        for filename, content in files.items():
            lines.extend([f"## {filename}", "", "```json" if not isinstance(content, str) else "```text"])
            if isinstance(content, str):
                lines.append(content)
            else:
                lines.append(json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True))
            lines.extend(["```", ""])
    return "\n".join(lines).rstrip() + "\n"


def _payload_to_latex(payload: dict[str, Any]) -> str:
    body = _latex_escape(_payload_to_markdown(payload))
    return "\\documentclass{article}\n\\usepackage[utf8]{inputenc}\n\\begin{document}\n\\begin{verbatim}\n" + body + "\\end{verbatim}\n\\end{document}\n"


def _payload_to_csv(payload: dict[str, Any]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["file", "path", "value"])
    files = payload.get("files", {})
    if isinstance(files, dict):
        for filename, content in files.items():
            for path, value in _flatten_values(content):
                writer.writerow([filename, path, value])
    return output.getvalue()


def _flatten_values(data: Any, prefix: tuple[str, ...] = ()) -> Iterable[tuple[str, str]]:
    if isinstance(data, dict):
        for key, value in data.items():
            yield from _flatten_values(value, (*prefix, str(key)))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            yield from _flatten_values(value, (*prefix, str(index)))
    else:
        yield (".".join(prefix), str(data))


def _latex_escape(value: str) -> str:
    return value.replace("\\", "\\textbackslash{}")


def _looks_like_encrypted_export_payload(path: Path) -> bool:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return False
    if not raw.lstrip().startswith(b"{"):
        return False
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and str(payload.get("magic") or "") in {"TMBMAP1", "TMBMEM1"}
        and isinstance(payload.get("ciphertext"), str)
    )
