from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone

import httpx
from google.genai import types

from adk_claw.context import get_context

logger = logging.getLogger(__name__)

_NO_SCREENSHOT_ACTIONS = frozenset({"screenshot", "extract_text", "close"})


def _take_screenshot(session_id: str, action: str) -> tuple[str | None, bytes | None]:
    """Take a screenshot, save it to disk for debugging, and return raw bytes.

    Returns:
        A tuple of (saved_file_path, png_bytes). Either may be None on failure.
    """
    ctx = get_context()
    try:
        resp = httpx.post(
            f"{ctx.browser_url}/session",
            json={"action": "screenshot", "session_id": session_id},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content", "")
        if not content:
            return None, None
        png_bytes = base64.b64decode(content)

        # Save to disk for debugging
        saved_path: str | None = None
        if ctx.screenshots_dir:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filepath = ctx.screenshots_dir / f"{ts}_{action}.png"
            filepath.write_bytes(png_bytes)
            logger.info("Saved browser screenshot: %s", filepath)
            saved_path = str(filepath)

        return saved_path, png_bytes
    except Exception:
        logger.warning("Failed to take screenshot after %s", action, exc_info=True)
        return None, None


def _result_with_screenshot(
    result: dict, png_bytes: bytes | None, saved_path: str | None,
) -> dict | list[types.Part]:
    """Return a multimodal response (text + image) if screenshot bytes are available."""
    if saved_path:
        result["screenshot_saved"] = saved_path
    if png_bytes is None:
        return result
    return [
        types.Part.from_text(text=str(result)),
        types.Part.from_bytes(data=png_bytes, mime_type="image/png"),
    ]


def browser_interact(
    action: str,
    session_id: str = "",
    url: str = "",
    selector: str = "",
    value: str = "",
    scroll_y: int = 0,
    timeout_ms: int = 10000,
) -> dict:
    """Interact with a persistent browser session.

    Start a new session by calling with action="goto" and a url (no session_id).
    The response will include a session_id to use for subsequent actions.

    Args:
        action: One of "goto", "click", "fill", "select_option", "scroll",
                "wait_for", "extract_text", "screenshot", "close".
        session_id: ID of an existing session. Omit when starting a new session.
        url: URL to navigate to (used with "goto").
        selector: CSS selector for the target element.
        value: Value for "fill" or "select_option" actions.
        scroll_y: Pixels to scroll vertically (used with "scroll").
        timeout_ms: Timeout in milliseconds for the action.
    """
    ctx = get_context()
    payload: dict = {"action": action, "timeout_ms": timeout_ms}
    if session_id:
        payload["session_id"] = session_id
    if url:
        payload["url"] = url
    if selector:
        payload["selector"] = selector
    if value:
        payload["value"] = value
    if scroll_y:
        payload["scroll_y"] = scroll_y

    client_timeout = max(30, timeout_ms / 1000 + 5)
    try:
        response = httpx.post(
            f"{ctx.browser_url}/session",
            json=payload,
            timeout=client_timeout,
        )
        response.raise_for_status()
        result = response.json()
        sid = result.get("session_id", session_id)
        if sid and action not in _NO_SCREENSHOT_ACTIONS:
            saved_path, png_bytes = _take_screenshot(sid, action)
            return _result_with_screenshot(result, png_bytes, saved_path)
        return result
    except httpx.HTTPError as e:
        return {"error": f"Browser service error: {e}"}


def browse_webpage(
    url: str, action: str = "extract_text", selector: str = "",
) -> dict | list[types.Part]:
    """Browse a webpage and extract its content or take a screenshot.

    Args:
        url: The URL to navigate to.
        action: What to do — "extract_text" to get page text, or "screenshot" to capture the page.
        selector: Optional CSS selector to target a specific element.
    """
    ctx = get_context()
    try:
        response = httpx.post(
            f"{ctx.browser_url}/browse",
            json={"url": url, "action": action, "selector": selector},
            timeout=30.0,
        )
        response.raise_for_status()
        result = response.json()

        if action == "screenshot":
            content = result.get("content", "")
            if content:
                png_bytes = base64.b64decode(content)
                # Save to disk for debugging
                saved_path: str | None = None
                if ctx.screenshots_dir:
                    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                    filepath = ctx.screenshots_dir / f"{ts}_browse.png"
                    filepath.write_bytes(png_bytes)
                    saved_path = str(filepath)
                return _result_with_screenshot(result, png_bytes, saved_path)

        return result
    except httpx.HTTPError as e:
        return {"error": f"Browser service error: {e}"}
