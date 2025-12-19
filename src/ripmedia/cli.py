from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated

import click
import typer
from rich.console import Console

from .config import coerce_value, get_config_path, load_config, open_config, set_config_value
from .errors import PartialSuccessError, RipmediaError
from .model import LogLevel
from .pipeline import run_download, run_info
from .urls import expand_url_args


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
    no_args_is_help=True,
)


def _make_ui(*, level: LogLevel, no_color: bool, print_path_only: bool):
    from .ui import Ui

    console = Console(no_color=no_color, highlight=False, soft_wrap=True)
    return Ui(console=console, level=level, print_path_only=print_path_only)


def _default_output_dir() -> Path:
    downloads = Path.home() / "Downloads"
    if downloads.exists():
        return downloads
    return Path("output")


@app.callback()
def _global_options(
    ctx: typer.Context,
    audio: Annotated[bool, typer.Option("--audio", help="Extract/best audio output.")] = False,
    override_audio_format: Annotated[
        str | None, typer.Option("--audio-format", help="Override audio output format (e.g. mp3).")
    ] = None,
    override_video_format: Annotated[
        str | None, typer.Option("--video-format", help="Override video output format (e.g. mp4).")
    ] = None,
    mp3: Annotated[bool, typer.Option("--mp3", help="Shorthand for --audio-format mp3.")] = False,
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Base output directory.")
    ] = _default_output_dir(),
    cookies: Annotated[
        Path | None, typer.Option("--cookies", help="Path to a Netscape cookies.txt file.")
    ] = None,
    cookies_from_browser: Annotated[
        str | None,
        typer.Option(
            "--cookies-from-browser",
            help="Load cookies from a browser profile (yt-dlp format).",
        ),
    ] = None,
    resolver: Annotated[
        str,
        typer.Option(
            "--resolver",
            help="Resolver provider for Spotify items (youtube|soundcloud).",
            case_sensitive=False,
        ),
    ] = "youtube",
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Show decision details.")] = False,
    debug: Annotated[bool, typer.Option("--debug", help="Show raw tool logs + stack traces.")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", help="Only print errors.")] = False,
    print_path: Annotated[
        bool, typer.Option("--print-path", help="Print only final path(s) on success.")
    ] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="Disable colored output.")] = False,
    interactive: Annotated[
        bool, typer.Option("--interactive", help="Allow prompts (resolver selection).")
    ] = False,
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
    )
    config_path = get_config_path()
    ctx.obj = ctx.obj or {}
    ctx.obj["config_path"] = config_path
    ctx.obj["config"] = load_config(config_path)


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


def _resolve_option(ctx: typer.Context, name: str, current):
    if _is_commandline(ctx, name):
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
    if "=" not in setting:
        raise typer.BadParameter("Use key=value.", param_hint="SETTING")
    key, value = setting.split("=", 1)
    if not key.strip():
        raise typer.BadParameter("Key cannot be empty.", param_hint="SETTING")
    set_config_value(path, key, value.strip())
    typer.echo(f"Updated {path}: {key.strip().lower().replace('-', '_')}={value.strip()}")


@app.command()
def download(
    ctx: typer.Context,
    urls: Annotated[list[str], typer.Argument(help="URL(s) or a urls.txt file.")],
    audio: Annotated[bool, typer.Option("--audio", help="Extract/best audio output.")] = False,
    override_audio_format: Annotated[
        str | None, typer.Option("--audio-format", help="Override audio output format (e.g. mp3).")
    ] = None,
    override_video_format: Annotated[
        str | None, typer.Option("--video-format", help="Override video output format (e.g. mp4).")
    ] = None,
    mp3: Annotated[bool, typer.Option("--mp3", help="Shorthand for --audio-format mp3.")] = False,
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Base output directory.")
    ] = _default_output_dir(),
    cookies: Annotated[
        Path | None, typer.Option("--cookies", help="Path to a Netscape cookies.txt file.")
    ] = None,
    cookies_from_browser: Annotated[
        str | None,
        typer.Option(
            "--cookies-from-browser",
            help="Load cookies from a browser profile (yt-dlp format).",
        ),
    ] = None,
    resolver: Annotated[
        str,
        typer.Option("--resolver", help="Resolver provider for Spotify items (youtube|soundcloud)."),
    ] = "youtube",
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Show decision details.")] = False,
    debug: Annotated[bool, typer.Option("--debug", help="Show raw tool logs + stack traces.")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", help="Only print errors.")] = False,
    print_path: Annotated[
        bool, typer.Option("--print-path", help="Print only final path(s) on success.")
    ] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="Disable colored output.")] = False,
    interactive: Annotated[
        bool, typer.Option("--interactive", help="Allow prompts (resolver selection).")
    ] = False,
) -> None:
    audio = _resolve_option(ctx, "audio", audio)
    override_audio_format = _resolve_option(ctx, "override_audio_format", override_audio_format)
    override_video_format = _resolve_option(ctx, "override_video_format", override_video_format)
    output_dir = _resolve_option(ctx, "output_dir", output_dir)
    cookies = _resolve_option(ctx, "cookies", cookies)
    cookies_from_browser = _resolve_option(ctx, "cookies_from_browser", cookies_from_browser)
    resolver = _resolve_option(ctx, "resolver", resolver)
    verbose = _resolve_option(ctx, "verbose", verbose)
    debug = _resolve_option(ctx, "debug", debug)
    quiet = _resolve_option(ctx, "quiet", quiet)
    print_path = _resolve_option(ctx, "print_path", print_path)
    no_color = _resolve_option(ctx, "no_color", no_color)
    interactive = _resolve_option(ctx, "interactive", interactive)

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

    resolver_norm = str(resolver).strip().lower()
    if resolver_norm in {"yt", "youtube"}:
        resolver_norm = "youtube"
    elif resolver_norm in {"sc", "soundcloud"}:
        resolver_norm = "soundcloud"
    else:
        raise typer.BadParameter(
            "Invalid --resolver. Use 'youtube' or 'soundcloud'.",
            param_hint="--resolver",
        )

    ui = _make_ui(
        level=_level_from_flags(quiet=quiet, verbose=verbose, debug=debug),
        no_color=no_color,
        print_path_only=print_path,
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
    )


@app.command()
def info(
    ctx: typer.Context,
    url: Annotated[str, typer.Argument(help="URL to inspect.")],
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON for scripting.")] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="Disable colored output.")] = False,
) -> None:
    no_color = _resolve_option(ctx, "no_color", no_color)
    ui = _make_ui(level="normal", no_color=no_color, print_path_only=False)
    try:
        item = run_info(url, ui=ui)
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
) -> None:
    successes: list[Path] = []
    failures: list[tuple[str, str, str | None]] = []

    for idx, url in enumerate(urls, start=1):
        if len(urls) > 1 and ui.level != "quiet" and not ui.print_path_only:
            ui.info(f"[dim]{idx}/{len(urls)}[/dim] {url}")
        try:
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
            )
            successes.extend(paths)
        except PartialSuccessError as e:
            successes.extend(e.saved_paths)
            failures.extend(e.failures)
            for f_url, msg, stage in e.failures:
                ui.error(f"{stage + ': ' if stage else ''}{msg} ({f_url})")
                hint = _hint_for_error(stage, msg)
                if hint and ui.level != "quiet" and not ui.print_path_only:
                    ui.info(f"[dim]Hint:[/dim] {hint}")
        except RipmediaError as e:
            msg = f"{e.stage + ': ' if e.stage else ''}{e}"
            failures.append((url, msg, e.stage))
            ui.error(msg)
            hint = _hint_for_error(e.stage, str(e))
            if hint and ui.level != "quiet" and not ui.print_path_only:
                ui.info(f"[dim]Hint:[/dim] {hint}")
            continue
        except Exception as e:  # noqa: BLE001
            failures.append((url, str(e), None))
            if ui.level == "debug":
                raise
            ui.error(str(e))
            hint = _hint_for_error(None, str(e))
            if hint and ui.level != "quiet" and not ui.print_path_only:
                ui.info(f"[dim]Hint:[/dim] {hint}")

    if failures and ui.level != "quiet" and not ui.print_path_only:
        ui.info(f"[bold]Summary:[/bold] saved={len(successes)} failed={len(failures)}")
        max_list = 20
        for failed_url, msg, stage in failures[:max_list]:
            prefix = f"{stage}: " if stage else ""
            ui.info(f"[red]-[/red] {prefix}{msg} ({failed_url})")
        if len(failures) > max_list:
            ui.info(f"[dim]…and {len(failures) - max_list} more failures[/dim]")

    if ui.print_path_only:
        for p in successes:
            ui.console.print(str(p))

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
    if "no supported javascript runtime" in m or "js runtime" in m or "ejs" in m:
        return "yt-dlp may need a JS runtime for YouTube. Install Node.js or Deno; see yt-dlp EJS docs."
    if "ffmpeg" in m or "ffprobe" in m:
        return "Install ffmpeg and ensure it's on PATH (check `ffmpeg -version`)."
    if stage == "Metadata" and ("spotify_client_id" in m or "spotify_client_secret" in m):
        return "Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to enable Spotify album/playlist expansion."
    if stage == "Resolve" and "low confidence" in m:
        return "Re-run with `--interactive` to choose, or try `--resolver soundcloud`."
    if "cookies" in m and ("required" in m or "needed" in m):
        return "Try passing cookies via `--cookies cookies.txt` or `--cookies-from-browser chrome`."
    return None
