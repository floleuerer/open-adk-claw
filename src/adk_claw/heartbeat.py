from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class HeartbeatTask:
    schedule: str
    prompt: str
    last_fired: datetime | None = None


OnHeartbeatCallback = Callable[[str, str], Awaitable[None]]


def _parse_heartbeat_md(path: Path) -> list[HeartbeatTask]:
    """Parse HEARTBEAT.md into tasks. Headings = schedule, body = prompt."""
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    tasks: list[HeartbeatTask] = []
    current_schedule = ""
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("#"):
            if current_schedule and current_lines:
                prompt = "\n".join(current_lines).strip()
                if prompt:
                    tasks.append(HeartbeatTask(schedule=current_schedule, prompt=prompt))
            current_schedule = line.lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_schedule and current_lines:
        prompt = "\n".join(current_lines).strip()
        if prompt:
            tasks.append(HeartbeatTask(schedule=current_schedule, prompt=prompt))

    return tasks


def _should_fire(task: HeartbeatTask, now: datetime) -> bool:
    """Check if a task should fire based on its schedule string."""
    schedule = task.schedule.lower().strip()

    # "Every N hours"
    match = re.match(r"every\s+(\d+)\s+hours?", schedule)
    if match:
        hours = int(match.group(1))
        if task.last_fired is None:
            return True
        elapsed = (now - task.last_fired).total_seconds()
        return elapsed >= hours * 3600

    # "Every day at HH:MM"
    match = re.match(r"every\s+day\s+at\s+(\d{1,2}):(\d{2})", schedule)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if task.last_fired and task.last_fired.date() == now.date():
            return False
        return now.hour >= hour and now.minute >= minute

    # "Every N minutes"
    match = re.match(r"every\s+(\d+)\s+minutes?", schedule)
    if match:
        minutes = int(match.group(1))
        if task.last_fired is None:
            return True
        elapsed = (now - task.last_fired).total_seconds()
        return elapsed >= minutes * 60

    logger.warning("Unknown schedule format: %s", task.schedule)
    return False


class HeartbeatScheduler:
    def __init__(
        self,
        heartbeat_files: list[Path],
        check_interval: float,
        on_heartbeat: OnHeartbeatCallback,
    ) -> None:
        self._heartbeat_files = heartbeat_files
        self._check_interval = check_interval
        self._on_heartbeat = on_heartbeat
        self._running = False
        self._tasks: list[HeartbeatTask] = []

    async def run(self) -> None:
        self._running = True
        self._last_fired: dict[str, datetime] = {}
        logger.info("Heartbeat scheduler started (interval: %.0fs)", self._check_interval)

        while self._running:
            try:
                self._tasks = []
                for f in self._heartbeat_files:
                    self._tasks.extend(_parse_heartbeat_md(f))
                now = datetime.now(timezone.utc)

                for task in self._tasks:
                    # Restore last_fired from persistent map so re-parsing
                    # the file doesn't reset the schedule
                    task.last_fired = self._last_fired.get(task.schedule)
                    if _should_fire(task, now):
                        logger.info("Firing heartbeat: %s", task.schedule)
                        task.last_fired = now
                        self._last_fired[task.schedule] = now
                        try:
                            await self._on_heartbeat(task.schedule, task.prompt)
                        except Exception:
                            logger.exception("Error in heartbeat callback")
            except Exception:
                logger.exception("Error in heartbeat loop")

            await asyncio.sleep(self._check_interval)

    def stop(self) -> None:
        self._running = False
