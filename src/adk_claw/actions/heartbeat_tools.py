from __future__ import annotations

from adk_claw.context import get_context
from adk_claw.heartbeat import _parse_heartbeat_md


def add_scheduled_task(schedule: str, prompt: str) -> dict:
    """Add a new recurring scheduled task.

    Args:
        schedule: When to run, e.g. 'Every 2 hours', 'Every 30 minutes', 'Every day at 09:00'.
        prompt: The instruction to execute on each occurrence.
    """
    ctx = get_context()
    if ctx.heartbeat_file is None:
        return {"error": "Custom heartbeat file not configured"}

    section = f"# {schedule}\n\n{prompt}\n\n"

    if ctx.heartbeat_file.exists():
        existing = ctx.heartbeat_file.read_text(encoding="utf-8")
        if not existing.endswith("\n"):
            existing += "\n"
        ctx.heartbeat_file.write_text(existing + section, encoding="utf-8")
    else:
        ctx.heartbeat_file.write_text(section, encoding="utf-8")

    return {"status": "added", "schedule": schedule, "prompt": prompt}


def list_scheduled_tasks() -> dict:
    """List all custom scheduled tasks."""
    ctx = get_context()
    if ctx.heartbeat_file is None:
        return {"error": "Custom heartbeat file not configured"}

    tasks = _parse_heartbeat_md(ctx.heartbeat_file)
    return {
        "tasks": [{"schedule": t.schedule, "prompt": t.prompt} for t in tasks],
        "count": len(tasks),
    }


def remove_scheduled_task(schedule: str) -> dict:
    """Remove a scheduled task by its schedule string.

    Args:
        schedule: The exact schedule string of the task to remove, e.g. 'Every 2 hours'.
    """
    ctx = get_context()
    if ctx.heartbeat_file is None:
        return {"error": "Custom heartbeat file not configured"}

    tasks = _parse_heartbeat_md(ctx.heartbeat_file)
    remaining = [t for t in tasks if t.schedule != schedule]

    if len(remaining) == len(tasks):
        return {"error": f"No task found with schedule: {schedule}"}

    content = ""
    for t in remaining:
        content += f"# {t.schedule}\n\n{t.prompt}\n\n"

    ctx.heartbeat_file.write_text(content, encoding="utf-8")
    return {"status": "removed", "schedule": schedule}
