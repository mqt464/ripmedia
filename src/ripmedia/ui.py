from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from time import monotonic, sleep
from typing import Callable, Iterator

from concurrent.futures import ThreadPoolExecutor

from rich.console import Console
from rich.console import Group
from rich.live import Live
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.spinner import Spinner
from rich.text import Text
from rich.markup import escape

from .model import LogLevel


@dataclass
class Ui:
    console: Console
    level: LogLevel
    print_path_only: bool = False
    plain_paths: bool = False
    speed_unit: str = "MBps"

    def stage(self, label: str, detail: str | None = None) -> None:
        if self.level == "quiet" or self.print_path_only:
            return
        style = {
            "Detected": "bold cyan",
            "Resolve": "bold magenta",
            "Downloading": "bold cyan",
            "Post-process": "bold cyan",
            "Tagging": "bold cyan",
            "Saved": "bold green",
            "Update": "bold cyan",
        }.get(label, "bold")
        if detail:
            self.console.print(f"[{style}]{label}[/] [dim]{detail}[/dim]")
        else:
            self.console.print(f"[{style}]{label}[/]")

    def info(self, message: str) -> None:
        if self.level == "quiet" or self.print_path_only:
            return
        self.console.print(message)

    def verbose(self, message: str) -> None:
        if self.level not in ("verbose", "debug") or self.print_path_only:
            return
        self.console.print(f"[dim]{message}[/dim]")

    def error(self, message: str) -> None:
        if self.print_path_only:
            return
        self.console.print(f"[red]Error:[/red] {message}")

    def banner(self, title: str) -> None:
        if self.level == "quiet" or self.print_path_only:
            return
        line = "=" * len(title)
        self.console.print(f"[bold]{title}[/bold]")
        self.console.print(f"[dim]{line}[/dim]")

    def section(self, title: str) -> None:
        if self.level == "quiet" or self.print_path_only:
            return
        self.console.print(f"[bold]{title}[/bold]")

    def status(self, label: str, ok: bool, detail: str | None = None) -> None:
        if self.level == "quiet" or self.print_path_only:
            return
        badge = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        if detail:
            self.console.print(f"{badge} {label} [dim]({detail})[/dim]")
        else:
            self.console.print(f"{badge} {label}")

    def path_link(self, path: "Path") -> str:
        if self.plain_paths:
            return str(path)
        try:
            resolved = path.resolve()
            target = resolved.parent.as_uri()
        except Exception:  # noqa: BLE001
            return str(path)
        return f"[link={target}]{resolved}[/link]"

    def hint(self, header: str, steps: list[str]) -> None:
        if self.level == "quiet" or self.print_path_only:
            return
        self.console.print(f"[bold]{header}[/bold]")
        for idx, step in enumerate(steps, start=1):
            self.console.print(f"{idx}. {step}")

    @contextmanager
    def spinner(self, label: str) -> Iterator[None]:
        if self.level == "quiet" or self.print_path_only:
            yield
            return
        spinner = Spinner("dots", text=Text(label))
        with self.console.status(spinner):
            yield

    def progress(
        self,
        *,
        transient: bool = True,
        show_description: bool = True,
        show_bytes: bool = False,
        show_speed: bool = False,
    ) -> Progress:
        columns = []
        columns.append(_CountColumn())
        if show_description:
            columns.append(TextColumn("{task.description}"))
        columns.extend(
            [
                BarColumn(bar_width=None, complete_style="cyan", finished_style="cyan", style="grey23"),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            ]
        )
        if show_bytes:
            columns.append(_BytesColumn())
        if show_speed:
            columns.append(_SpeedColumn(self.speed_unit))
        columns.append(TimeRemainingColumn())
        return Progress(
            *columns,
            console=self.console,
            transient=transient,
            disable=self.level == "quiet" or self.print_path_only,
        )

    def run_steps(
        self,
        steps: list[tuple[str, Callable[[], "StepResult"]]],
        *,
        show_description: bool = True,
    ) -> list["StepResult"]:
        if self.level == "quiet" or self.print_path_only:
            return [fn() for _, fn in steps]

        results: list[StepResult] = []
        durations: list[float] = []
        completed = 0.0
        default_step_seconds = 20.0

        progress = self.progress(transient=False, show_description=show_description)
        task_id = progress.add_task("Preparing", total=len(steps))

        def estimate_step_seconds() -> float:
            if durations:
                return max(5.0, sum(durations) / len(durations))
            return default_step_seconds

        with ThreadPoolExecutor(max_workers=1) as executor, self.live_progress(
            progress,
            max_log_lines=6,
        ) as live:
            for label, fn in steps:
                progress.update(task_id, description=label)
                live.tick(label)

                start = monotonic()
                future = executor.submit(fn)
                while not future.done():
                    elapsed = monotonic() - start
                    est = estimate_step_seconds()
                    fraction = min(0.95, elapsed / est) if est > 0 else 0.0
                    progress.update(task_id, completed=completed + fraction)
                    live.tick()
                    sleep(0.2)

                try:
                    result = future.result()
                except Exception as e:  # noqa: BLE001
                    result = StepResult(label=label, ok=False, detail=str(e))

                duration = monotonic() - start
                durations.append(duration)
                completed += 1.0
                progress.update(task_id, completed=completed)
                stamped = StepResult(
                    label=label,
                    ok=result.ok,
                    detail=result.detail,
                    duration_s=duration,
                )
                results.append(stamped)
                live.add_result(stamped)

            progress.update(task_id, completed=len(steps))
            live.clear_current()

        return results

    def live_progress(self, progress: Progress, *, max_log_lines: int = 6) -> "LiveProgress":
        return LiveProgress(self, progress=progress, max_log_lines=max_log_lines)


@dataclass(frozen=True)
class StepResult:
    label: str
    ok: bool
    detail: str | None = None
    duration_s: float | None = None


def _format_step(step: StepResult) -> str:
    badge = "[green]OK[/green]" if step.ok else "[red]FAIL[/red]"
    extras: list[str] = []
    if step.duration_s is not None:
        extras.append(f"[dim]{_format_duration(step.duration_s)}[/dim]")
    if step.detail and (
        not step.ok or step.detail.lower().startswith("skipped") or step.label.lower() == "saved"
    ):
        extras.append(f"[dim]{_shorten(step.detail, 60)}[/dim]")
    extra_text = f" {' | '.join(extras)}" if extras else ""
    label = _shorten(step.label, 48)
    return f"{badge} {label}{extra_text}"


def _format_duration(seconds: float) -> str:
    total = int(round(seconds))
    if total < 0:
        total = 0
    mins, secs = divmod(total, 60)
    hours, mins = divmod(mins, 60)
    if hours:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def _format_bytes_parts(value: float) -> tuple[str, str]:
    amount = float(value)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = units[0]
    for unit in units:
        if abs(amount) < 1000 or unit == units[-1]:
            break
        amount /= 1000.0
    if unit == "B":
        return f"{amount:.0f}", unit
    return f"{amount:>5.1f}", unit


def _shorten(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


class _CountColumn(ProgressColumn):
    def render(self, task) -> Text:  # type: ignore[override]
        item_total = task.fields.get("item_total")
        if isinstance(item_total, int) and item_total > 0:
            item_index = task.fields.get("item_index") or 0
            return Text(f"({int(item_index)}/{int(item_total)})")

        total = task.total
        if total is None or total <= 0:
            return Text("")
        completed = int(task.completed)
        total_i = int(total)
        return Text(f"({completed}/{total_i})")


class _BytesColumn(ProgressColumn):
    def render(self, task) -> Text:  # type: ignore[override]
        total = task.total
        completed = task.completed
        if completed is None:
            return Text("")
        if total is None or total <= 0:
            if completed <= 0:
                return Text("")
            value, unit = _format_bytes_parts(completed)
            return Text(f"{value} {unit}", style="progress.data.download")
        if total <= 1 and completed <= 1:
            return Text("")
        value_done, unit_done = _format_bytes_parts(completed)
        value_total, unit_total = _format_bytes_parts(total)
        if unit_done == unit_total:
            text = f"{value_done}/{value_total} {unit_done}"
        else:
            text = f"{value_done} {unit_done}/{value_total} {unit_total}"
        return Text(text, style="progress.data.download")


class _SpeedColumn(ProgressColumn):
    def __init__(self, unit: str) -> None:
        super().__init__()
        self._unit = unit

    def render(self, task) -> Text:  # type: ignore[override]
        speed = task.speed
        if speed is None or speed <= 0:
            return Text("")
        if self._unit == "Mbps":
            value = (speed * 8) / 1_000_000
            suffix = "Mb/s"
        else:
            value = speed / 1_000_000
            suffix = "MB/s"
        return Text(f"{value:>5.1f} {suffix}", style="progress.data.speed")


def _render_live(progress: Progress, log_lines: list[str], current_line: str) -> Group:
    lines: list[Text] = []
    if current_line:
        lines.append(Text.from_markup(current_line))
    if log_lines:
        lines.extend(Text.from_markup(line) for line in log_lines)
    if not lines:
        lines.append(Text(""))
    return Group(progress, *lines)


class LiveProgress:
    def __init__(self, ui: Ui, *, progress: Progress, max_log_lines: int = 6) -> None:
        self._ui = ui
        self._progress = progress
        self._max_log_lines = max_log_lines
        self._log_lines: list[str] = []
        self._current_line = ""
        self._label = ""
        self._spinner_frames = ["-", "\\", "|", "/"]
        self._live: Live | None = None

    @property
    def label(self) -> str:
        return self._label

    @property
    def progress(self) -> Progress:
        return self._progress

    def __enter__(self) -> "LiveProgress":
        self._live = Live(
            _render_live(self._progress, self._log_lines, self._current_line),
            console=self._ui.console,
            refresh_per_second=12,
        )
        self._live.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._live is not None:
            self._live.__exit__(exc_type, exc, tb)

    def tick(self, label: str | None = None) -> None:
        if label is not None:
            self._label = label
        spinner = self._spinner_frames[int(monotonic() * 10) % len(self._spinner_frames)]
        safe_label = escape(self._label)
        self._current_line = f"[dim]{spinner}[/dim] Running: {safe_label}"
        self._refresh()

    def clear_current(self) -> None:
        self._current_line = ""
        self._refresh()

    def add_result(self, result: StepResult) -> None:
        self._log_lines.append(_format_step(result))
        if len(self._log_lines) > self._max_log_lines:
            del self._log_lines[:-self._max_log_lines]
        self._refresh()

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(_render_live(self._progress, self._log_lines, self._current_line))
