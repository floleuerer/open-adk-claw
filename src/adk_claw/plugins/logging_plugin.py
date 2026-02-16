"""Plugin that logs agent invocations and tool calls."""

from __future__ import annotations

import logging
from typing import Any, Optional, TYPE_CHECKING

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.genai import types

if TYPE_CHECKING:
    from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)


class LoggingPlugin(BasePlugin):
    """Logs agent and tool invocations for observability."""

    def __init__(self) -> None:
        super().__init__(name="logging")

    async def before_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> Optional[types.Content]:
        logger.info(">>> [AGENT] Active: %s", agent.name.upper())
        return None

    async def after_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> Optional[types.Content]:
        logger.info("<<< [AGENT] Finished: %s", agent.name.upper())
        return None

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> Optional[dict]:
        logger.info("  --- [TOOL] %s | args: %s", tool.name, tool_args)
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict,
    ) -> Optional[dict]:
        logger.info("  --- [TOOL] %s: Finished", tool.name)
        return None
