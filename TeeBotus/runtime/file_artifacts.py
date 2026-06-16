from __future__ import annotations

import base64
import mimetypes
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Mapping


MAX_GENERATED_FILE_BYTES = 256 * 1024
MAX_GENERATED_FILES_PER_REPLY = 3
MAX_GENERATED_IMAGE_PROMPT_CHARS = 2000
MAX_GENERATED_IMAGES_PER_REPLY = 2
SAFE_GENERATED_FILE_EXTENSIONS = frozenset(
    {
        ".csv",
        ".ics",
        ".icl",
        ".ical",
        ".json",
        ".md",
        ".pdf",
        ".tex",
        ".txt",
        ".vcf",
        ".vcard",
        ".yaml",
        ".yml",
    }
)
SAFE_GENERATED_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
TEXT_FILE_CONTENT_TYPES = {
    ".ics": "text/calendar; charset=utf-8",
    ".icl": "text/calendar; charset=utf-8",
    ".ical": "text/calendar; charset=utf-8",
    ".vcf": "text/vcard; charset=utf-8",
    ".vcard": "text/vcard; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".yaml": "application/yaml; charset=utf-8",
    ".yml": "application/yaml; charset=utf-8",
    ".tex": "application/x-tex; charset=utf-8",
}
GENERATED_FILE_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bsyt_[A-Za-z0-9_=-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bgsk_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
)
GENERATED_FILE_URL_CREDENTIAL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@")
GENERATED_FILE_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?P<key>[A-Za-z0-9_ -]*(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|bearer[_ -]?token|secret|password)[A-Za-z0-9_ -]*)"
    r"\s*[:=]\s*['\"]?(?P<value>[^'\"\s,;)]+)",
    re.IGNORECASE,
)
GENERATED_FILE_CONTENT_TYPE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}"
    r"(?:\s*;\s*[A-Za-z0-9!#$&^_.+-]+=(?:[A-Za-z0-9!#$&^_.+-]+|\"[A-Za-z0-9 !#$&^_.+;=:-]*\"))*$"
)
SAFE_GENERATED_FILE_SECRET_VALUES = frozenset(
    {
        "configured",
        "example",
        "missing",
        "none",
        "optional",
        "redacted",
        "replace",
        "test",
        "token",
        "<redacted>",
    }
)
FILE_BLOCK_RE = re.compile(
    r"(?P<block>\[\[TEE_FILE(?P<attrs>[^\]]*)\]\]\s*(?P<body>.*?)\s*\[\[/TEE_FILE\]\])",
    re.DOTALL,
)
FILE_ATTR_RE = re.compile(r"(?P<key>filename|content_type|caption)\s*=\s*\"(?P<value>[^\"]*)\"")
IMAGE_BLOCK_RE = re.compile(
    r"(?P<block>\[\[TEE_IMAGE(?P<attrs>[^\]]*)\]\]\s*(?P<body>.*?)\s*\[\[/TEE_IMAGE\]\])",
    re.DOTALL,
)
IMAGE_ATTR_RE = re.compile(r"(?P<key>filename|caption|purpose)\s*=\s*\"(?P<value>[^\"]*)\"")


@dataclass(frozen=True)
class GeneratedFile:
    filename: str
    content_type: str
    data: bytes
    caption: str = ""


@dataclass(frozen=True)
class GeneratedImageRequest:
    filename: str
    prompt: str
    caption: str = ""
    purpose: str = ""


def normalize_generated_file(raw: Mapping[str, Any]) -> GeneratedFile | None:
    filename = _safe_filename(str(raw.get("filename") or "").strip())
    if not filename:
        return None
    extension = PurePath(filename).suffix.casefold()
    if extension not in SAFE_GENERATED_FILE_EXTENSIONS:
        return None
    data = _generated_file_data(raw)
    if data is None or len(data) > MAX_GENERATED_FILE_BYTES:
        return None
    if _generated_file_contains_secret(data):
        return None
    content_type = _safe_content_type(str(raw.get("content_type") or "").strip(), filename)
    caption = str(raw.get("caption") or "").strip()[:240]
    return GeneratedFile(filename=filename, content_type=content_type, data=data, caption=caption)


def normalize_generated_image_request(raw: Mapping[str, Any]) -> GeneratedImageRequest | None:
    filename = _safe_filename(str(raw.get("filename") or "bild.png").strip())
    if not filename:
        filename = "bild.png"
    extension = PurePath(filename).suffix.casefold()
    if extension not in SAFE_GENERATED_IMAGE_EXTENSIONS:
        filename = f"{PurePath(filename).stem or 'bild'}.png"
    prompt = str(raw.get("prompt") or raw.get("text") or raw.get("content") or "").strip()
    if not prompt:
        return None
    prompt = prompt[:MAX_GENERATED_IMAGE_PROMPT_CHARS]
    caption = str(raw.get("caption") or "").strip()[:240]
    purpose = str(raw.get("purpose") or "").strip().casefold()[:80]
    return GeneratedImageRequest(filename=filename, prompt=prompt, caption=caption, purpose=purpose)


def generated_file_to_outbox_payload(file: GeneratedFile) -> dict[str, Any]:
    try:
        text = file.data.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "filename": file.filename,
            "content_type": file.content_type,
            "caption": file.caption,
            "base64": base64.b64encode(file.data).decode("ascii"),
        }
    return {
        "filename": file.filename,
        "content_type": file.content_type,
        "caption": file.caption,
        "text": text,
    }


def parse_generated_file_blocks(text: str) -> tuple[str, tuple[GeneratedFile, ...]]:
    files: list[GeneratedFile] = []

    def replace(match: re.Match[str]) -> str:
        if len(files) >= MAX_GENERATED_FILES_PER_REPLY:
            return ""
        attrs = {m.group("key"): m.group("value") for m in FILE_ATTR_RE.finditer(match.group("attrs") or "")}
        attrs["text"] = match.group("body")
        file = normalize_generated_file(attrs)
        if file is not None:
            files.append(file)
        return ""

    cleaned = FILE_BLOCK_RE.sub(replace, text).strip()
    return cleaned, tuple(files)


def parse_generated_image_blocks(text: str) -> tuple[str, tuple[GeneratedImageRequest, ...]]:
    images: list[GeneratedImageRequest] = []

    def replace(match: re.Match[str]) -> str:
        if len(images) >= MAX_GENERATED_IMAGES_PER_REPLY:
            return ""
        attrs = {m.group("key"): m.group("value") for m in IMAGE_ATTR_RE.finditer(match.group("attrs") or "")}
        attrs["prompt"] = match.group("body")
        image = normalize_generated_image_request(attrs)
        if image is not None:
            images.append(image)
        return ""

    cleaned = IMAGE_BLOCK_RE.sub(replace, text).strip()
    return cleaned, tuple(images)


def _generated_file_data(raw: Mapping[str, Any]) -> bytes | None:
    if "base64" in raw:
        try:
            return base64.b64decode(str(raw.get("base64") or ""), validate=True)
        except (ValueError, TypeError):
            return None
    if "data_base64" in raw:
        try:
            return base64.b64decode(str(raw.get("data_base64") or ""), validate=True)
        except (ValueError, TypeError):
            return None
    text = raw.get("text")
    if text is None:
        text = raw.get("content")
    if text is None:
        return None
    return str(text).encode("utf-8")


def _safe_filename(value: str) -> str:
    name = PurePath(value.replace("\\", "/")).name.strip()
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)
    name = name.strip(" .")
    if not name or name in {".", ".."}:
        return ""
    return name[:120]


def _generated_file_contains_secret(data: bytes) -> bool:
    text = data.decode("utf-8", errors="replace")
    if any(pattern.search(text) for pattern in GENERATED_FILE_SECRET_PATTERNS):
        return True
    if GENERATED_FILE_URL_CREDENTIAL_RE.search(text):
        return True
    for match in GENERATED_FILE_SECRET_ASSIGNMENT_RE.finditer(text):
        if _generated_file_secret_value_is_unsafe(match.group("key"), match.group("value")):
            return True
    return False


def _generated_file_secret_value_is_unsafe(key: object, value: object) -> bool:
    key_text = str(key or "").strip().casefold().replace("-", "_").replace(" ", "_")
    value_text = str(value or "").strip().strip("\"'`")
    if not value_text:
        return False
    normalized_value = value_text.casefold()
    if normalized_value in SAFE_GENERATED_FILE_SECRET_VALUES:
        return False
    if _generated_file_secret_value_is_env_reference(key_text, value_text):
        return False
    return True


def _generated_file_secret_value_is_env_reference(key: object, value: object) -> bool:
    key_text = str(key or "").strip().casefold().replace("-", "_").replace(" ", "_")
    value_text = str(value or "").strip()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", value_text):
        return False
    return key_text.endswith("_env") or value_text == key_text.upper()


def _safe_content_type(value: str, filename: str) -> str:
    normalized = str(value or "").strip()
    if normalized and _content_type_is_safe(normalized):
        return normalized[:160]
    return _guess_generated_file_content_type(filename)


def _content_type_is_safe(value: str) -> bool:
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return False
    return bool(GENERATED_FILE_CONTENT_TYPE_RE.fullmatch(value))


def _guess_generated_file_content_type(filename: str) -> str:
    extension = PurePath(filename).suffix.casefold()
    if extension in TEXT_FILE_CONTENT_TYPES:
        return TEXT_FILE_CONTENT_TYPES[extension]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"
