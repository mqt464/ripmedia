from __future__ import annotations

import json
import os
import re
import textwrap
from pathlib import Path
from time import monotonic
from typing import Annotated

import click
import typer
from rich.console import Console

from .ui import StepResult
from .config import coerce_value, get_config_path, load_config, open_config, set_config_value, update_config
from .errors import PartialSuccessError, RipmediaError
from .model import LogLevel
from .pipeline import run_download, run_info
from .urls import expand_url_args
from .cookies import CookieProfile, discover_cookie_profiles, format_cookie_spec
from .plugin_system import HookContext, load_plugins, get_plugin_dir
from .shared import NoopLogger
from .ytdlp_utils import normalize_cookies_from_browser


class DefaultToDownloadGroup(typer.core.TyperGroup):
    def resolve_command(self, ctx: click.Context, args: list[str]):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            if not args:
                raise
            default_cmd_name = "download"
            default_cmd = self.get_command(ctx, default_cmd_name)
            if default_cmd is None:
                raise
            return default_cmd_name, default_cmd, args


app = typer.Typer(
    add_completion=False,
    help="ripmedia — metadata-first media ingestion CLI.",
    cls=DefaultToDownloadGroup,
    no_args_is_help=False,
    invoke_without_command=True,
)

cookies_app = typer.Typer(
    add_completion=False,
    help="Cookies helpers (auto-detect browser profiles).",
    invoke_without_command=True,
)

app.add_typer(cookies_app, name="cookies")

plugins_app = typer.Typer(
    add_completion=False,
    help="Manage local plugins.",
    invoke_without_command=True,
)

app.add_typer(plugins_app, name="plugins")

PLUGIN_REGISTRY = load_plugins()
for plugin in PLUGIN_REGISTRY.plugins:
    if plugin.app is not None:
        app.add_typer(plugin.app, name=plugin.name)


def _make_ui(*, level: LogLevel, no_color: bool, print_path_only: bool, speed_unit: str):
    from .ui import Ui

    console = Console(no_color=no_color, highlight=False, soft_wrap=True)
    return Ui(console=console, level=level, print_path_only=print_path_only, speed_unit=speed_unit)


def _default_output_dir() -> Path:
    downloads = Path.home() / "Downloads"
    if downloads.exists():
        return downloads
    return Path("output")


AudioOption = Annotated[bool, typer.Option("--audio", help="Extract/best audio output.")]
AudioFormatOption = Annotated[
    str | None, typer.Option("--audio-format", help="Override audio output format (e.g. mp3).")
]
VideoFormatOption = Annotated[
    str | None, typer.Option("--video-format", help="Override video output format (e.g. mp4).")
]
Mp3Option = Annotated[bool, typer.Option("--mp3", help="Shorthand for --audio-format mp3.")]
OutputDirOption = Annotated[Path, typer.Option("--output-dir", help="Base output directory.")]
CookiesOption = Annotated[
    Path | None, typer.Option("--cookies", help="Path to a Netscape cookies.txt file.")
]
CookiesFromBrowserOption = Annotated[
    str | None,
    typer.Option(
        "--cookies-from-browser",
        help="Load cookies from a browser profile (yt-dlp format).",
    ),
]
ResolverOption = Annotated[
    str,
    typer.Option(
        "--resolver",
        help="Resolver provider for Spotify items (youtube|soundcloud).",
        case_sensitive=False,
    ),
]
VerboseOption = Annotated[bool, typer.Option("-v", "--verbose", help="Show decision details.")]
DebugOption = Annotated[bool, typer.Option("--debug", help="Show raw tool logs + stack traces.")]
QuietOption = Annotated[bool, typer.Option("--quiet", help="Only print errors.")]
PrintPathOption = Annotated[
    bool, typer.Option("--print-path", help="Print only final path(s) on success.")
]
NoColorOption = Annotated[bool, typer.Option("--no-color", help="Disable colored output.")]
InteractiveOption = Annotated[
    bool, typer.Option("--interactive", help="Allow prompts (resolver selection).")
]
SpeedUnitOption = Annotated[
    str,
    typer.Option("--speed-unit", help="Speed unit: mb/s (bytes) or mbp/s (bits)."),
]
InstallSystemOption = Annotated[
    bool,
    typer.Option(
        "--install-system/--no-install-system",
        help="Install missing system dependencies when possible (Windows only).",
    ),
]
GitPullOption = Annotated[
    bool,
    typer.Option("--git-pull/--no-git-pull", help="Pull latest changes if running from git."),
]


@app.callback()
def _global_options(
    ctx: typer.Context,
    audio: AudioOption = False,
    override_audio_format: AudioFormatOption = None,
    override_video_format: VideoFormatOption = None,
    mp3: Mp3Option = False,
    output_dir: OutputDirOption = _default_output_dir(),
    cookies: CookiesOption = None,
    cookies_from_browser: CookiesFromBrowserOption = None,
    resolver: ResolverOption = "youtube",
    verbose: VerboseOption = False,
    debug: DebugOption = False,
    quiet: QuietOption = False,
    print_path: PrintPathOption = False,
    no_color: NoColorOption = False,
    interactive: InteractiveOption = False,
    speed_unit: SpeedUnitOption = "MBps",
) -> None:
    _ = (
        ctx,
        audio,
        override_audio_format,
        override_video_format,
        mp3,
        output_dir,
        cookies,
        cookies_from_browser,
        resolver,
        verbose,
        debug,
        quiet,
        print_path,
        no_color,
        interactive,
        speed_unit,
    )
    config_path = get_config_path()
    ctx.obj = ctx.obj or {}
    ctx.obj["config_path"] = config_path
    ctx.obj["config"] = load_config(config_path)
    if ctx.invoked_subcommand is None and not ctx.args:
        _print_help(Console(no_color=no_color, highlight=False, soft_wrap=True))
        raise typer.Exit()


def _is_commandline(ctx: typer.Context | None, name: str) -> bool:
    if ctx is None:
        return False
    try:
        src = ctx.get_parameter_source(name)
    except Exception:  # noqa: BLE001
        return False
    return src == click.core.ParameterSource.COMMANDLINE


def _get_config(ctx: typer.Context) -> tuple[dict[str, str], Path | None]:
    root = ctx
    while root.parent is not None:
        root = root.parent
    obj = root.obj or {}
    return obj.get("config", {}), obj.get("config_path")


def _resolve_option(ctx: typer.Context | None, name: str, current):
    if _is_commandline(ctx, name):
        return current
    if ctx is None:
        return current
    parent = ctx.parent
    if parent is not None and _is_commandline(parent, name) and name in parent.params:
        return parent.params[name]
    config, config_path = _get_config(ctx)
    if config and name in config:
        try:
            value = coerce_value(name, config[name])
        except ValueError as e:
            hint = f" (config: {config_path})" if config_path else ""
            raise typer.BadParameter(
                f"{e}{hint}",
                param_hint=f"--{name.replace('_', '-')}",
            ) from e
        if value is not None:
            return value
    return current


def _normalize_format(value: str | None, *, param_hint: str) -> str | None:
    if value is None:
        return None
    v = str(value).strip().lower()
    if not v or v in {"false", "none", "null"}:
        return None
    v = v.lstrip(".")
    if not v:
        return None
    if not re.fullmatch(r"[a-z0-9]+", v):
        raise typer.BadParameter(
            f"Invalid format: {value}",
            param_hint=param_hint,
        )
    return v


def _normalize_resolver(value: str, *, strict: bool) -> str:
    resolver_norm = str(value).strip().lower()
    if resolver_norm in {"yt", "youtube"}:
        return "youtube"
    if resolver_norm in {"sc", "soundcloud"}:
        return "soundcloud"
    if strict:
        raise typer.BadParameter(
            "Invalid --resolver. Use 'youtube' or 'soundcloud'.",
            param_hint="--resolver",
        )
    return "youtube"


def _print_help(console: Console) -> None:
    console.print("ripmedia — metadata-first media ingestion CLI.")
    console.print("")
    console.print("[dim]Usage[/dim]")
    console.print("  ripmedia <url...>")
    console.print("  ripmedia download <url...>")
    console.print("  ripmedia info <url>")
    console.print("  ripmedia update")
    console.print("  ripmedia config [update|key=value]")
    console.print("  ripmedia cookies")
    console.print("  ripmedia cookies refresh")
    console.print("  ripmedia plugins")
    console.print("  ripmedia webhost")
    console.print("  ripmedia help")
    console.print("")
    console.print("[dim]Commands[/dim]")
    console.print("  download   Download media (default)")
    console.print("  info       Show metadata")
    console.print("  update     Update tool and dependencies")
    console.print("  config     Open or edit config")
    console.print("  cookies    Manage browser cookies")
    console.print("  plugins    Manage local plugins")
    console.print("  webhost    Local web UI")
    console.print("  help       Show this help")
    console.print("")
    console.print("[dim]Common options[/dim]")
    console.print("  --audio, --audio-format, --video-format, --mp3")
    console.print("  --output-dir, --cookies, --cookies-from-browser")
    console.print("  --resolver, --interactive")
    console.print("  --print-path, --quiet, --verbose, --debug, --no-color")
    console.print("  --speed-unit")
    console.print("")
    console.print("[dim]Examples[/dim]")
    console.print('  ripmedia "https://youtu.be/..."')
    console.print('  ripmedia info "https://..."')
    console.print("  ripmedia config update")
    console.print("  ripmedia webhost")


@app.command()
def config(
    setting: Annotated[
        str | None,
        typer.Argument(help="Open config, or set a value with key=value."),
    ] = None,
) -> None:
    path = get_config_path()
    if setting is None:
        open_config(path)
        return
    if setting.strip().lower() == "update":
        added, removed = update_config(path)
        config = load_config(path)
        no_color = False
        if "no_color" in config:
            try:
                no_color = bool(coerce_value("no_color", config["no_color"]))
            except ValueError:
                no_color = False
        console = Console(no_color=no_color, highlight=False, soft_wrap=True)
        console.print(f"[green]Config updated[/green] [dim](added {added}, removed {removed})[/dim]")
        console.print(f"[dim]{path}[/dim]")
        return
    if "=" not in setting:
        raise typer.BadParameter("Use key=value.", param_hint="SETTING")
    key, value = setting.split("=", 1)
    if not key.strip():
        raise typer.BadParameter("Key cannot be empty.", param_hint="SETTING")
    set_config_value(path, key, value.strip())
    typer.echo(f"Updated {path}: {key.strip().lower().replace('-', '_')}={value.strip()}")


@cookies_app.callback(invoke_without_command=True)
def cookies_root(
    ctx: typer.Context,
    no_color: NoColorOption = False,
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    _run_cookies_select(ctx, no_color=no_color)


@cookies_app.command("refresh")
def cookies_refresh(
    ctx: typer.Context,
    no_color: NoColorOption = False,
) -> None:
    _run_cookies_refresh(ctx, no_color=no_color)


@plugins_app.callback(invoke_without_command=True)
def plugins_root(
    ctx: typer.Context,
    no_color: NoColorOption = False,
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    _plugins_list(ctx, no_color=no_color)


@plugins_app.command("list")
def plugins_list(
    ctx: typer.Context,
    no_color: NoColorOption = False,
) -> None:
    _plugins_list(ctx, no_color=no_color)


@plugins_app.command("enable")
def plugins_enable(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Plugin name to enable.")],
    no_color: NoColorOption = False,
) -> None:
    _plugins_toggle(ctx, name=name, enable=True, no_color=no_color)


@plugins_app.command("disable")
def plugins_disable(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Plugin name to disable.")],
    no_color: NoColorOption = False,
) -> None:
    _plugins_toggle(ctx, name=name, enable=False, no_color=no_color)


@plugins_app.command("remove")
def plugins_remove(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Plugin name to remove.")],
    no_color: NoColorOption = False,
) -> None:
    _plugins_remove(ctx, name=name, no_color=no_color)


@plugins_app.command("init")
def plugins_init(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Plugin name to create.")],
    no_color: NoColorOption = False,
) -> None:
    _plugins_init(ctx, name=name, no_color=no_color)


def _run_cookies_select(ctx: typer.Context, *, no_color: bool) -> None:
    config, config_path = _get_config(ctx)
    ui = _make_ui(level="normal", no_color=no_color, print_path_only=False, speed_unit="MBps")

    cookies_value = config.get("cookies")
    if cookies_value:
        try:
            cookies_path = coerce_value("cookies", cookies_value)
        except ValueError:
            cookies_path = None
        if isinstance(cookies_path, Path) and cookies_path.exists():
            ui.status("Cookies", True, f"Using {ui.path_link(cookies_path)}")
            return

    candidates = _scan_cookie_profiles(ui)
    if not candidates:
        ui.error("No browser profiles found.")
        raise typer.Exit(1)

    selected = _prompt_cookie_profile(ui, candidates, default_spec=config.get("cookies_from_browser"))
    if config_path is not None:
        set_config_value(config_path, "cookies_from_browser", format_cookie_spec(selected.spec))
    ui.status("Cookies", True, f"Using {selected.browser_label} · {selected.profile or 'Default'}")


def _run_cookies_refresh(ctx: typer.Context, *, no_color: bool) -> None:
    config, config_path = _get_config(ctx)
    ui = _make_ui(level="normal", no_color=no_color, print_path_only=False, speed_unit="MBps")

    cookies_path = None
    if "cookies" in config:
        try:
            cookies_path = coerce_value("cookies", config["cookies"])
        except ValueError:
            cookies_path = None
    if not isinstance(cookies_path, Path):
        cookies_path = Path.home() / ".ripmedia" / "cookies.txt"

    candidates = _scan_cookie_profiles(ui)
    if not candidates:
        ui.error("No browser profiles found.")
        raise typer.Exit(1)

    selected = _prompt_cookie_profile(ui, candidates, default_spec=config.get("cookies_from_browser"))

    def _export() -> StepResult:
        from yt_dlp import YoutubeDL

        cookies_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            ydl = YoutubeDL(
                {
                    "cookiesfrombrowser": selected.spec,
                    "quiet": True,
                    "no_warnings": True,
                    "logger": NoopLogger(),
                }
            )
            jar = ydl.cookiejar
            jar.save(str(cookies_path), ignore_discard=True, ignore_expires=True)
            return StepResult(label="Export cookies", ok=True, detail=str(cookies_path))
        except Exception as e:  # noqa: BLE001
            detail = _clean_cookie_error(str(e))
            return StepResult(label="Export cookies", ok=False, detail=detail)

    results = ui.run_steps([("Export cookies", _export)], show_description=False)
    if not results or not results[-1].ok:
        raise typer.Exit(1)
    if config_path is not None:
        set_config_value(config_path, "cookies_from_browser", format_cookie_spec(selected.spec))
    if config_path is not None:
        set_config_value(config_path, "cookies", str(cookies_path))
    ui.status("Cookies", True, f"Saved {ui.path_link(cookies_path)}")


def _scan_cookie_profiles(ui) -> list[CookieProfile]:
    candidates: list[CookieProfile] = []

    def _scan() -> StepResult:
        nonlocal candidates
        candidates = discover_cookie_profiles()
        ok = bool(candidates)
        detail = f"{len(candidates)} found" if ok else "none found"
        return StepResult(label="Scan browsers", ok=ok, detail=detail)

    ui.run_steps([("Scan browsers", _scan)], show_description=False)
    return candidates


def _prompt_cookie_profile(
    ui,
    candidates: list[CookieProfile],
    *,
    default_spec: str | None,
) -> CookieProfile:
    if len(candidates) == 1:
        return candidates[0]

    default_idx = _default_candidate_index(candidates, default_spec)
    ui.section("Select profile")
    for idx, candidate in enumerate(candidates, start=1):
        marker = "[cyan]>[/cyan]" if idx == default_idx else "[dim]·[/dim]"
        suffix = " [dim](default)[/dim]" if idx == default_idx else ""
        ui.console.print(f"{marker} [dim]{idx}[/dim] {candidate.display}{suffix}")

    raw = ui.console.input(f"Select profile [{default_idx}]: ").strip()
    if not raw:
        return candidates[default_idx - 1]
    try:
        choice = int(raw)
    except ValueError as e:
        ui.error("Invalid selection.")
        raise typer.Exit(2) from e
    if choice < 1 or choice > len(candidates):
        ui.error("Selection out of range.")
        raise typer.Exit(2)
    return candidates[choice - 1]


def _default_candidate_index(candidates: list[CookieProfile], spec_value: str | None) -> int:
    if not spec_value:
        return 1
    spec = normalize_cookies_from_browser(spec_value)
    if not spec:
        return 1
    spec_key = _spec_key(spec)
    for idx, candidate in enumerate(candidates, start=1):
        if _spec_key(candidate.spec) == spec_key:
            return idx
    return 1


def _spec_key(spec: tuple) -> tuple[str, ...]:
    parts: list[str] = []
    for part in spec:
        if part is None:
            continue
        text = str(part)
        if ":\\" in text or "\\" in text or "/" in text:
            text = os.path.normcase(text)
        parts.append(text.lower())
    return tuple(parts)


def _plugins_list(ctx: typer.Context, *, no_color: bool) -> None:
    ui = _make_ui(level="normal", no_color=no_color, print_path_only=False, speed_unit="MBps")
    plugin_dir = get_plugin_dir()
    if not plugin_dir.exists():
        ui.status("Plugins", True, f"No plugins yet. Create in {ui.path_link(plugin_dir)}")
        return
    if not PLUGIN_REGISTRY.plugins:
        ui.status("Plugins", True, "No plugins found.")
        return
    ui.section("Plugins")
    for info in PLUGIN_REGISTRY.plugins:
        label = info.name
        if not info.enabled:
            ui.console.print(f"[dim]·[/dim] {label} [dim](disabled)[/dim]")
            continue
        if info.error:
            ui.console.print(f"[red]![/red] {label} [dim]{info.error}[/dim]")
        else:
            ui.console.print(f"[green]●[/green] {label} [dim]enabled[/dim]")


def _plugins_toggle(ctx: typer.Context, *, name: str, enable: bool, no_color: bool) -> None:
    ui = _make_ui(level="normal", no_color=no_color, print_path_only=False, speed_unit="MBps")
    plugin_dir = get_plugin_dir()
    plugin_dir.mkdir(parents=True, exist_ok=True)
    target = None
    for path in plugin_dir.glob("*.py"):
        if path.stem == name or path.stem == f"{name}.disabled":
            target = path
            break
    for path in plugin_dir.glob("*.disabled.py"):
        if path.name == f"{name}.disabled.py":
            target = path
            break
    if target is None:
        ui.error("Plugin not found.")
        raise typer.Exit(1)
    if enable:
        if target.name.endswith(".disabled.py"):
            new_path = target.with_name(target.name.replace(".disabled.py", ".py"))
            target.rename(new_path)
        ui.status("Plugins", True, f"Enabled {name}")
    else:
        if target.name.endswith(".py") and not target.name.endswith(".disabled.py"):
            new_path = target.with_name(f"{name}.disabled.py")
            target.rename(new_path)
        ui.status("Plugins", True, f"Disabled {name}")


def _plugins_remove(ctx: typer.Context, *, name: str, no_color: bool) -> None:
    ui = _make_ui(level="normal", no_color=no_color, print_path_only=False, speed_unit="MBps")
    plugin_dir = get_plugin_dir()
    removed = False
    for path in plugin_dir.glob(f"{name}.py"):
        path.unlink(missing_ok=True)
        removed = True
    for path in plugin_dir.glob(f"{name}.disabled.py"):
        path.unlink(missing_ok=True)
        removed = True
    if not removed:
        ui.error("Plugin not found.")
        raise typer.Exit(1)
    ui.status("Plugins", True, f"Removed {name}")


def _plugins_init(ctx: typer.Context, *, name: str, no_color: bool) -> None:
    ui = _make_ui(level="normal", no_color=no_color, print_path_only=False, speed_unit="MBps")
    plugin_dir = get_plugin_dir()
    plugin_dir.mkdir(parents=True, exist_ok=True)
    target = plugin_dir / f"{name}.py"
    if target.exists():
        ui.error("Plugin already exists.")
        raise typer.Exit(1)
    template = _plugin_template(name)
    target.write_text(template, encoding="utf-8")
    ui.status("Plugins", True, f"Created {ui.path_link(target)}")


def _plugin_template(name: str) -> str:
    safe = re.sub(r"[^a-z0-9_\-]", "_", name.lower())
    template = f"""
from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from urllib import request

from ripmedia.pipeline import run_download
from ripmedia.config import get_config_path, load_config, coerce_value

PLUGIN_NAME = "{safe}"


def register(plugin):
    @plugin.command("send", help="Download then send to Discord webhook.")
    def send(url: str, audio: bool = False, mp3: bool = False):
        config = load_config(get_config_path())
        webhook = config.get("discord_webhook")
        if not webhook:
            raise SystemExit("Set discord_webhook in config.ini")
        output_dir = coerce_value("output_dir", config.get("output_dir", "output"))
        speed_unit = coerce_value("speed_unit", config.get("speed_unit", "MBps")) or "MBps"
        no_color = bool(coerce_value("no_color", config.get("no_color", False)))
        ui = plugin.make_ui(no_color=no_color, speed_unit=str(speed_unit))
        if mp3:
            audio = True
            override_audio_format = "mp3"
        else:
            override_audio_format = None
        paths = run_download(
            url,
            output_dir=output_dir,
            audio=audio,
            override_audio_format=override_audio_format,
            override_video_format=None,
            resolver=config.get("resolver", "youtube"),
            interactive=False,
            cookies=coerce_value("cookies", config.get("cookies")),
            cookies_from_browser=config.get("cookies_from_browser"),
            ui=ui,
            prefer_mp3_mp4=True,
            show_file_size=False,
            show_stage=True,
        )
        _send_file(webhook, paths[0])
        ui.status("Discord", True, f"Uploaded {{ui.path_link(paths[0])}}")


def _send_file(webhook: str, path: Path) -> None:
    boundary = uuid.uuid4().hex
    filename = path.name
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with path.open("rb") as f:
        data = f.read()
    body = b"".join(
        [
            f"--{{boundary}}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{{filename}}"\r\n'.encode(),
            f"Content-Type: {{mime}}\r\n\r\n".encode(),
            data,
            b"\r\n",
            f"--{{boundary}}--\r\n".encode(),
        ]
    )
    req = request.Request(webhook, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={{boundary}}")
    request.urlopen(req).read()
"""
    return textwrap.dedent(template).lstrip()


def _clean_cookie_error(message: str) -> str:
    msg = message.replace("ERROR:", "").strip()
    lower = msg.lower()
    if "could not copy chrome cookie database" in lower:
        return "Close Helium and retry."
    return msg or "Cookie export failed."


@app.command()
def help(
    no_color: NoColorOption = False,
) -> None:
    _print_help(Console(no_color=no_color, highlight=False, soft_wrap=True))


@app.command()
def webhost(
    ctx: typer.Context,
    port: Annotated[int | None, typer.Option("--port", help="Port to bind (0 = auto).")] = None,
    parallel: Annotated[int, typer.Option("--parallel", help="Parallel downloads.")] = 2,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the web UI in your browser.")
    ] = True,
) -> None:
    from .webhost import WebSettings, run_webhost

    config, _ = _get_config(ctx)

    def _cfg(key: str, default):
        if key in config:
            try:
                value = coerce_value(key, config[key])
            except ValueError:
                return default
            if value is not None:
                return value
        return default

    output_dir = _cfg("output_dir", _default_output_dir())
    audio = _cfg("audio", False)
    override_audio_format = _cfg("override_audio_format", None)
    override_video_format = _cfg("override_video_format", None)
    resolver = _cfg("resolver", "youtube")
    cookies = _cfg("cookies", None)
    cookies_from_browser = _cfg("cookies_from_browser", None)
    interactive = False
    prefer_mp3_mp4 = _cfg("prefer_mp3_mp4", True)
    speed_unit = _cfg("speed_unit", "MBps")
    web_port = _cfg("web_port", 0)

    if port is None:
        port = int(web_port) if isinstance(web_port, int) else 0

    resolver_norm = _normalize_resolver(str(resolver), strict=False)

    settings = WebSettings(
        output_dir=output_dir,
        audio=audio,
        override_audio_format=override_audio_format,
        override_video_format=override_video_format,
        resolver=resolver_norm,
        interactive=bool(interactive),
        cookies=cookies,
        cookies_from_browser=cookies_from_browser,
        prefer_mp3_mp4=bool(prefer_mp3_mp4),
        speed_unit=str(speed_unit),
    )

    run_webhost(
        host="127.0.0.1",
        port=int(port),
        parallel=int(parallel),
        settings=settings,
        open_browser=open_browser,
    )


@app.command()
def download(
    ctx: typer.Context,
    urls: Annotated[list[str], typer.Argument(help="URL(s) or a urls.txt file.")],
    audio: AudioOption = False,
    override_audio_format: AudioFormatOption = None,
    override_video_format: VideoFormatOption = None,
    mp3: Mp3Option = False,
    output_dir: OutputDirOption = _default_output_dir(),
    cookies: CookiesOption = None,
    cookies_from_browser: CookiesFromBrowserOption = None,
    resolver: ResolverOption = "youtube",
    verbose: VerboseOption = False,
    debug: DebugOption = False,
    quiet: QuietOption = False,
    print_path: PrintPathOption = False,
    no_color: NoColorOption = False,
    interactive: InteractiveOption = False,
    speed_unit: SpeedUnitOption = "MBps",
) -> None:
    config_snapshot, _ = _get_config(ctx)
    audio = _resolve_option(ctx, "audio", audio)
    override_audio_format = _resolve_option(ctx, "override_audio_format", override_audio_format)
    override_video_format = _resolve_option(ctx, "override_video_format", override_video_format)
    output_dir = _resolve_option(ctx, "output_dir", output_dir)
    cookies = _resolve_option(ctx, "cookies", cookies)
    cookies_from_browser = _resolve_option(ctx, "cookies_from_browser", cookies_from_browser)
    resolver = _resolve_option(ctx, "resolver", resolver)
    prefer_mp3_mp4 = _resolve_option(ctx, "prefer_mp3_mp4", True)
    verbose = _resolve_option(ctx, "verbose", verbose)
    debug = _resolve_option(ctx, "debug", debug)
    quiet = _resolve_option(ctx, "quiet", quiet)
    print_path = _resolve_option(ctx, "print_path", print_path)
    no_color = _resolve_option(ctx, "no_color", no_color)
    interactive = _resolve_option(ctx, "interactive", interactive)
    speed_unit = _resolve_option(ctx, "speed_unit", speed_unit)
    speed_unit = coerce_value("speed_unit", str(speed_unit)) or "MBps"
    show_file_size = _resolve_option(ctx, "show_file_size", False)

    if mp3:
        audio_format_cli = _is_commandline(ctx, "override_audio_format") or _is_commandline(
            ctx.parent, "override_audio_format"
        )
        if audio_format_cli:
            normalized = _normalize_format(override_audio_format, param_hint="--audio-format")
            if normalized and normalized != "mp3":
                raise typer.BadParameter(
                    "Conflicting audio format. Use --audio-format mp3 or remove --mp3.",
                    param_hint="--mp3",
                )
        override_audio_format = "mp3"
        audio = True

    override_audio_format = _normalize_format(override_audio_format, param_hint="--audio-format")
    override_video_format = _normalize_format(override_video_format, param_hint="--video-format")
    if override_audio_format:
        audio = True

    resolver_norm = _normalize_resolver(str(resolver), strict=True)

    ui = _make_ui(
        level=_level_from_flags(quiet=quiet, verbose=verbose, debug=debug),
        no_color=no_color,
        print_path_only=print_path,
        speed_unit=speed_unit,
    )
    expanded = expand_url_args(list(urls))
    _download_many(
        expanded,
        audio=audio,
        override_audio_format=override_audio_format,
        override_video_format=override_video_format,
        output_dir=output_dir,
        cookies=cookies,
        cookies_from_browser=cookies_from_browser,
        resolver=resolver_norm,
        interactive=interactive,
        ui=ui,
        prefer_mp3_mp4=prefer_mp3_mp4,
        show_file_size=bool(show_file_size),
        config_snapshot=config_snapshot,
    )


@app.command()
def info(
    ctx: typer.Context,
    url: Annotated[str, typer.Argument(help="URL to inspect.")],
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON for scripting.")] = False,
    no_color: NoColorOption = False,
) -> None:
    no_color = _resolve_option(ctx, "no_color", no_color)
    speed_unit = coerce_value("speed_unit", str(_resolve_option(ctx, "speed_unit", "MBps"))) or "MBps"
    cookies = _resolve_option(ctx, "cookies", None)
    cookies_from_browser = _resolve_option(ctx, "cookies_from_browser", None)
    ui = _make_ui(level="normal", no_color=no_color, print_path_only=False, speed_unit=speed_unit)
    try:
        item = run_info(
            url,
            ui=ui,
            cookies=cookies,
            cookies_from_browser=cookies_from_browser,
        )
    except RipmediaError as e:
        ui.error(f"{e.stage + ': ' if e.stage else ''}{e}")
        raise typer.Exit(2) from e

    if json_out:
        ui.console.print(json.dumps(item.to_json(), indent=2, ensure_ascii=False))
        return

    ui.console.print(f"[bold]Provider:[/bold] {item.provider.value}")
    ui.console.print(f"[bold]Kind:[/bold] {item.kind.value}")
    if item.title:
        ui.console.print(f"[bold]Title:[/bold] {item.title}")
    if item.artist:
        ui.console.print(f"[bold]Artist:[/bold] {item.artist}")
    if item.album:
        ui.console.print(f"[bold]Album:[/bold] {item.album}")
    if item.duration_seconds:
        ui.console.print(f"[bold]Duration:[/bold] {item.duration_seconds}s")
    if item.artwork_url:
        ui.console.print(f"[bold]Artwork:[/bold] {item.artwork_url}")


@app.command()
def update(
    install_system: InstallSystemOption = True,
    git_pull: GitPullOption = True,
    verbose: VerboseOption = False,
    debug: DebugOption = False,
    quiet: QuietOption = False,
    no_color: NoColorOption = False,
    speed_unit: SpeedUnitOption = "MBps",
) -> None:
    from .update import run_update

    speed_unit = coerce_value("speed_unit", str(_resolve_option(None, "speed_unit", speed_unit))) or "MBps"
    ui = _make_ui(
        level=_level_from_flags(quiet=quiet, verbose=verbose, debug=debug),
        no_color=no_color,
        print_path_only=False,
        speed_unit=speed_unit,
    )
    code = run_update(ui=ui, install_system=install_system, git_pull=git_pull)
    raise typer.Exit(code)


def _level_from_flags(*, quiet: bool, verbose: bool, debug: bool) -> LogLevel:
    if quiet:
        return "quiet"
    if debug:
        return "debug"
    if verbose:
        return "verbose"
    return "normal"


def _download_many(
    urls: list[str],
    *,
    audio: bool,
    override_audio_format: str | None,
    override_video_format: str | None,
    output_dir: Path,
    cookies: Path | None,
    cookies_from_browser: str | None,
    resolver: str,
    interactive: bool,
    ui,
    prefer_mp3_mp4: bool,
    show_file_size: bool,
    config_snapshot: dict[str, str],
) -> None:
    successes: list[Path] = []
    failures: list[tuple[str, str, str | None]] = []
    use_live = ui.level != "quiet" and not ui.print_path_only
    live = None
    progress = None
    task_id = None

    if use_live:
        progress = ui.progress(
            show_bytes=show_file_size,
            show_speed=True,
            show_description=False,
            transient=False,
        )
        task_id = progress.add_task("download", total=1.0)
        live = ui.live_progress(progress, max_log_lines=7)

    def _status_label(paths: list[Path], fallback: str) -> str:
        if paths:
            return paths[0].name
        return fallback

    def _record_result(label: str, ok: bool, detail: str | None, start_time: float) -> None:
        if live is None:
            return
        duration = monotonic() - start_time
        live.add_result(StepResult(label=label, ok=ok, detail=detail, duration_s=duration))

    def _emit(event: str, **kwargs) -> None:
        if PLUGIN_REGISTRY.hooks.get(event):
            PLUGIN_REGISTRY.emit(
                HookContext(
                    event=event,
                    url=kwargs.get("url"),
                    item=kwargs.get("item"),
                    paths=kwargs.get("paths"),
                    error=kwargs.get("error"),
                    stage=kwargs.get("stage"),
                    config=config_snapshot,
                    ui=ui,
                )
            )

    if live is None:
        for idx, url in enumerate(urls, start=1):
            if len(urls) > 1 and not use_live:
                ui.info(f"[dim]{idx}/{len(urls)}[/dim] {url}")
            start_time = monotonic()
            try:
                _emit("download_start", url=url)
                paths = run_download(
                    url,
                    output_dir=output_dir,
                    audio=audio,
                    override_audio_format=override_audio_format,
                    override_video_format=override_video_format,
                    resolver=resolver,
                    interactive=interactive,
                    cookies=cookies,
                    cookies_from_browser=cookies_from_browser,
                    ui=ui,
                    prefer_mp3_mp4=prefer_mp3_mp4,
                    show_file_size=show_file_size,
                    progress=progress,
                    progress_task_id=task_id,
                    live=live,
                    show_stage=not use_live,
                )
                successes.extend(paths)
                _record_result(_status_label(paths, url), True, None, start_time)
                _emit("download_complete", url=url, paths=paths)
            except PartialSuccessError as e:
                successes.extend(e.saved_paths)
                failures.extend(e.failures)
                _record_result(url, False, str(e), start_time)
                if e.saved_paths:
                    _emit("download_complete", url=url, paths=e.saved_paths)
                for f_url, msg, stage in e.failures:
                    _emit("download_error", url=f_url, error=Exception(msg), stage=stage)
                for f_url, msg, stage in e.failures:
                    ui.error(f"{stage + ': ' if stage else ''}{msg} ({f_url})")
                if e.failures:
                    _, msg, stage = e.failures[0]
                    hint = _hint_for_error(stage, msg)
                    if hint and ui.level != "quiet" and not ui.print_path_only:
                        ui.info(hint)
            except RipmediaError as e:
                msg = str(e)
                failures.append((url, msg, e.stage))
                _record_result(url, False, msg, start_time)
                _emit("download_error", url=url, error=e, stage=e.stage)
                ui.error(f"{e.stage + ': ' if e.stage else ''}{e}")
                hint = _hint_for_error(e.stage, str(e))
                if hint and ui.level != "quiet" and not ui.print_path_only:
                    ui.info(hint)
                continue
            except Exception as e:  # noqa: BLE001
                failures.append((url, str(e), None))
                _record_result(url, False, str(e), start_time)
                _emit("download_error", url=url, error=e, stage=None)
                if ui.level == "debug":
                    raise
                ui.error(str(e))
                hint = _hint_for_error(None, str(e))
                if hint and ui.level != "quiet" and not ui.print_path_only:
                    ui.info(hint)
    else:
        with live:
            for idx, url in enumerate(urls, start=1):
                if progress is not None and task_id is not None:
                    progress.update(task_id, item_index=idx, item_total=len(urls))
                start_time = monotonic()
                try:
                    _emit("download_start", url=url)
                    paths = run_download(
                        url,
                        output_dir=output_dir,
                        audio=audio,
                        override_audio_format=override_audio_format,
                        override_video_format=override_video_format,
                        resolver=resolver,
                        interactive=interactive,
                        cookies=cookies,
                        cookies_from_browser=cookies_from_browser,
                        ui=ui,
                        prefer_mp3_mp4=prefer_mp3_mp4,
                        show_file_size=show_file_size,
                        progress=progress,
                        progress_task_id=task_id,
                        live=live,
                        show_stage=False,
                    )
                    successes.extend(paths)
                    _record_result(_status_label(paths, url), True, None, start_time)
                    _emit("download_complete", url=url, paths=paths)
                except PartialSuccessError as e:
                    successes.extend(e.saved_paths)
                    failures.extend(e.failures)
                    _record_result(url, False, str(e), start_time)
                    if e.saved_paths:
                        _emit("download_complete", url=url, paths=e.saved_paths)
                    for f_url, msg, stage in e.failures:
                        _emit("download_error", url=f_url, error=Exception(msg), stage=stage)
                except RipmediaError as e:
                    msg = str(e)
                    failures.append((url, msg, e.stage))
                    _record_result(url, False, msg, start_time)
                    _emit("download_error", url=url, error=e, stage=e.stage)
                except Exception as e:  # noqa: BLE001
                    failures.append((url, str(e), None))
                    _record_result(url, False, str(e), start_time)
                    _emit("download_error", url=url, error=e, stage=None)
                    if ui.level == "debug":
                        raise
            live.clear_current()

    if failures and ui.level != "quiet" and not ui.print_path_only and not use_live:
        ui.info(f"[bold]Summary:[/bold] saved={len(successes)} failed={len(failures)}")
        max_list = 20
        for failed_url, msg, stage in failures[:max_list]:
            prefix = f"{stage}: " if stage else ""
            ui.info(f"[red]-[/red] {prefix}{msg} ({failed_url})")
        if len(failures) > max_list:
            ui.info(f"[dim]…and {len(failures) - max_list} more failures[/dim]")

    if ui.print_path_only:
        for p in successes:
            ui.console.print(ui.path_link(p))

    if use_live and ui.level != "quiet" and not ui.print_path_only:
        if failures:
            ui.error(f"{len(failures)} failed, {len(successes)} saved.")
        else:
            ui.info(f"[green]Download complete: {len(successes)} saved.[/green]")

    if failures and not successes:
        # Exit code contract:
        # - 2: invalid input/usage (e.g. unsupported URL/provider)
        # - 1: operational failure (network/tooling/etc)
        all_invalid = all(stage == "Detected" for _, __, stage in failures)
        raise typer.Exit(2 if all_invalid else 1)
    if failures:
        raise typer.Exit(1)


def _hint_for_error(stage: str | None, message: str) -> str | None:
    m = message.lower()
    hint = "[dim]Try running `ripmedia update`.[/dim]"
    if "no supported javascript runtime" in m or "js runtime" in m or "ejs" in m:
        return hint
    if "403" in m or "forbidden" in m:
        return hint
    if "ffmpeg" in m or "ffprobe" in m:
        return hint
    if stage == "Metadata" and ("spotify_client_id" in m or "spotify_client_secret" in m):
        return hint
    if stage == "Resolve" and "low confidence" in m:
        return hint
    if "cookies" in m and ("required" in m or "needed" in m):
        return hint
    return None
