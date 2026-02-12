from __future__ import annotations

import io
import json
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count
from pathlib import Path
from time import monotonic
from typing import Any

from importlib import resources
from concurrent.futures import ThreadPoolExecutor

from rich.console import Console

from .errors import RipmediaError
from .model import NormalizedItem
from .pipeline import run_download
from .ui import StepResult, Ui
from .urls import expand_url_args


@dataclass
class WebSettings:
    output_dir: Path
    audio: bool
    override_audio_format: str | None
    override_video_format: str | None
    resolver: str
    interactive: bool
    cookies: Path | None
    cookies_from_browser: str | None
    prefer_mp3_mp4: bool
    speed_unit: str


@dataclass
class ItemState:
    id: str
    url: str
    status: str = "queued"
    title: str | None = None
    provider: str | None = None
    kind: str | None = None
    current: str | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)
    error: str | None = None
    updated_at: float = field(default_factory=monotonic)


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: set[queue.Queue[str]] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue()
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue[str]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, payload: dict[str, Any]) -> None:
        message = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(message)
            except Exception:
                continue


class DownloadManager:
    def __init__(self, *, broker: EventBroker, settings: WebSettings, parallel: int) -> None:
        self._broker = broker
        self._settings = settings
        self._executor = ThreadPoolExecutor(max_workers=max(1, parallel))
        self._items: dict[str, ItemState] = {}
        self._lock = threading.Lock()
        self._id_counter = count(1)

    def enqueue(self, urls: list[str]) -> list[ItemState]:
        items: list[ItemState] = []
        for url in urls:
            item_id = str(next(self._id_counter))
            state = ItemState(id=item_id, url=url)
            with self._lock:
                self._items[item_id] = state
            items.append(state)
            self._broker.publish({"type": "queued", "item": self._serialize(state)})
            self._executor.submit(self._run, item_id, url)
        return items

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._serialize(item) for item in self._items.values()]

    def _serialize(self, item: ItemState) -> dict[str, Any]:
        return {
            "id": item.id,
            "url": item.url,
            "status": item.status,
            "title": item.title,
            "provider": item.provider,
            "kind": item.kind,
            "current": item.current,
            "progress": item.progress,
            "steps": item.steps,
            "paths": item.paths,
            "error": item.error,
            "updated_at": item.updated_at,
        }

    def _update(self, item_id: str, **changes: Any) -> ItemState | None:
        with self._lock:
            item = self._items.get(item_id)
            if not item:
                return None
            for key, value in changes.items():
                setattr(item, key, value)
            item.updated_at = monotonic()
            return item

    def _record_step(self, item_id: str, step: StepResult) -> None:
        payload = {"ok": step.ok, "detail": step.detail, "duration": step.duration_s}
        with self._lock:
            item = self._items.get(item_id)
            if not item:
                return
            steps = dict(item.steps)
            steps[step.label] = payload
            item.steps = steps
            item.updated_at = monotonic()
        self._broker.publish({"type": "step", "id": item_id, "step": step.label, **payload})

    def _record_status(self, item_id: str, label: str) -> None:
        with self._lock:
            item = self._items.get(item_id)
            if not item:
                return
            if item.status not in {"done", "error"}:
                item.status = "running"
            item.current = label
            item.updated_at = monotonic()
        self._broker.publish({"type": "status", "id": item_id, "label": label})

    def _record_progress(self, item_id: str, data: dict[str, Any]) -> None:
        speed = data.get("speed")
        if speed is not None:
            try:
                speed_value = float(speed)
            except (TypeError, ValueError):
                speed_value = None
            if speed_value is not None:
                data["speed_display"] = _format_speed(speed_value, self._settings.speed_unit)
                data["speed_unit"] = self._settings.speed_unit
        item = self._update(item_id, progress=data)
        if item:
            self._broker.publish({"type": "progress", "id": item_id, **data})

    def _record_metadata(self, item_id: str, item: NormalizedItem) -> None:
        title = item.title or item.url
        provider = item.provider.value if hasattr(item.provider, "value") else str(item.provider)
        kind = item.kind.value if hasattr(item.kind, "value") else str(item.kind)
        updated = self._update(item_id, title=title, provider=provider, kind=kind, status="running")
        if updated:
            self._broker.publish(
                {"type": "meta", "id": item_id, "title": title, "provider": provider, "kind": kind}
            )

    def _run(self, item_id: str, url: str) -> None:
        ui = Ui(
            console=Console(file=io.StringIO(), no_color=True, highlight=False, soft_wrap=True),
            level="quiet",
            plain_paths=True,
            speed_unit=self._settings.speed_unit,
        )
        start = monotonic()
        self._record_status(item_id, "Starting")

        def metadata_cb(item: NormalizedItem) -> None:
            self._record_metadata(item_id, item)

        def status_cb(label: str) -> None:
            self._record_status(item_id, label)

        def step_cb(step: StepResult) -> None:
            self._record_step(item_id, step)

        def progress_cb(update: dict[str, Any]) -> None:
            self._record_progress(item_id, update)

        try:
            paths = run_download(
                url,
                output_dir=self._settings.output_dir,
                audio=self._settings.audio,
                override_audio_format=self._settings.override_audio_format,
                override_video_format=self._settings.override_video_format,
                resolver=self._settings.resolver,
                interactive=self._settings.interactive,
                cookies=self._settings.cookies,
                cookies_from_browser=self._settings.cookies_from_browser,
                ui=ui,
                prefer_mp3_mp4=self._settings.prefer_mp3_mp4,
                show_file_size=False,
                show_stage=False,
                metadata_callback=metadata_cb,
                status_callback=status_cb,
                step_callback=step_cb,
                progress_callback=progress_cb,
            )
        except RipmediaError as e:
            self._update(item_id, status="error", error=str(e))
            self._broker.publish(
                {"type": "error", "id": item_id, "message": str(e), "stage": e.stage}
            )
            return
        except Exception as e:  # noqa: BLE001
            self._update(item_id, status="error", error=str(e))
            self._broker.publish({"type": "error", "id": item_id, "message": str(e)})
            return

        duration = monotonic() - start
        path_strings = []
        for p in paths:
            try:
                path_strings.append(str(p.resolve()))
            except Exception:
                path_strings.append(str(p))
        self._update(item_id, status="done", paths=path_strings)
        self._broker.publish(
            {"type": "done", "id": item_id, "paths": path_strings, "duration": duration}
        )


class WebHandler(BaseHTTPRequestHandler):
    server_version = "ripmedia"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/events":
            return self._handle_events()
        if path == "/state":
            return self._handle_state()
        asset = self.server.assets.get(path)  # type: ignore[attr-defined]
        if asset is None and path in {"", "/"}:
            asset = self.server.assets.get("/index.html")  # type: ignore[attr-defined]
        if asset is None:
            self.send_response(404)
            self.end_headers()
            return
        body, mime = asset
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/enqueue":
            return self._handle_enqueue()
        if path == "/open":
            return self._handle_open()
        self.send_response(404)
        self.end_headers()
        return

    def _handle_enqueue(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
        urls: list[str] = []
        if "application/json" in (self.headers.get("Content-Type") or ""):
            try:
                payload = json.loads(raw)
                urls = payload.get("urls", [])
            except json.JSONDecodeError:
                urls = []
        else:
            urls = [line.strip() for line in raw.splitlines() if line.strip()]

        urls = [u for u in urls if u]
        manager = self.server.manager  # type: ignore[attr-defined]
        manager.enqueue(expand_url_args(urls))
        resp = json.dumps({"queued": len(urls)})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp.encode("utf-8"))

    def _handle_open(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
        target = None
        try:
            payload = json.loads(raw)
            target = payload.get("path")
        except json.JSONDecodeError:
            target = None
        if not target:
            self.send_response(400)
            self.end_headers()
            return

        settings = self.server.settings  # type: ignore[attr-defined]
        resolved = Path(target).expanduser().resolve()
        base = settings.output_dir.expanduser().resolve()
        if not _is_safe_path(base, resolved):
            self.send_response(403)
            self.end_headers()
            return

        _open_in_explorer(resolved)
        self.send_response(204)
        self.end_headers()

    def _handle_state(self) -> None:
        manager = self.server.manager  # type: ignore[attr-defined]
        payload = json.dumps({"items": manager.snapshot()})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload.encode("utf-8"))

    def _handle_events(self) -> None:
        broker: EventBroker = self.server.broker  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = broker.subscribe()
        try:
            while True:
                try:
                    message = q.get(timeout=10)
                    payload = message.encode("utf-8")
                except queue.Empty:
                    payload = b": ping\n\n"
                try:
                    self.wfile.write(payload)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    break
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            broker.unsubscribe(q)


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):  # noqa: ARG002
        exc_type, exc, _ = sys.exc_info()
        if exc_type and issubclass(exc_type, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        return super().handle_error(request, client_address)


def run_webhost(
    *,
    host: str,
    port: int,
    parallel: int,
    settings: WebSettings,
    open_browser: bool,
) -> None:
    assets = _load_assets()
    broker = EventBroker()
    manager = DownloadManager(broker=broker, settings=settings, parallel=parallel)

    server = QuietThreadingHTTPServer((host, port), WebHandler)
    server.assets = assets  # type: ignore[attr-defined]
    server.broker = broker  # type: ignore[attr-defined]
    server.manager = manager  # type: ignore[attr-defined]
    server.settings = settings  # type: ignore[attr-defined]
    server.daemon_threads = True
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}"
    if open_browser:
        webbrowser.open(url)
    print(f"Webhost running at {url}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        manager.shutdown()


def _load_assets() -> dict[str, tuple[bytes, str]]:
    files = resources.files("ripmedia.web")
    index = files.joinpath("index.html").read_text(encoding="utf-8")
    css = files.joinpath("style.css").read_text(encoding="utf-8")
    js = files.joinpath("app.js").read_text(encoding="utf-8")
    return {
        "/index.html": (index.encode("utf-8"), "text/html; charset=utf-8"),
        "/style.css": (css.encode("utf-8"), "text/css; charset=utf-8"),
        "/app.js": (js.encode("utf-8"), "text/javascript; charset=utf-8"),
    }


def _format_speed(speed_bps: float, unit: str) -> str:
    if unit == "Mbps":
        value = (float(speed_bps) * 8) / 1_000_000
        suffix = "Mb/s"
    else:
        value = float(speed_bps) / 1_000_000
        suffix = "MB/s"
    return f"{value:>5.1f} {suffix}"


def _open_in_explorer(path: Path) -> None:
    target = path if path.is_dir() else path.parent
    if os.name == "nt":
        os.startfile(str(target))
    elif sys.platform == "darwin":
        subprocess.run(["open", str(target)], check=False)
    else:
        subprocess.run(["xdg-open", str(target)], check=False)


def _is_safe_path(base: Path, target: Path) -> bool:
    try:
        return target.is_relative_to(base)
    except AttributeError:
        return str(target).startswith(str(base))
