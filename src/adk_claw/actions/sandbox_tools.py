from __future__ import annotations

import httpx

from adk_claw.context import get_context


def execute_shell(command: str, timeout: int = 10, working_dir: str = "") -> dict:
    """Execute a shell command in the sandboxed environment and return the output.

    Args:
        command: The shell command to run.
        timeout: Maximum execution time in seconds (max 30).
        working_dir: Optional working directory (defaults to /data/files).
    """
    ctx = get_context()
    timeout = min(timeout, 30)
    try:
        response = httpx.post(
            f"{ctx.sandbox_url}/execute_shell",
            json={"command": command, "timeout": timeout, "working_dir": working_dir},
            timeout=float(timeout + 5),
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        return {"error": f"Sandbox service error: {e}"}


def execute_code(code: str, language: str = "python", timeout: int = 10) -> dict:
    """Execute code in a sandboxed environment and return the output.

    Args:
        code: The source code to execute.
        language: Programming language (currently only "python" is supported).
        timeout: Maximum execution time in seconds (max 30).
    """
    ctx = get_context()
    timeout = min(timeout, 30)
    try:
        response = httpx.post(
            f"{ctx.sandbox_url}/execute",
            json={"code": code, "language": language, "timeout": timeout},
            timeout=float(timeout + 5),
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        return {"error": f"Sandbox service error: {e}"}
