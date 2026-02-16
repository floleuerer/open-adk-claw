from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

import yaml
from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.genai import types

# Import available tools for dynamic assignment
from adk_claw.actions.browser_tools import browser_interact, browse_webpage
from adk_claw.actions.datetime_tools import get_current_datetime
from adk_claw.actions.memory_tools import search_memory
from adk_claw.actions.sandbox_tools import execute_code, execute_shell

if TYPE_CHECKING:
    from adk_claw.skills.toolset import SkillToolset

logger = logging.getLogger(__name__)

TOOL_REGISTRY = {
    "browser_interact": browser_interact,
    "browse_webpage": browse_webpage,
    "get_current_datetime": get_current_datetime,
    "search_memory": search_memory,
    "execute_code": execute_code,
    "execute_shell": execute_shell,
}


def load_dynamic_agents(agents_dir: Path, skill_toolset: SkillToolset) -> list[LlmAgent]:
    """Load LlmAgent definitions from YAML files in the specified directory."""
    if not agents_dir.is_dir():
        return []

    dynamic_agents = []
    for yaml_file in sorted(agents_dir.glob("*.yaml")):
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            if not config:
                continue

            name = config.get("name")
            description = config.get("description")
            instruction = config.get("instruction")
            model = config.get("model", "gemini-3-flash-preview")
            tool_names = config.get("tools", [])

            if not name or not description or not instruction:
                logger.warning("Skipping invalid agent config in %s: missing name, description or instruction", yaml_file)
                continue

            tools: list[Any] = []
            for tname in tool_names:
                if tname in TOOL_REGISTRY:
                    tools.append(TOOL_REGISTRY[tname])
                elif tname == "skill_toolset":
                    tools.append(skill_toolset)
                else:
                    logger.warning("Tool '%s' not found in registry for agent '%s'", tname, name)

            agent = LlmAgent(
                name=name,
                description=description,
                instruction=instruction,
                model=Gemini(
                    model=model,
                    retry_options=types.HttpRetryOptions(initial_delay=2, attempts=5),
                ),
                tools=tools,
            )
            dynamic_agents.append(agent)
            logger.info("Loaded dynamic agent: %s", name)

        except Exception:
            logger.exception("Error loading dynamic agent from %s", yaml_file)

    return dynamic_agents
