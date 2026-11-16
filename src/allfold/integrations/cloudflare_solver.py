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


_CHECKBOX_INTERACTABLE = """function(hitTest = true) {
    if (!this.isConnected || this.disabled || this.checked) return false;
    if (!this.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return false;
    const style = window.getComputedStyle(this);
    const rect = this.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0 || style.visibility === 'hidden'
            || style.display === 'none' || style.pointerEvents === 'none') return false;
    if (!hitTest) return true;
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


async def _checkbox_is_interactable(checkbox, *, hit_test=True) -> bool:
    from pydoll.exceptions import CommandFailed

    try:
        response = await checkbox.execute_script(_CHECKBOX_INTERACTABLE,
            arguments=[{'value': hit_test}], return_by_value=True)
    except CommandFailed:
        return False
    return bool(response.get('result', {}).get('result', {}).get('value', False))


_CHECKBOX_LABELS = """function() {
    if (!this.isConnected || this.localName !== 'input' || this.type !== 'checkbox'
            || this.disabled || this.checked) return [];
    return [...(this.labels || [])].filter(label => label.control === this);
}"""


async def _checkbox_target(checkbox):
    if await _checkbox_is_interactable(checkbox):
        return checkbox
    # Turnstile can make the native input transparent and style its associated
    # label. Only that exact control's visible, hit-testable label may substitute.
    for label in await checkbox.query_script(_CHECKBOX_LABELS):
        if await _checkbox_is_interactable(label):
            return label
    return None


async def _control_path_is_clear(target, connection, frame_id, lineage):
    # Match Pydoll's native click point, then hit-test through each actual CDP
    # target boundary. An iframe's center says nothing about its control's point.
    quad = await target.bounds()
    point = [sum(quad[axis::2]) / 4 for axis in (0, 1)]
    expected = {'frameId': frame_id}

    async def hit_matches():
        hit = (await connection.execute_command({'method': 'DOM.getNodeForLocation', 'params': {
            'x': int(point[0]), 'y': int(point[1]), 'includeUserAgentShadowDOM': True}}))['result']
        return all(hit.get(key) == value for key, value in expected.items())

    for frame, parent_connection, owner_id in reversed(lineage):
        if not await _checkbox_is_interactable(frame, hit_test=False):
            return False
        if parent_connection is connection:
            continue  # Native hit-testing already traverses same-process frames.
        if not await hit_matches():
            return False
        viewport = (await connection.execute_command({'method': 'Page.getLayoutMetrics'}))['result']['cssLayoutViewport']
        u, v = point[0] / viewport['clientWidth'], point[1] / viewport['clientHeight']
        quad = await frame.bounds()
        point = [quad[axis] + u * (quad[axis + 2] - quad[axis])
                 + v * (quad[axis + 6] - quad[axis]) for axis in (0, 1)]
        connection = parent_connection
        expected = {'backendNodeId': owner_id}
    return await hit_matches()


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
    try:
        while not task.done():
            if stop.is_set():
                task.cancel()
                break
            await asyncio.wait({task}, timeout=0.05)
        try:
            return await task
        except asyncio.CancelledError:
            return ({'outcome': 'not_executed', 'reason': 'canceled'} if stop.is_set()
                    else {'outcome': 'failed', 'reason': 'solver_failed'})
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def _challenge_origin(url: str) -> bool:
    source = urlsplit(url)
    return (source.scheme == "https"
            and source.netloc.lower() in {"challenges.cloudflare.com", "challenges.cloudflare.com:443"})


async def _disconnect(connection):
    # A stop can arrive while an ordinary scan is already closing its frame
    # connection. Do not interrupt that cleanup and report a premature terminal.
    closing = asyncio.create_task(connection.close())
    try:
        await asyncio.shield(closing)
    except asyncio.CancelledError:
        await closing
        raise


async def _frame_connection(frame_id, browser_connection, endpoint, resources):
    from pydoll.connection.connection_handler import ConnectionHandler

    # Only a frame already discovered under the original target may be attached.
    info = await browser_connection.execute_command({'method': 'Target.getTargetInfo', 'params': {'targetId': frame_id}})
    if info['result']['targetInfo'].get('type') != 'iframe':
        return None
    address = urlunsplit(endpoint._replace(path=f'/devtools/page/{frame_id}'))
    connection = ConnectionHandler(ws_address=address)
    resources.push_async_callback(_disconnect, connection)
    tree = (await connection.execute_command({'method': 'Page.getFrameTree'}))['result']['frameTree']
    return (connection, tree) if tree['frame']['id'] == frame_id else None


async def _owned_frames(connection, tree, targets, browser_connection, endpoint, resources, ancestors=(), seen=None):
    from pydoll.elements.web_element import WebElement

    seen = set() if seen is None else seen
    children = {item['frame']['id']: item for item in tree.get('childFrames', [])}
    # Page.getFrameTree omits OOPIFs. A target listing supplies candidate IDs only;
    # DOM.getFrameOwner on this exact parent must prove membership before use.
    for info in targets:
        children.setdefault(info['targetId'], {'frame': {'id': info['targetId'], 'url': info.get('url', '')}})
    for child in children.values():
        frame_id = child['frame']['id']
        if frame_id == tree['frame']['id'] or frame_id in seen:
            continue
        try:
            async with asyncio.timeout(5):
                owner = (await connection.execute_command({'method': 'DOM.getFrameOwner', 'params': {'frameId': frame_id}}))['result']['backendNodeId']
                resolved = await connection.execute_command({'method': 'DOM.resolveNode', 'params': {'backendNodeId': owner}})
                element = WebElement(resolved['result']['object']['objectId'], connection)
                if not await _checkbox_is_interactable(element, hit_test=False):
                    seen.add(frame_id)
                    continue
                attached = None
                if 'parentId' not in child['frame']:
                    attached = await _frame_connection(frame_id, browser_connection, endpoint, resources)
                    if not attached or attached[1]['frame'].get('parentId') != tree['frame']['id']:
                        continue  # A descendant must be reached through every actual parent.
                    child = attached[1]
                seen.add(frame_id)
            # Never keep a timeout context open across yield: it would cancel the
            # consumer's task while that task is inspecting a different CDP control.
            lineage = (*ancestors, (element, connection, owner))
            child_connection = attached[0] if attached else connection
            if _challenge_origin(child['frame'].get('url', '')):
                yield element, frame_id, child_connection, lineage
            else:
                async for entry in _owned_frames(child_connection, child, targets, browser_connection, endpoint, resources, lineage, seen):
                    yield entry
        except Exception:
            continue  # Detached/hidden auxiliary frames do not veto an actionable sibling.


async def _frame_body(frame_id, connection, browser_connection, endpoint, resources):
    from pydoll.elements.web_element import WebElement
    from pydoll.exceptions import CommandFailed

    try:
        result = await connection.execute_command({'method': 'Page.createIsolatedWorld',
            'params': {'frameId': frame_id, 'worldName': 'AllfoldSolver'}})
    except CommandFailed:
        attached = await _frame_connection(frame_id, browser_connection, endpoint, resources)
        if not attached or not _challenge_origin(attached[1]['frame'].get('url', '')):
            return None
        connection = attached[0]
        result = await connection.execute_command({'method': 'Page.createIsolatedWorld',
            'params': {'frameId': frame_id, 'worldName': 'AllfoldSolver'}})
    result = await connection.execute_command({'method': 'Runtime.evaluate', 'params': {
        'contextId': result['result']['executionContextId'],
        'expression': 'location.origin === "https://challenges.cloudflare.com" ? document.body : null'}})
    object_id = result.get('result', {}).get('result', {}).get('objectId')
    return (WebElement(object_id, connection), connection) if object_id else None


async def _node_key(node, connection, frame_id):
    reference = await node.execute_script('return this', return_by_value=False)
    object_id = reference['result']['result'].get('objectId')
    if not object_id:
        return None
    # Node handles are local to the actual frame connection, never a URL lookup.
    response = await node.execute_script('return this.ownerDocument.defaultView.location.origin', return_by_value=True)
    if response.get('result', {}).get('result', {}).get('value') != 'https://challenges.cloudflare.com':
        return None
    response = await connection.execute_command({'method': 'DOM.describeNode', 'params': {'objectId': object_id, 'depth': 0}})
    return frame_id, response['result']['node']['backendNodeId']


async def _scan(connection, browser_connection, endpoint, clicked, stop):
    from pydoll.exceptions import ShadowRootNotFound

    async with asyncio.timeout(5):
        tree = (await connection.execute_command({'method': 'Page.getFrameTree'}))['result']['frameTree']
        targets = (await browser_connection.execute_command({'method': 'Target.getTargets', 'params': {
            'filter': [{'type': 'iframe'}]}}))['result']['targetInfos']
    candidates = []
    async with AsyncExitStack() as resources:
        async for frame, frame_id, parent_connection, lineage in _owned_frames(
                connection, tree, targets, browser_connection, endpoint, resources):
            try:
                async with asyncio.timeout(5):
                    resolved = await _frame_body(frame_id, parent_connection, browser_connection, endpoint, resources)
                    if resolved is None:
                        continue
                    body, frame_connection = resolved
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
                        target = await _checkbox_target(box)
                        if target is not None and key not in clicked and await _control_path_is_clear(target, frame_connection, frame_id, lineage):
                            target_key = await _node_key(target, frame_connection, frame_id)
                            if target_key is not None:
                                candidates.append((lineage, box, key, frame_connection, frame_id, target, target_key))
                        elif target is None:
                            clicked.discard(key)  # A real disabled/checked -> ready transition may retry.
            except Exception:
                continue  # Stale nodes and local CDP failures are observations, not terminal page failures.
        # Count currently actionable controls, not every checkbox or frame on the page.
        unique = {key: (lineage, box, frame_connection, frame_id, target, target_key)
                  for lineage, box, key, frame_connection, frame_id, target, target_key in candidates}
        if len(unique) > 1:
            return {'outcome': 'waiting', 'reason': 'checkbox_ambiguous'}
        if not unique:
            return {'outcome': 'waiting', 'reason': 'checkbox_not_found'}
        key, (lineage, box, frame_connection, frame_id, target, target_key) = next(iter(unique.items()))
        async with asyncio.timeout(5):
            # The owner node and control must still be current and hit-testable.
            # This tolerates same-tab navigation but never retargets another tab.
            if stop.is_set():
                raise asyncio.CancelledError()
            if await _node_key(box, frame_connection, frame_id) != key:
                return {'outcome': 'waiting', 'reason': 'checkbox_not_interactable'}
            current_target = await _checkbox_target(box)
            if current_target is None or await _node_key(current_target, frame_connection, frame_id) != target_key:
                return {'outcome': 'waiting', 'reason': 'checkbox_not_interactable'}
            if not await _control_path_is_clear(current_target, frame_connection, frame_id, lineage):
                return {'outcome': 'waiting', 'reason': 'checkbox_not_interactable'}
            await target.click()
            clicked.add(key)
            return {'outcome': 'clicked', 'reason': 'checkbox_clicked'}


async def _watch_turnstile(cdp_url: str, stop: Event, *, target_id: str, progress) -> dict[str, str]:
    from pydoll.connection.connection_handler import ConnectionHandler

    endpoint = urlsplit(cdp_url)
    clicked = set()
    last = None
    while not stop.is_set():
        try:
            async with AsyncExitStack() as resources:
                browser_connection = ConnectionHandler(ws_address=cdp_url)
                resources.push_async_callback(_disconnect, browser_connection)
                async with asyncio.timeout(5):
                    result = await browser_connection.execute_command({'method': 'Target.getTargetInfo', 'params': {'targetId': target_id}})
                if result['result']['targetInfo'].get('type') != 'page':
                    return {'outcome': 'not_executed', 'reason': 'target_closed'}
                page_endpoint = urlunsplit(endpoint._replace(path=f'/devtools/page/{target_id}'))
                connection = ConnectionHandler(ws_address=page_endpoint)
                resources.push_async_callback(_disconnect, connection)
                while not stop.is_set():
                    result = await _scan(connection, browser_connection, endpoint, clicked, stop)
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
