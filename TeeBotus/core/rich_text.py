from __future__ import annotations

from html import escape


def html_anchor(label: str, url: str) -> str:
    return f'<a href="{escape(str(url or ""), quote=True)}">{escape(str(label or ""))}</a>'


def html_with_single_link(text: str, *, label: str, url: str) -> str:
    plain = str(text or "")
    escaped = escape(plain)
    target = f"{label} {url}"
    escaped_target = escape(target)
    if escaped_target in escaped:
        return escaped.replace(escaped_target, html_anchor(label, url), 1)
    escaped_url = escape(str(url or ""))
    if escaped_url in escaped:
        return escaped.replace(escaped_url, html_anchor(label, url), 1)
    return escaped
