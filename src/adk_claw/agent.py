from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.plugins.multimodal_tool_results_plugin import MultimodalToolResultsPlugin
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

from adk_claw.plugins.logging_plugin import LoggingPlugin
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from adk_claw.actions.datetime_tools import get_current_datetime
from adk_claw.actions.memory_tools import search_memory
from adk_claw.actions.sandbox_tools import execute_code, execute_shell
from adk_claw.actions.skill_tools import create_skill, list_skills
from adk_claw.actions.agent_tools import create_dynamic_agent, list_dynamic_agents
from adk_claw.agents.browser_agent import create_browser_agent
from adk_claw.agents.dynamic import load_dynamic_agents
from adk_claw.agents.email_calendar_agent import create_email_calendar_agent
from adk_claw.agents.heartbeat_agent import create_heartbeat_agent
from adk_claw.agents.memory_curator_agent import create_memory_curator_agent

from adk_claw.config import Settings
from adk_claw.guardrails.execution_guardrails import make_execution_guardrail_callback
from adk_claw.memory.service import MarkdownMemoryService
from adk_claw.skills.toolset import SkillToolset

logger = logging.getLogger(__name__)


def _build_agent_tools(settings: Settings, skill_toolset: SkillToolset) -> list:
    agent_tools = [
        AgentTool(agent=create_heartbeat_agent()),
        AgentTool(agent=create_browser_agent()),
    ]

    # Load dynamic agents from workspace/agents/
    dynamic_agents_dir = settings.base_dir / "agents"
    for agent in load_dynamic_agents(dynamic_agents_dir, skill_toolset):
        agent_tools.append(AgentTool(agent=agent))

    if settings.gmail_credentials_file:
        agent_tools.append(AgentTool(agent=create_email_calendar_agent(settings)))
        logger.info("Email/calendar agent tool enabled")
    return agent_tools


def _load_rules(base_dir: Path) -> str:
    rules_file = base_dir / "RULES.md"
    if rules_file.exists():
        return rules_file.read_text(encoding="utf-8")
    return "You are a helpful AI assistant."


def _load_long_term_memory(base_dir: Path) -> str:
    memory_file = base_dir / "memory" / "MEMORY.md"
    if memory_file.exists():
        content = memory_file.read_text(encoding="utf-8").strip()
        if content:
            return f"\n\n## Profile\n{content}"
    return ""


def _build_instruction(settings: Settings) -> callable:
    base_dir = settings.base_dir

    def _instruction(_ctx) -> str:
        parts = [_load_rules(base_dir)]
        parts.append(_load_long_term_memory(base_dir))
        now = datetime.now(timezone.utc)
        parts.append(
            f"\n\n## Current Date & Time\n"
            f"{now.strftime('%A, %Y-%m-%d %H:%M:%S')} UTC"
        )
        return "".join(parts)

    return _instruction


def create_agent(settings: Settings) -> LlmAgent:
    instruction = _build_instruction(settings)
    skill_toolset = SkillToolset(
        skills_dir=settings.base_dir / "skills",
        sandbox_url=settings.sandbox_service_url,
    )
    execution_guardrail = make_execution_guardrail_callback(
        model=settings.execution_guardrail_model,
        enabled=settings.execution_guardrail_enabled,
    )
    return LlmAgent(
        name=settings.app_name,
        model=Gemini(
            #model=settings.model_name,
            model="gemini-3-pro-preview",
            retry_options=types.HttpRetryOptions(initial_delay=2, attempts=5),
        ),
        instruction=instruction,
        tools=[
            search_memory,
            get_current_datetime,
            execute_code,
            execute_shell,
            create_skill,
            list_skills,
            create_dynamic_agent,
            list_dynamic_agents,
            skill_toolset,
            *_build_agent_tools(settings, skill_toolset),
        ],
        before_tool_callback=execution_guardrail,
    )


def create_runner(
    settings: Settings,
    memory_service: MarkdownMemoryService,
) -> Runner:
    agent = create_agent(settings)
    session_service = InMemorySessionService()

    return Runner(
        app_name=settings.app_name,
        agent=agent,
        session_service=session_service,
        memory_service=memory_service,
        plugins=[MultimodalToolResultsPlugin(), LoggingPlugin()],
    )


def create_curator_runner(
    settings: Settings,
    session_service: InMemorySessionService,
) -> Runner:
    """Standalone runner for the memory curator agent, used during session rotation.

    Shares the main runner's session service so the curator can read
    conversation history from the session being rotated.
    """
    agent = create_memory_curator_agent()
    return Runner(
        app_name=settings.app_name,
        agent=agent,
        session_service=session_service,
        plugins=[LoggingPlugin()],
    )
