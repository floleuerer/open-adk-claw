from __future__ import annotations

import asyncio
import base64
import time
import uuid
from typing import Literal

from fastapi import FastAPI
from playwright.async_api import Page, async_playwright
from pydantic import BaseModel

app = FastAPI(title="Browser Service")

_playwright = None
_browser = None

_sessions: dict[str, dict] = {}  # session_id -> {"page": Page, "last_used": float}
_sessions_lock = asyncio.Lock()
SESSION_TTL_SECONDS = 300  # 5 min idle timeout

_cleanup_task = None


async def _cleanup_expired_sessions():
    while True:
        await asyncio.sleep(30)
        now = time.monotonic()
        async with _sessions_lock:
            expired = [
                sid
                for sid, info in _sessions.items()
                if now - info["last_used"] > SESSION_TTL_SECONDS
            ]
            for sid in expired:
                try:
                    ctx = _sessions[sid]["page"].context
                    await _sessions[sid]["page"].close()
                    await ctx.close()
                except Exception:
                    pass
                del _sessions[sid]


_STEALTH_JS = """
// Override navigator.webdriver
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// Override navigator.plugins to look real
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// Override navigator.languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});

// Pass Chrome detection
window.chrome = { runtime: {} };

// Override permissions query
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);
"""

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


async def _new_stealth_page() -> Page:
    """Create a new page with stealth scripts applied."""
    context = await _browser.new_context(
        user_agent=_USER_AGENT,
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        timezone_id="America/New_York",
    )
    await context.add_init_script(_STEALTH_JS)
    page = await context.new_page()
    return page


@app.on_event("startup")
async def startup():
    global _playwright, _browser, _cleanup_task
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )
    _cleanup_task = asyncio.create_task(_cleanup_expired_sessions())


@app.on_event("shutdown")
async def shutdown():
    global _playwright, _browser, _cleanup_task
    if _cleanup_task:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
    async with _sessions_lock:
        for info in _sessions.values():
            try:
                ctx = info["page"].context
                await info["page"].close()
                await ctx.close()
            except Exception:
                pass
        _sessions.clear()
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()


class BrowseRequest(BaseModel):
    url: str
    action: str = "extract_text"  # "extract_text" or "screenshot"
    selector: str = ""


class BrowseResponse(BaseModel):
    content: str = ""
    title: str = ""
    url: str = ""
    error: str = ""


@app.post("/browse", response_model=BrowseResponse)
async def browse(req: BrowseRequest) -> BrowseResponse:
    if not _browser:
        return BrowseResponse(error="Browser not initialized")

    page = await _new_stealth_page()
    try:
        await page.goto(req.url, wait_until="domcontentloaded", timeout=20000)
        title = await page.title()
        final_url = page.url

        if req.action == "screenshot":
            if req.selector:
                element = await page.query_selector(req.selector)
                if element:
                    screenshot = await element.screenshot()
                else:
                    screenshot = await page.screenshot(full_page=False)
            else:
                screenshot = await page.screenshot(full_page=False)
            content = base64.b64encode(screenshot).decode("utf-8")
        else:
            if req.selector:
                element = await page.query_selector(req.selector)
                content = await element.inner_text() if element else ""
            else:
                content = await page.inner_text("body")
            # Truncate very long pages
            content = content[:50000]

        return BrowseResponse(content=content, title=title, url=final_url)
    except Exception as e:
        return BrowseResponse(error=str(e))
    finally:
        context = page.context
        await page.close()
        await context.close()


# --- Session-based interaction ---


class SessionRequest(BaseModel):
    session_id: str | None = None
    action: Literal[
        "goto",
        "click",
        "fill",
        "select_option",
        "scroll",
        "wait_for",
        "extract_text",
        "screenshot",
        "close",
    ]
    url: str = ""
    selector: str = ""
    value: str = ""
    scroll_y: int = 0
    timeout_ms: int = 10000


class SessionResponse(BaseModel):
    session_id: str = ""
    content: str = ""
    title: str = ""
    url: str = ""
    error: str = ""


async def _get_or_create_session(
    session_id: str | None, action: str
) -> tuple[str, Page | None, str]:
    """Returns (session_id, page, error)."""
    if session_id is None:
        if action != "goto":
            return "", None, "session_id is required for actions other than 'goto'"
        if not _browser:
            return "", None, "Browser not initialized"
        page = await _new_stealth_page()
        sid = uuid.uuid4().hex
        async with _sessions_lock:
            _sessions[sid] = {"page": page, "last_used": time.monotonic()}
        return sid, page, ""

    async with _sessions_lock:
        info = _sessions.get(session_id)
        if info is None:
            return session_id, None, f"Session '{session_id}' not found or expired"
        info["last_used"] = time.monotonic()
        return session_id, info["page"], ""


@app.post("/session", response_model=SessionResponse)
async def session(req: SessionRequest) -> SessionResponse:
    sid, page, err = await _get_or_create_session(req.session_id, req.action)
    if err:
        return SessionResponse(session_id=sid, error=err)

    try:
        if req.action == "goto":
            await page.goto(
                req.url, wait_until="domcontentloaded", timeout=req.timeout_ms
            )

        elif req.action == "click":
            await page.click(req.selector, timeout=req.timeout_ms)

        elif req.action == "fill":
            await page.fill(req.selector, req.value, timeout=req.timeout_ms)

        elif req.action == "select_option":
            await page.select_option(req.selector, req.value, timeout=req.timeout_ms)

        elif req.action == "scroll":
            await page.evaluate(f"window.scrollBy(0, {req.scroll_y})")

        elif req.action == "wait_for":
            await page.wait_for_selector(req.selector, timeout=req.timeout_ms)

        elif req.action == "extract_text":
            if req.selector:
                element = await page.query_selector(req.selector)
                text = await element.inner_text() if element else ""
            else:
                text = await page.inner_text("body")
            return SessionResponse(
                session_id=sid,
                content=text[:50000],
                title=await page.title(),
                url=page.url,
            )

        elif req.action == "screenshot":
            if req.selector:
                element = await page.query_selector(req.selector)
                if element:
                    screenshot = await element.screenshot()
                else:
                    screenshot = await page.screenshot(full_page=False)
            else:
                screenshot = await page.screenshot(full_page=False)
            return SessionResponse(
                session_id=sid,
                content=base64.b64encode(screenshot).decode("utf-8"),
                title=await page.title(),
                url=page.url,
            )

        elif req.action == "close":
            async with _sessions_lock:
                _sessions.pop(sid, None)
            ctx = page.context
            await page.close()
            await ctx.close()
            return SessionResponse(session_id=sid)

        # Default return for actions that don't produce content
        return SessionResponse(
            session_id=sid,
            title=await page.title(),
            url=page.url,
        )

    except Exception as e:
        # Don't close the session on error — agent may retry
        return SessionResponse(session_id=sid, error=str(e))


@app.get("/health")
async def health():
    async with _sessions_lock:
        active = len(_sessions)
    return {"status": "ok", "active_sessions": active}
