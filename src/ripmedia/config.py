from __future__ import annotations

import os
import re
from pathlib import Path

from .shared import open_with_default_app

_BOOL_TRUE = {"1", "true", "yes", "on"}
_BOOL_FALSE = {"0", "false", "no", "off"}
_BOOL_KEYS = {
    "audio",
    "verbose",
    "debug",
    "quiet",
    "print_path",
    "no_color",
    "interactive",
    "prefer_mp3_mp4",
    "show_file_size",
    "update_from_github",
}
_PATH_KEYS = {"output_dir", "cookies"}
_FORMAT_OVERRIDE_KEYS = {"override_audio_format", "override_video_format"}
_SPEED_UNIT_KEYS = {"speed_unit"}
_INT_KEYS = {"web_port"}


def _default_config_text() -> str:
    downloads = Path.home() / "Downloads"
    output_dir = downloads if downloads.exists() else Path("output")
    return (
        "# ripmedia config\n"
        "# key=value\n"
        "#\n"
        f"output_dir={output_dir}\n"
        "web_port=0\n"
        "override_audio_format=false\n"
        "override_video_format=false\n"
        "prefer_mp3_mp4=true\n"
        "show_file_size=false\n"
        "update_from_github=true\n"
        "speed_unit=MBps\n"
        "resolver=youtube\n"
        "audio=false\n"
        "verbose=false\n"
        "debug=false\n"
        "quiet=false\n"
        "print_path=false\n"
        "no_color=false\n"
        "interactive=false\n"
        "cookies=none\n"
        "cookies_from_browser=none\n"
    )


def get_config_path() -> Path:
    return Path.home() / ".ripmedia" / "config.ini"


def ensure_config_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_default_config_text(), encoding="utf-8")


def load_config(path: Path | None = None) -> dict[str, str]:
    path = path or get_config_path()
    if not path.exists():
        return {}
    config: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lower().replace("-", "_")
        value = value.strip()
        if key:
            config[key] = value
    return config


def set_config_value(path: Path, key: str, value: str) -> None:
    key = key.strip().lower().replace("-", "_")
    ensure_config_file(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    updated = False
    out: list[str] = []
    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith(";") or "=" not in raw:
            out.append(line)
            continue
        k, _ = raw.split("=", 1)
        if k.strip().lower() == key:
            out.append(f"{key}={value}")
            updated = True
        else:
            out.append(line)
    if not updated:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def update_config(path: Path) -> tuple[int, int]:
    ensure_config_file(path)
    existing = load_config(path)
    defaults = _default_config_values()

    removed = [key for key in existing if key not in defaults]
    merged = defaults.copy()
    for key, value in existing.items():
        if key in defaults:
            merged[key] = value

    lines: list[str] = []
    for line in _default_config_text().splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith(";") or "=" not in raw:
            lines.append(line)
            continue
        key, _ = raw.split("=", 1)
        normalized = key.strip().lower().replace("-", "_")
        value = merged.get(normalized, "")
        lines.append(f"{normalized}={value}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    added = [key for key in defaults if key not in existing]
    return len(added), len(removed)


def coerce_value(key: str, value: str):
    key = key.strip().lower().replace("-", "_")
    v = value.strip()
    if v.lower() in {"", "none", "null"}:
        return None
    if key in _BOOL_KEYS:
        low = v.lower()
        if low in _BOOL_TRUE:
            return True
        if low in _BOOL_FALSE:
            return False
        raise ValueError(f"Invalid boolean for {key}: {value}")
    if key in _PATH_KEYS:
        return Path(os.path.expanduser(v))
    if key in _FORMAT_OVERRIDE_KEYS:
        low = v.lower()
        if low in _BOOL_FALSE:
            return None
        if low in _BOOL_TRUE:
            raise ValueError(f"Invalid format for {key}: {value}")
        low = low.lstrip(".")
        if not low:
            return None
        if not re.fullmatch(r"[a-z0-9]+", low):
            raise ValueError(f"Invalid format for {key}: {value}")
        return low
    if key in _INT_KEYS:
        try:
            return int(v)
        except ValueError as e:
            raise ValueError(f"Invalid integer for {key}: {value}") from e
    if key in _SPEED_UNIT_KEYS:
        return _normalize_speed_unit(v)
    return v


def _normalize_speed_unit(value: str) -> str:
    raw = value.strip().replace(" ", "")
    if not raw:
        raise ValueError(f"Invalid speed_unit: {value}. Use mb/s or mbp/s.")
    if raw in {"MBps", "MB/s"}:
        return "MBps"
    if raw in {"Mbps", "Mb/s"}:
        return "Mbps"
    v = raw.lower()
    if v in {"mb/s", "mbyte/s", "mbytes/s", "mbps_bytes"}:
        return "MBps"
    if v in {"mbp/s", "mbps", "mbit/s", "mbits/s"}:
        return "Mbps"
    if "byte" in v:
        return "MBps"
    if "bit" in v:
        return "Mbps"
    if v.endswith("mbs"):
        return "MBps"
    if v.endswith("mbps"):
        return "Mbps"
    raise ValueError(f"Invalid speed_unit: {value}. Use mb/s or mbp/s.")


def _default_config_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _default_config_text().splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith(";") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        normalized = key.strip().lower().replace("-", "_")
        values[normalized] = value.strip()
    return values


def open_config(path: Path) -> None:
    ensure_config_file(path)
    open_with_default_app(path, reveal_parent=False)
