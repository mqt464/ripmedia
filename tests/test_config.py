from pathlib import Path

import pytest

from ripmedia.config import coerce_value, load_config, set_config_value, update_config


def test_load_config_parses_and_normalizes_keys(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "# comment\n"
        "output-dir=~/Downloads\n"
        "PRINT_PATH=true\n"
        "; ignored\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config["output_dir"] == "~/Downloads"
    assert config["print_path"] == "true"


def test_set_config_value_updates_existing(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text("audio=false\nfoo=bar\n", encoding="utf-8")
    set_config_value(path, "audio", "true")
    text = path.read_text(encoding="utf-8")
    assert "audio=true" in text
    assert "foo=bar" in text


def test_coerce_value_bool_and_path() -> None:
    assert coerce_value("audio", "true") is True
    assert coerce_value("audio", "0") is False
    assert coerce_value("audio", "none") is None
    assert coerce_value("prefer_mp3_mp4", "false") is False
    assert coerce_value("update_from_github", "false") is False
    assert coerce_value("resolver", "youtube") == "youtube"
    assert coerce_value("override_audio_format", "false") is None
    assert coerce_value("override_audio_format", ".MP3") == "mp3"
    path = coerce_value("output-dir", "~/Downloads")
    assert isinstance(path, Path)


def test_coerce_value_invalid_bool() -> None:
    with pytest.raises(ValueError):
        coerce_value("audio", "maybe")


def test_coerce_value_invalid_format_bool() -> None:
    with pytest.raises(ValueError):
        coerce_value("override_video_format", "true")


def test_coerce_value_speed_unit() -> None:
    assert coerce_value("speed_unit", "mb/s") == "MBps"
    assert coerce_value("speed_unit", "mbp/s") == "Mbps"
    assert coerce_value("speed_unit", "MBps") == "MBps"
    with pytest.raises(ValueError):
        coerce_value("speed_unit", "mbxs")


def test_coerce_value_int() -> None:
    assert coerce_value("web_port", "0") == 0
    assert coerce_value("web_port", "8787") == 8787
    with pytest.raises(ValueError):
        coerce_value("web_port", "nope")


def test_update_config_adds_and_removes(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "output_dir=custom\n"
        "legacy_key=true\n",
        encoding="utf-8",
    )
    added, removed = update_config(path)
    assert added > 0
    assert removed == 1
    text = path.read_text(encoding="utf-8")
    assert "output_dir=custom" in text
    assert "legacy_key" not in text
