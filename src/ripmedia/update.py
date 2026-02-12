from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from time import monotonic

from .shared import format_duration
from .ui import StepResult, Ui


def run_update(*, ui: Ui, install_system: bool, git_pull: bool) -> int:
    root = _find_repo_root()

    steps: list[tuple[str, callable]] = []
    if git_pull:
        steps.append(("Git pull", lambda: _run_git_pull(ui, root)))
    steps.append(("Python package", lambda: _update_python_packages(root)))
    steps.append(("yt-dlp", _update_ytdlp))
    steps.append(("System deps", lambda: _ensure_system_deps(install_system=install_system)))
    start = monotonic()
    results = ui.run_steps(steps, show_description=False)
    elapsed = monotonic() - start

    all_ok = all(step.ok for step in results)
    if all_ok:
        ui.info(f"[green]Update complete in {format_duration(elapsed)}.[/green]")
        return 0

    ui.error("Update finished with issues.")
    return 1


def _find_repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here.parent] + list(here.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    return None


def _run_git_pull(ui: Ui, root: Path | None) -> StepResult:
    if root is None:
        return StepResult("Git pull", True, "skipped (no repo)")
    if not (root / ".git").exists():
        return StepResult("Git pull", True, "skipped (no .git)")
    if not _which("git"):
        return StepResult("Git pull", True, "skipped (git not found)")
    ok, detail = _run_cmd(["git", "-C", str(root), "pull", "--ff-only"])
    return StepResult("Git pull", ok, detail)


def _update_python_packages(root: Path | None) -> StepResult:
    if root:
        ok, detail = _run_cmd([sys.executable, "-m", "pip", "install", "-e", str(root)])
        return StepResult("Python package", ok, detail)
    ok, detail = _run_cmd([sys.executable, "-m", "pip", "install", "-U", "ripmedia"])
    return StepResult("Python package", ok, detail)


def _update_ytdlp() -> StepResult:
    ok, detail = _run_cmd([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"])
    return StepResult("yt-dlp", ok, detail)


def _ensure_system_deps(*, install_system: bool) -> StepResult:
    missing: list[str] = []
    if not _which("ffmpeg"):
        missing.append("ffmpeg")
    if not _has_js_runtime():
        missing.append("js_runtime")

    if not missing:
        return StepResult("System deps", True, "ok")

    if not install_system:
        detail = _missing_detail(missing)
        return StepResult("System deps", False, detail)

    if platform.system().lower() != "windows":
        detail = _missing_detail(missing)
        return StepResult("System deps", False, detail)

    if not _which("winget"):
        detail = _missing_detail(missing) + "; winget not found"
        return StepResult("System deps", False, detail)

    ok = True
    installed: list[str] = []
    failed: list[str] = []
    if "ffmpeg" in missing:
        ff_ok, _ = _run_cmd(
            [
                "winget",
                "install",
                "--id",
                "Gyan.FFmpeg",
                "-e",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ],
        )
        if ff_ok:
            installed.append("ffmpeg")
        else:
            failed.append("ffmpeg")
        ok = ok and ff_ok
    if "js_runtime" in missing:
        deno_ok, _ = _run_cmd(
            [
                "winget",
                "install",
                "--id",
                "DenoLand.Deno",
                "-e",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ],
        )
        if not deno_ok:
            deno_ok, _ = _run_cmd(
                [
                    "winget",
                    "install",
                    "--id",
                    "OpenJS.NodeJS.LTS",
                    "-e",
                    "--accept-source-agreements",
                    "--accept-package-agreements",
                ],
            )
        if deno_ok:
            installed.append("js runtime")
        else:
            failed.append("js runtime")
        ok = ok and deno_ok

    detail_parts: list[str] = []
    if installed:
        detail_parts.append("installed " + ", ".join(installed))
    if failed:
        detail_parts.append("failed " + ", ".join(failed))
    detail = "; ".join(detail_parts) if detail_parts else "partial"
    return StepResult("System deps", ok, detail)


def _missing_detail(missing: list[str]) -> str:
    labels = []
    if "ffmpeg" in missing:
        labels.append("ffmpeg")
    if "js_runtime" in missing:
        labels.append("js runtime")
    return "missing " + ", ".join(labels)


def _has_js_runtime() -> bool:
    return _which("deno") or _which("node") or _which("bun")


def _which(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _run_cmd(cmd: list[str]) -> tuple[bool, str | None]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        return False, stderr.splitlines()[-1] if stderr else "command failed"
    if proc.stdout:
        last_line = proc.stdout.strip().splitlines()[-1]
        return True, last_line if last_line else None
    return True, None

