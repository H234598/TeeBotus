from __future__ import annotations

from email.message import Message


def parse_header(line: str) -> tuple[str, dict[str, str]]:
    message = Message()
    message["content-type"] = line
    value = message.get_content_type()
    params = dict(message.get_params(header="content-type")[1:])
    return value, params
