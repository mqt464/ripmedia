from __future__ import annotations

from pathlib import Path


class RipmediaError(Exception):
    stage: str | None = None

    def __init__(self, message: str, *, stage: str | None = None) -> None:
        super().__init__(message)
        self.stage = stage


class UsageError(RipmediaError):
    pass


class DetectError(RipmediaError):
    pass


class MetadataError(RipmediaError):
    pass


class ResolveError(RipmediaError):
    pass


class DownloadError(RipmediaError):
    pass


class TagError(RipmediaError):
    pass


class PartialSuccessError(RipmediaError):
    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        saved_paths: list[Path] | None = None,
        failures: list[tuple[str, str, str | None]] | None = None,
    ) -> None:
        super().__init__(message, stage=stage)
        self.saved_paths = saved_paths or []
        self.failures = failures or []
