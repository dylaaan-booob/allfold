"""Click a Turnstile checkbox in one existing Electron page using Pydoll.

The result describes execution only. BrowserRuntime must check the page again.
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
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
    if (!this.isConnected || this.disabled || this.checked) return false;
    if (!this.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return false;
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


async def solve_cloudflare(cdp_url: str, stop: Event, *, target_id: str, progress) -> dict[str, str]:
    """Observe one verified native target until its owner cancels; never launch Chrome."""
    if stop.is_set():
        return {"outcome": "not_executed", "reason": "canceled"}
    if not cdp_url:
        return {"outcome": "not_executed", "reason": "cdp_unavailable"}
    try:
        return await _solve_until_canceled(cdp_url, stop, target_id=target_id, progress=progress)
    except Exception:
        return {"outcome": "failed", "reason": "solver_failed"}


async def _solve_until_canceled(cdp_url: str, stop: Event, *, target_id: str, progress) -> dict[str, str]:
    task = asyncio.create_task(_watch_turnstile(cdp_url, stop, target_id=target_id, progress=progress))
    while not task.done():
        if stop.is_set():
            task.cancel()
            break
        await asyncio.wait({task}, timeout=0.05)
    try:
        return await task
    except asyncio.CancelledError:
        if not stop.is_set():
            raise
        return {"outcome": "not_executed", "reason": "canceled"}


def _challenge_origin(url: str) -> bool:
    source = urlsplit(url)
    return (source.scheme == "https"
            and source.netloc.lower() in {"challenges.cloudflare.com", "challenges.cloudflare.com:443"})


async def _frame_body(frame, connection, browser, endpoint, resources: AsyncExitStack):
    from pydoll.browser.tab import Tab
    from pydoll.commands import DomCommands
    from pydoll.connection.connection_handler import ConnectionHandler
    from pydoll.elements.web_element import WebElement

    # Describe the frame element on the bound page. Pydoll's generic iframe
    # resolver can attach unrelated targets while looking for this document.
    reference = await frame.execute_script("return this", return_by_value=False)
    object_id = reference["result"]["result"].get("objectId")
    if object_id is None:
        return None
    response = await connection.execute_command(DomCommands.describe_node(object_id=object_id))
    node = response["result"]["node"]
    frame_id = node.get("frameId")
    if not frame_id:
        return None
    if node.get("contentDocument"):
        result = await connection.execute_command({
            "method": "Page.createIsolatedWorld", "params": {"frameId": frame_id, "worldName": "AllfoldSolver"}})
        context = result["result"]["executionContextId"]
        result = await connection.execute_command({"method": "Runtime.evaluate", "params": {
            "contextId": context,
            "expression": 'location.origin === "https://challenges.cloudflare.com" ? document.body : null',
        }})
        object_id = result.get("result", {}).get("result", {}).get("objectId")
        return (WebElement(object_id, connection), connection, frame_id) if object_id else None

    if not any(target.get("targetId") == frame_id and target.get("type") == "iframe"
               and _challenge_origin(target.get("url", "")) for target in await browser.get_targets()):
        return None
    frame_endpoint = urlunsplit(endpoint._replace(path=f"/devtools/page/{frame_id}"))
    frame_connection = ConnectionHandler(ws_address=frame_endpoint)
    resources.push_async_callback(frame_connection.close)
    result = await frame_connection.execute_command({"method": "Page.getFrameTree"})
    current = result["result"]["frameTree"]["frame"]
    if current["id"] != frame_id or not _challenge_origin(current["url"]):
        return None
    frame_tab = Tab(browser, target_id=frame_id, ws_address=frame_endpoint,
                    connection_handler=frame_connection)
    body = await frame_tab.query("body", raise_exc=False)
    return (body, frame_connection, frame_id) if body else None


async def _node_key(node, connection, frame_id):
    from pydoll.commands import DomCommands
    reference = await node.execute_script('return this', return_by_value=False)
    object_id = reference['result']['result'].get('objectId')
    if not object_id:
        return None
    # Node handles are local to the actual frame connection, never a URL lookup.
    response = await node.execute_script('return this.ownerDocument.defaultView.location.origin', return_by_value=True)
    if response.get('result', {}).get('result', {}).get('value') != 'https://challenges.cloudflare.com':
        return None
    response = await connection.execute_command(DomCommands.describe_node(object_id=object_id))
    return frame_id, response['result']['node']['backendNodeId']


async def _scan(tab, connection, browser, endpoint, clicked, stop):
    from pydoll.exceptions import ShadowRootNotFound

    # Pydoll deep=True enumerates browser-wide OOPIFs. Keep frame discovery rooted
    # in this target, including its accessible/closed shadow roots.
    async with asyncio.timeout(5):
        frames = await tab.query('iframe', find_all=True, raise_exc=False) or []
        for shadow in await tab.find_shadow_roots():
            frames.extend(await shadow.query('iframe', find_all=True, raise_exc=False) or [])
    candidates = []
    async with AsyncExitStack() as resources:
        for frame in frames:
            if not _challenge_origin(frame.get_attribute('src') or ''):
                continue
            try:
                async with asyncio.timeout(5):
                    if not await _checkbox_is_interactable(frame):
                        continue
                    resolved = await _frame_body(frame, connection, browser, endpoint, resources)
                    if resolved is None:
                        continue  # An unrelated rebuilding frame cannot veto a valid control.
                    body, frame_connection, frame_id = resolved
                    boxes = await body.query_script(_CHECKBOX_QUERY)
                    try:
                        shadow = await body.get_shadow_root()
                    except ShadowRootNotFound:
                        shadow = None
                    if shadow is not None:
                        boxes.extend(await shadow.query_script(_CHECKBOX_QUERY))
                    for box in boxes:
                        key = await _node_key(box, frame_connection, frame_id)
                        if key is None:
                            continue
                        usable = await _checkbox_is_interactable(box)
                        if usable and key not in clicked:
                            candidates.append((frame, box, key, frame_connection, frame_id))
                        elif not usable:
                            clicked.discard(key)  # A real disabled/checked -> ready transition may retry.
            except Exception:
                continue  # Stale nodes and local CDP failures are observations, not terminal page failures.
        # Count currently actionable controls, not every checkbox or frame on the page.
        unique = {key: (frame, box, frame_connection, frame_id)
                  for frame, box, key, frame_connection, frame_id in candidates}
        if len(unique) > 1:
            return {'outcome': 'waiting', 'reason': 'checkbox_ambiguous'}
        if not unique:
            return {'outcome': 'waiting', 'reason': 'checkbox_not_found'}
        key, (frame, box, frame_connection, frame_id) = next(iter(unique.items()))
        async with asyncio.timeout(5):
            # The owner node and control must still be current and hit-testable.
            # This tolerates same-tab navigation but never retargets another tab.
            if stop.is_set():
                raise asyncio.CancelledError()
            if not await _checkbox_is_interactable(frame) or not await _checkbox_is_interactable(box):
                return {'outcome': 'waiting', 'reason': 'checkbox_not_interactable'}
            if await _node_key(box, frame_connection, frame_id) != key:
                return {'outcome': 'waiting', 'reason': 'checkbox_not_interactable'}
            await box.click()
            clicked.add(key)
            return {'outcome': 'clicked', 'reason': 'checkbox_clicked'}


async def _watch_turnstile(cdp_url: str, stop: Event, *, target_id: str, progress) -> dict[str, str]:
    from pydoll import Chrome
    from pydoll.browser.tab import Tab
    from pydoll.connection.connection_handler import ConnectionHandler

    endpoint = urlsplit(cdp_url)
    clicked = set()
    last = None
    while not stop.is_set():
        try:
            async with AsyncExitStack() as resources:
                browser = Chrome()
                # close() only disconnects; stop()/the browser context manager would close Electron.
                resources.push_async_callback(browser.close)
                async with asyncio.timeout(5):
                    await browser.connect(cdp_url)
                    targets = await browser.get_targets()
                if not any(item.get('targetId') == target_id and item.get('type') == 'page' for item in targets):
                    return {'outcome': 'not_executed', 'reason': 'target_closed'}
                page_endpoint = urlunsplit(endpoint._replace(path=f'/devtools/page/{target_id}'))
                connection = ConnectionHandler(ws_address=page_endpoint)
                resources.push_async_callback(connection.close)
                tab = Tab(browser, target_id=target_id, ws_address=page_endpoint, connection_handler=connection)
                while not stop.is_set():
                    result = await _scan(tab, connection, browser, endpoint, clicked, stop)
                    if result != last:
                        await progress(result)
                        last = result
                    # A cancelable observation interval, not an attempt or challenge deadline.
                    await asyncio.sleep(.5)
        except Exception:
            result = {'outcome': 'waiting', 'reason': 'cdp_unavailable'}
            if result != last:
                await progress(result)
                last = result
            await asyncio.sleep(.5)
    return {'outcome': 'not_executed', 'reason': 'canceled'}
