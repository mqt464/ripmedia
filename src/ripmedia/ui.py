from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.spinner import Spinner
from rich.text import Text

from .model import LogLevel


@dataclass
class Ui:
    console: Console
    level: LogLevel
    print_path_only: bool = False

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

    @contextmanager
    def spinner(self, label: str) -> Iterator[None]:
        if self.level == "quiet" or self.print_path_only:
            yield
            return
        spinner = Spinner("dots", text=Text(label))
        with self.console.status(spinner):
            yield

    def progress(self) -> Progress:
        return Progress(
            TextColumn("{task.description}"),
            BarColumn(bar_width=None),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=self.console,
            transient=True,
            disable=self.level == "quiet" or self.print_path_only,
        )
