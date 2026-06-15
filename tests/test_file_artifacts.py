from __future__ import annotations

from TeeBotus.runtime.file_artifacts import parse_generated_file_blocks


def test_parse_generated_file_blocks_accepts_icl_calendar_files() -> None:
    visible, files = parse_generated_file_blocks(
        'Bitte importieren.\n[[TEE_FILE filename="termin.icl"]]\nBEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n[[/TEE_FILE]]'
    )

    assert visible == "Bitte importieren."
    assert len(files) == 1
    assert files[0].filename == "termin.icl"
    assert files[0].content_type == "text/calendar; charset=utf-8"
    assert files[0].data.startswith(b"BEGIN:VCALENDAR")
