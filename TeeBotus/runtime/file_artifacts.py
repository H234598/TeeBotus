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
    content_type = str(raw.get("content_type") or "").strip() or _guess_generated_file_content_type(filename)
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


def _guess_generated_file_content_type(filename: str) -> str:
    extension = PurePath(filename).suffix.casefold()
    if extension in TEXT_FILE_CONTENT_TYPES:
        return TEXT_FILE_CONTENT_TYPES[extension]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"
