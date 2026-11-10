"""Click a Turnstile checkbox in one existing Electron page using Pydoll.

The result describes execution only. BrowserRuntime must check the page again.
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import logging
from threading import Event
from urllib.parse import urlsplit, urlunsplit


_CHECKBOX_QUERY = """function() {
    const found = new Set();
    const roots = [this];
    for (const root of roots) {
        for (const node of root.querySelectorAll('input[type="checkbox"]')) found.add(node);
        // Descendant hosts only: the starting body's own root is searched separately.
        for (const host of root.querySelectorAll('*')) {
            if (host.shadowRoot) roots.push(host.shadowRoot);
        }
    }
    return [...found];
}"""


_CHECKBOX_INTERACTABLE = """function() {
    if (!this.isConnected || this.disabled) return false;
    const style = window.getComputedStyle(this);
    const rect = this.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0 || style.visibility === 'hidden'
            || style.display === 'none' || style.pointerEvents === 'none') return false;
    const x = rect.x + rect.width / 2;
    const y = rect.y + rect.height / 2;
    const roots = [];
    for (let node = this; node;) {
        const root = node.getRootNode();
        if (typeof root.elementFromPoint !== 'function') return false;
        roots.push(root);
        if (root === this.ownerDocument) break;
        node = root.host;
    }
    if (roots[roots.length - 1] !== this.ownerDocument) return false;
    // Each outer root retargets the hit to the next shadow host, including closed roots.
    for (let i = roots.length - 1; i >= 0; i--) {
        const hit = roots[i].elementFromPoint(x, y);
        if (i > 0) {
            if (hit !== roots[i - 1].host) return false;
        } else if (!hit || (hit !== this && !this.contains(hit))) {
            return false;
        }
    }
    return true;
}"""


async def _checkbox_is_interactable(checkbox) -> bool:
    from pydoll.exceptions import CommandFailed

    try:
        response = await checkbox.execute_script(_CHECKBOX_INTERACTABLE, return_by_value=True)
    except CommandFailed:
        return False
    return bool(response.get('result', {}).get('result', {}).get('value', False))


def solve_cloudflare(cdp_url: str, page_url: str, stop: Event, *, target_id: str) -> dict[str, str]:
    if stop.is_set():
        return {"outcome": "not_executed", "reason": "canceled"}
    if not cdp_url:
        return {"outcome": "not_executed", "reason": "cdp_unavailable"}
    # Upstream logs may contain URLs or raw exceptions; Main logs our fixed codes.
    quiet_loggers = [logging.getLogger(name) for name in ("pydoll", "websockets.client")]
    previous = [(logger.handlers, logger.propagate) for logger in quiet_loggers]
    try:
        for logger in quiet_loggers:
            logger.handlers = [logging.NullHandler()]
            logger.propagate = False
        return asyncio.run(_solve_until_canceled(cdp_url, page_url, stop, target_id=target_id))
    except Exception:
        return {"outcome": "failed", "reason": "solver_failed"}
    finally:
        for logger, (handlers, propagate) in zip(quiet_loggers, previous):
            logger.handlers = handlers
            logger.propagate = propagate


async def _solve_until_canceled(cdp_url: str, page_url: str, stop: Event, *, target_id: str) -> dict[str, str]:
    task = asyncio.create_task(_click_turnstile(cdp_url, page_url, stop, target_id=target_id))
    while not task.done():
        if stop.is_set():
            task.cancel()
            break
        await asyncio.wait({task}, timeout=0.02)
    try:
        return await task
    except asyncio.CancelledError:
        if not stop.is_set():
            raise
        return {"outcome": "not_executed", "reason": "canceled"}


async def _click_turnstile(cdp_url: str, page_url: str, stop: Event, *, target_id: str) -> dict[str, str]:
    from pydoll import Chrome
    from pydoll.browser.tab import Tab
    from pydoll.connection.connection_handler import ConnectionHandler
    from pydoll.exceptions import NoValidTabFound, ShadowRootNotFound

    async with AsyncExitStack() as resources:
        browser = Chrome()
        # Browser.close() disconnects; its context manager and stop() close Electron.
        resources.push_async_callback(browser.close)
        try:
            await browser.connect(cdp_url)
        except NoValidTabFound:
            return {"outcome": "not_executed", "reason": "page_not_unique"}
        except Exception:
            return {"outcome": "not_executed", "reason": "cdp_unavailable"}
        targets = [target for target in await browser.get_targets()
                   if target.get("targetId") == target_id
                   and target.get("type") == "page" and target.get("url") == page_url]
        if len(targets) != 1:
            return {"outcome": "not_executed", "reason": "page_not_unique"}

        endpoint = urlsplit(cdp_url)
        page_endpoint = urlunsplit(endpoint._replace(path=f"/devtools/page/{target_id}"))
        connection = ConnectionHandler(ws_address=page_endpoint)
        resources.push_async_callback(connection.close)
        tab = Tab(browser, target_id=target_id, ws_address=page_endpoint,
                  connection_handler=connection)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 30.0
        while loop.time() < deadline:
            if stop.is_set():
                raise asyncio.CancelledError()
            async with AsyncExitStack() as scan_resources:
                # Bound the scans themselves, not just the polling sleeps.
                discovery = asyncio.timeout_at(deadline)
                try:
                    async with discovery:
                        frames = await tab.query("iframe", find_all=True, raise_exc=False) or []
                        # deep=True enumerates global OOPIF targets in 3.0.0; stay in this page.
                        for shadow in await tab.find_shadow_roots():
                            frames.extend(await shadow.query("iframe", find_all=True,
                                                             raise_exc=False) or [])

                        checkboxes = []
                        for frame in frames:
                            source = urlsplit(frame.get_attribute("src") or "")
                            if (source.scheme != "https"
                                    or source.netloc.lower() not in {
                                        "challenges.cloudflare.com",
                                        "challenges.cloudflare.com:443"}):
                                continue
                            context = await frame.iframe_context()
                            if context is not None:
                                scan_resources.push_async_callback(context.close)
                            body = await frame.query("body", raise_exc=False)
                            if body is None:
                                continue
                            checkboxes.extend(await body.query_script(_CHECKBOX_QUERY))
                            try:
                                shadow = await body.get_shadow_root()
                            except ShadowRootNotFound:
                                shadow = None
                            if shadow is not None:
                                checkboxes.extend(await shadow.query_script(_CHECKBOX_QUERY))
                        if len(checkboxes) > 1:
                            return {"outcome": "failed", "reason": "checkbox_not_unique"}
                        interactable = bool(checkboxes) and await _checkbox_is_interactable(checkboxes[0])
                except TimeoutError:
                    if not discovery.expired():
                        raise
                    return {"outcome": "not_found", "reason": "checkbox_not_found"}
                if loop.time() >= deadline:
                    return {"outcome": "not_found", "reason": "checkbox_not_found"}
                if interactable:
                    if stop.is_set():
                        raise asyncio.CancelledError()
                    # Clicking is outside the discovery budget and is never retried.
                    await checkboxes[0].click()
                    return {"outcome": "clicked", "reason": "checkbox_clicked"}
            remaining = deadline - loop.time()
            if remaining > 0:
                await asyncio.sleep(min(0.15, remaining))
        return {"outcome": "not_found", "reason": "checkbox_not_found"}
