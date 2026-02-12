from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import typer

from .config import get_config_path, load_config
from .ui import Ui
from rich.console import Console


@dataclass
class HookContext:
    event: str
    url: str | None = None
    item: Any | None = None
    paths: list[Path] | None = None
    error: Exception | None = None
    stage: str | None = None
    config: dict[str, str] | None = None
    ui: Ui | None = None


@dataclass
class PluginInfo:
    name: str
    path: Path
    enabled: bool
    error: str | None = None
    app: typer.Typer | None = None
    module: ModuleType | None = None


@dataclass
class PluginRegistry:
    hooks: dict[str, list[Callable[[HookContext], None]]] = field(default_factory=dict)
    plugins: list[PluginInfo] = field(default_factory=list)

    def register_hook(self, event: str, func: Callable[[HookContext], None]) -> None:
        self.hooks.setdefault(event, []).append(func)

    def emit(self, ctx: HookContext) -> None:
        for func in self.hooks.get(ctx.event, []):
            try:
                func(ctx)
            except Exception as e:  # noqa: BLE001
                if ctx.ui is not None:
                    ctx.ui.status(f"Plugin {func.__module__}", False, str(e))


class PluginAPI:
    def __init__(self, info: PluginInfo, registry: PluginRegistry) -> None:
        self.info = info
        self.registry = registry
        self.app = typer.Typer(add_completion=False, help=f"{info.name} plugin")

    def command(self, *args, **kwargs):
        return self.app.command(*args, **kwargs)

    def hook(self, event: str):
        def decorator(func: Callable[[HookContext], None]):
            self.registry.register_hook(event, func)
            return func

        return decorator

    def get_config(self) -> dict[str, str]:
        return load_config(get_config_path())

    def make_ui(self, *, no_color: bool = False, speed_unit: str = "MBps") -> Ui:
        console = Console(no_color=no_color, highlight=False, soft_wrap=True)
        return Ui(console=console, level="normal", print_path_only=False, speed_unit=speed_unit)


def get_plugin_dir() -> Path:
    return Path.home() / ".ripmedia" / "plugins"


def discover_plugins() -> list[PluginInfo]:
    root = get_plugin_dir()
    if not root.exists():
        return []
    plugins: list[PluginInfo] = []
    for path in sorted(root.glob("*.py")):
        name = path.stem
        enabled = True
        if name.endswith(".disabled"):
            name = name[: -len(".disabled")]
            enabled = False
        plugins.append(PluginInfo(name=name, path=path, enabled=enabled))
    for path in sorted(root.glob("*.disabled.py")):
        name = path.name[:-len(".disabled.py")]
        plugins.append(PluginInfo(name=name, path=path, enabled=False))
    dedup: dict[str, PluginInfo] = {}
    for info in plugins:
        dedup.setdefault(info.path.name, info)
    return list(dedup.values())


def load_plugins() -> PluginRegistry:
    registry = PluginRegistry()
    for info in discover_plugins():
        if not info.enabled:
            registry.plugins.append(info)
            continue
        try:
            module = _load_module(info)
            info.module = module
            api = PluginAPI(info, registry)
            register = getattr(module, "register", None) or getattr(module, "setup", None)
            if callable(register):
                register(api)
            else:
                info.error = "Missing register(plugin)"
            if api.app.registered_commands or api.app.registered_groups:
                info.app = api.app
        except Exception as e:  # noqa: BLE001
            info.error = str(e)
        registry.plugins.append(info)
    return registry


def _load_module(info: PluginInfo) -> ModuleType:
    module_name = f"ripmedia_user_plugin_{info.name}"
    spec = importlib.util.spec_from_file_location(module_name, info.path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load plugin")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
