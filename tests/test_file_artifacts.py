from __future__ import annotations

from TeeBotus.runtime.file_artifacts import parse_generated_file_blocks, parse_generated_image_blocks


def test_parse_generated_file_blocks_accepts_icl_calendar_files() -> None:
    visible, files = parse_generated_file_blocks(
        'Bitte importieren.\n[[TEE_FILE filename="termin.icl"]]\nBEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n[[/TEE_FILE]]'
    )

    assert visible == "Bitte importieren."
    assert len(files) == 1
    assert files[0].filename == "termin.icl"
    assert files[0].content_type == "text/calendar; charset=utf-8"
    assert files[0].data.startswith(b"BEGIN:VCALENDAR")


def test_parse_generated_file_blocks_rejects_secret_like_content() -> None:
    secret = "sk-" + "live" + "-secret1234567890"
    visible, files = parse_generated_file_blocks(
        f'Nicht senden.\n[[TEE_FILE filename="notiz.txt"]]\nOPENAI_API_KEY={secret}\n[[/TEE_FILE]]'
    )

    assert visible == "Nicht senden."
    assert files == ()


def test_parse_generated_file_blocks_rejects_uppercase_secret_values() -> None:
    visible, files = parse_generated_file_blocks(
        'Nicht senden.\n[[TEE_FILE filename="notiz.txt"]]\nOPENAI_API_KEY=PLAINSECRET123\n[[/TEE_FILE]]'
    )

    assert visible == "Nicht senden."
    assert files == ()


def test_parse_generated_file_blocks_allows_secret_placeholders() -> None:
    visible, files = parse_generated_file_blocks(
        'Vorlage.\n[[TEE_FILE filename="config.md"]]\nOPENAI_API_KEY=OPENAI_API_KEY\nToken: <redacted>\n[[/TEE_FILE]]'
    )

    assert visible == "Vorlage."
    assert len(files) == 1
    assert files[0].filename == "config.md"


def test_parse_generated_file_blocks_sanitizes_header_injection_content_type() -> None:
    visible, files = parse_generated_file_blocks(
        'Datei.\n[[TEE_FILE filename="notiz.txt" content_type="text/plain\r\nX-Injected: yes"]]\nHallo\n[[/TEE_FILE]]'
    )

    assert visible == "Datei."
    assert len(files) == 1
    assert files[0].content_type == "text/plain; charset=utf-8"


def test_parse_generated_file_blocks_falls_back_from_invalid_content_type() -> None:
    visible, files = parse_generated_file_blocks(
        'Datei.\n[[TEE_FILE filename="daten.json" content_type="not-a-mime"]]\n{}\n[[/TEE_FILE]]'
    )

    assert visible == "Datei."
    assert len(files) == 1
    assert files[0].content_type == "application/json; charset=utf-8"


def test_parse_generated_file_blocks_preserves_safe_content_type_parameters() -> None:
    visible, files = parse_generated_file_blocks(
        'Datei.\n[[TEE_FILE filename="termin.ics" content_type="text/calendar; charset=utf-8"]]\nBEGIN:VCALENDAR\nEND:VCALENDAR\n[[/TEE_FILE]]'
    )

    assert visible == "Datei."
    assert len(files) == 1
    assert files[0].content_type == "text/calendar; charset=utf-8"


def test_parse_generated_image_blocks_extracts_safe_image_request() -> None:
    visible, images = parse_generated_image_blocks(
        'Schau mal.\n[[TEE_IMAGE filename="../wetter.svg" caption="Morgenbild" purpose="weather_encouragement"]]\n'
        "Ein freundliches Aquarell mit Regen und warmer Lampe.\n"
        "[[/TEE_IMAGE]]"
    )

    assert visible == "Schau mal."
    assert len(images) == 1
    assert images[0].filename == "wetter.png"
    assert images[0].caption == "Morgenbild"
    assert images[0].purpose == "weather_encouragement"
    assert "Aquarell" in images[0].prompt
