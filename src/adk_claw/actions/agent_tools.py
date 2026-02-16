from __future__ import annotations

import yaml
from adk_claw.context import get_context
from adk_claw.agents.dynamic import TOOL_REGISTRY


def create_dynamic_agent(
    name: str,
    description: str,
    instruction: str,
    tools: list[str] | None = None,
    model: str = "gemini-3-flash-preview",
) -> dict:
    """Create a new dynamic sub-agent.

    The agent will be available after the next system restart or session rotation
    if the agent is re-initialized.

    Args:
        name: Unique name for the agent (lowercase, underscores).
        description: Brief description of what the agent does (used for transfer).
        instruction: Detailed system prompt for the agent.
        tools: List of tool names to give to the agent.
               Available: browser_interact, browse_webpage, get_current_datetime,
               search_memory, execute_code, execute_shell,
               skill_toolset (for dynamic skills).
        model: Gemini model name to use.
    """
    ctx = get_context()
    if ctx.agents_dir is None:
        return {"error": "Agents directory not configured"}

    # Validate tools
    if tools:
        invalid_tools = [t for t in tools if t not in TOOL_REGISTRY]
        if invalid_tools:
            return {"error": f"Invalid tools: {', '.join(invalid_tools)}"}

    config = {
        "name": name,
        "description": description,
        "instruction": instruction,
        "model": model,
        "tools": tools or [],
    }

    agent_path = ctx.agents_dir / f"{name}.yaml"
    try:
        with open(agent_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, sort_keys=False)
        return {"status": "created", "name": name, "path": str(agent_path)}
    except Exception as e:
        return {"error": f"Failed to save agent config: {e}"}


def list_dynamic_agents() -> dict:
    """List all dynamically configured agents."""
    ctx = get_context()
    if ctx.agents_dir is None:
        return {"error": "Agents directory not configured"}

    agents = []
    for yaml_file in sorted(ctx.agents_dir.glob("*.yaml")):
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            if config:
                agents.append({
                    "name": config.get("name"),
                    "description": config.get("description"),
                    "model": config.get("model"),
                    "tools": config.get("tools", []),
                })
        except Exception:
            continue

    return {"agents": agents, "count": len(agents)}
