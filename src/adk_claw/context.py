from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from adk_claw.memory.service import MarkdownMemoryService


@dataclass
class AppContext:
    """Central application context — replaces per-module globals."""

    memory_service: MarkdownMemoryService | None = None

    # Google API services (googleapiclient.discovery.Resource)
    gmail_service: Any = None
    calendar_service: Any = None

    # Sidecar service URLs
    browser_url: str = "http://browser:8000"
    sandbox_url: str = "http://sandbox:8000"

    # Workspace paths
    screenshots_dir: Path | None = None
    files_dir: Path | None = None
    skills_dir: Path | None = None
    agents_dir: Path | None = None
    heartbeat_file: Path | None = None


_app_ctx: ContextVar[AppContext] = ContextVar("app_ctx")


def get_context() -> AppContext:
    """Return the current application context."""
    return _app_ctx.get()


def set_context(ctx: AppContext) -> None:
    """Set the application context (call once at startup)."""
    _app_ctx.set(ctx)
