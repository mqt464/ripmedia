from __future__ import annotations

import configparser
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CookieProfile:
    browser_id: str
    browser_label: str
    profile: str | None
    container: Path | None
    profile_path: Path | None

    @property
    def spec(self) -> tuple:
        if self.profile_path is not None:
            return (self.browser_id, str(self.profile_path))
        if self.profile is not None:
            return (self.browser_id, self.profile)
        return (self.browser_id,)

    @property
    def display(self) -> str:
        profile = self.profile or "Default"
        suffix = ""
        if self.container is not None:
            suffix = f" [dim]({self.container})[/dim]"
        elif self.profile_path is not None:
            suffix = f" [dim]({self.profile_path})[/dim]"
        return f"{self.browser_label} · {profile}{suffix}"


def discover_cookie_profiles() -> list[CookieProfile]:
    if sys.platform.startswith("win"):
        return _discover_windows()
    if sys.platform == "darwin":
        return _discover_macos()
    return _discover_linux()


def _discover_windows() -> list[CookieProfile]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roaming = Path(os.environ.get("APPDATA", ""))
    candidates: list[CookieProfile] = []

    chromium_roots = [
        ("Chrome", "chrome", local / "Google" / "Chrome" / "User Data"),
        ("Edge", "edge", local / "Microsoft" / "Edge" / "User Data"),
        ("Brave", "brave", local / "BraveSoftware" / "Brave-Browser" / "User Data"),
        ("Vivaldi", "vivaldi", local / "Vivaldi" / "User Data"),
        ("Chromium", "chromium", local / "Chromium" / "User Data"),
        ("Helium", "chrome", local / "imput" / "Helium" / "User Data"),
    ]
    for label, browser_id, root in chromium_roots:
        candidates.extend(_find_chromium_profiles(label, browser_id, root))

    firefox_root = roaming / "Mozilla" / "Firefox"
    candidates.extend(_find_firefox_profiles(firefox_root))

    return candidates


def _discover_macos() -> list[CookieProfile]:
    home = Path.home()
    support = home / "Library" / "Application Support"
    candidates: list[CookieProfile] = []
    chromium_roots = [
        ("Chrome", "chrome", support / "Google" / "Chrome"),
        ("Edge", "edge", support / "Microsoft Edge"),
        ("Brave", "brave", support / "BraveSoftware" / "Brave-Browser"),
        ("Vivaldi", "vivaldi", support / "Vivaldi"),
        ("Chromium", "chromium", support / "Chromium"),
        ("Helium", "chrome", support / "imput" / "Helium"),
    ]
    for label, browser_id, root in chromium_roots:
        candidates.extend(_find_chromium_profiles(label, browser_id, root))

    firefox_root = support / "Firefox"
    candidates.extend(_find_firefox_profiles(firefox_root))
    return candidates


def _discover_linux() -> list[CookieProfile]:
    home = Path.home()
    config_dir = home / ".config"
    candidates: list[CookieProfile] = []
    chromium_roots = [
        ("Chrome", "chrome", config_dir / "google-chrome"),
        ("Edge", "edge", config_dir / "microsoft-edge"),
        ("Brave", "brave", config_dir / "BraveSoftware" / "Brave-Browser"),
        ("Vivaldi", "vivaldi", config_dir / "vivaldi"),
        ("Chromium", "chromium", config_dir / "chromium"),
    ]
    for label, browser_id, root in chromium_roots:
        candidates.extend(_find_chromium_profiles(label, browser_id, root))

    firefox_root = home / ".mozilla" / "firefox"
    candidates.extend(_find_firefox_profiles(firefox_root))
    return candidates


def _find_chromium_profiles(
    label: str, browser_id: str, root: Path
) -> list[CookieProfile]:
    if not root.exists():
        return []
    profiles: list[CookieProfile] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        if name != "Default" and not re.match(r"Profile \d+", name):
            continue
        if not _has_chromium_cookies(entry):
            continue
        profiles.append(
            CookieProfile(
                browser_id=browser_id,
                browser_label=label,
                profile=name,
                container=root,
                profile_path=entry,
            )
        )
    return profiles


def _find_firefox_profiles(root: Path) -> list[CookieProfile]:
    ini = root / "profiles.ini"
    if not ini.exists():
        return []
    parser = configparser.ConfigParser()
    parser.read(ini, encoding="utf-8")
    profiles: list[CookieProfile] = []
    for section in parser.sections():
        if not section.lower().startswith("profile"):
            continue
        name = parser.get(section, "Name", fallback=None)
        rel = parser.get(section, "IsRelative", fallback="1")
        path = parser.get(section, "Path", fallback=None)
        if not path:
            continue
        profile_path = Path(path)
        if rel.strip() == "1":
            profile_path = root / profile_path
        if not profile_path.exists():
            continue
        if not (profile_path / "cookies.sqlite").exists():
            continue
        profiles.append(
            CookieProfile(
                browser_id="firefox",
                browser_label="Firefox",
                profile=name or profile_path.name,
                container=None,
                profile_path=profile_path,
            )
        )
    return profiles


def _has_chromium_cookies(profile_dir: Path) -> bool:
    return (profile_dir / "Network" / "Cookies").exists() or (profile_dir / "Cookies").exists()


def format_cookie_spec(spec: Iterable) -> str:
    parts = []
    for part in spec:
        if part is None:
            continue
        parts.append(str(part))
    return "|".join(parts)
