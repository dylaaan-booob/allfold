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
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden'
        && style.display !== 'none' && style.pointerEvents !== 'none';
}"""


async def _checkbox_is_interactable(checkbox) -> bool:
    from pydoll.exceptions import CommandFailed

    try:
        response = await checkbox.execute_script(_CHECKBOX_INTERACTABLE, return_by_value=True)
    except CommandFailed:
        return False
    return bool(response.get('result', {}).get('result', {}).get('value', False))


_CHECKBOX_LABELS = """function() {
    if (!this.isConnected || this.localName !== 'input' || this.type !== 'checkbox'
            || this.disabled || this.checked) return [];
    return [...(this.labels || [])].filter(label => label.control === this);
}"""


async def _hit_belongs_to_control(connection, hit, key):
    if hit.get('frameId') != key[0]:
        return False
    # Resolve both nodes in an isolated world so site prototypes cannot replace
    # the native containment check. Release these short-lived handles together.
    context = (await connection.execute_command({'method': 'Page.createIsolatedWorld', 'params': {
        'frameId': key[0], 'worldName': 'AllfoldSolver'}}))['result']['executionContextId']
    group = 'AllfoldSolverHit'
    try:
        nodes = []
        for backend_id in (key[1], hit['backendNodeId']):
            result = await connection.execute_command({'method': 'DOM.resolveNode', 'params': {
                'backendNodeId': backend_id, 'objectGroup': group, 'executionContextId': context}})
            nodes.append(result['result']['object']['objectId'])
        result = await connection.execute_command({'method': 'Runtime.callFunctionOn', 'params': {
            'objectId': nodes[0], 'functionDeclaration': '''function(hit) {
                // Chromium exposes hit pseudo-elements as CSSPseudoElement, not Node.
                if (!(hit instanceof Node)) hit = hit.element;
                return this.isConnected && hit instanceof Node && this.contains(hit);
            }''',
            'arguments': [{'objectId': nodes[1]}], 'returnByValue': True}})
        return result['result']['result'].get('value') is True
    finally:
        await connection.execute_command({'method': 'Runtime.releaseObjectGroup', 'params': {'objectGroup': group}})


async def _control_point(target, connection, key, lineage):
    # Use the actual native content-box point throughout, without a later scroll
    # or position recomputation. An iframe's center cannot prove this path clear.
    quad = await target.bounds()
    point = [sum(quad[axis::2]) / 4 for axis in (0, 1)]
    click_point = tuple(int(value) for value in point)
    point = list(click_point)
    expected_owner = None

    async def hit_matches():
        hit = (await connection.execute_command({'method': 'DOM.getNodeForLocation', 'params': {
            'x': int(point[0]), 'y': int(point[1]), 'includeUserAgentShadowDOM': True}}))['result']
        if expected_owner is None:
            return await _hit_belongs_to_control(connection, hit, key)
        return hit.get('backendNodeId') == expected_owner

    for frame, parent_connection, owner_id, child_id in reversed(lineage):
        if not await _checkbox_is_interactable(frame):
            return None
        if parent_connection is connection:
            continue  # Native hit-testing already traverses same-process frames.
        if not await hit_matches():
            return None
        context = (await connection.execute_command({'method': 'Page.createIsolatedWorld', 'params': {
            'frameId': child_id, 'worldName': 'AllfoldSolver'}}))['result']['executionContextId']
        viewport = (await connection.execute_command({'method': 'Runtime.evaluate', 'params': {
            'contextId': context, 'expression': '({width: innerWidth, height: innerHeight})',
            'returnByValue': True}}))['result']['result']['value']
        # innerWidth/Height include scrollbars, matching the iframe content quad;
        # LayoutViewport.clientWidth/Height would scale the point incorrectly.
        u, v = point[0] / viewport['width'], point[1] / viewport['height']
        quad = await frame.bounds()
        point = [quad[axis] + u * (quad[axis + 2] - quad[axis])
                 + v * (quad[axis + 6] - quad[axis]) for axis in (0, 1)]
        connection = parent_connection
        expected_owner = owner_id
    return click_point if await hit_matches() else None


async def _checkbox_target(checkbox, connection, frame_id, lineage):
    from pydoll.exceptions import CommandFailed

    # Native inputs and their explicit labels are alternative interaction targets
    # for one checkbox. Test each at its actual point before choosing it.
    for target in [checkbox, *await checkbox.query_script(_CHECKBOX_LABELS)]:
        try:
            if not await _checkbox_is_interactable(target):
                continue
            key = await _node_key(target, connection, frame_id)
            if key is not None:
                point = await _control_point(target, connection, key, lineage)
                if point is not None:
                    return key, point
        except CommandFailed:
            continue  # An offscreen/stale input must not veto its usable label.
    return None


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
                if not await _checkbox_is_interactable(element):
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
            lineage = (*ancestors, (element, connection, owner, frame_id))
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


async def _scan(connection, browser_connection, endpoint, stop):
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
                        current = await _checkbox_target(box, frame_connection, frame_id, lineage)
                        if current is not None:
                            target_key, _point = current
                            candidates.append((lineage, box, key, frame_connection, frame_id, target_key))
            except Exception:
                continue  # Stale nodes and local CDP failures are observations, not terminal page failures.
        # Count currently actionable controls, not every checkbox or frame on the page.
        unique = {key: (lineage, box, frame_connection, frame_id, target_key)
                  for lineage, box, key, frame_connection, frame_id, target_key in candidates}
        if len(unique) > 1:
            return {'outcome': 'waiting', 'reason': 'checkbox_ambiguous'}
        if not unique:
            return {'outcome': 'waiting', 'reason': 'checkbox_not_found'}
        key, (lineage, box, frame_connection, frame_id, target_key) = next(iter(unique.items()))
        async with asyncio.timeout(5):
            # The owner node and control must still be current and hit-testable.
            # This tolerates same-tab navigation but never retargets another tab.
            if stop.is_set():
                raise asyncio.CancelledError()
            if await _node_key(box, frame_connection, frame_id) != key:
                return {'outcome': 'waiting', 'reason': 'checkbox_not_interactable'}
            current = await _checkbox_target(box, frame_connection, frame_id, lineage)
            if current is None or current[0] != target_key:
                return {'outcome': 'waiting', 'reason': 'checkbox_not_interactable'}
            if stop.is_set():
                raise asyncio.CancelledError()
            point = current[1]
            event = {'x': point[0], 'y': point[1], 'button': 'left', 'clickCount': 1}
            try:
                await frame_connection.execute_command({'method': 'Input.dispatchMouseEvent', 'params': {
                    **event, 'type': 'mousePressed', 'buttons': 1}})
            finally:
                await frame_connection.execute_command({'method': 'Input.dispatchMouseEvent', 'params': {
                    **event, 'type': 'mouseReleased', 'buttons': 0}})
            return {'outcome': 'clicked', 'reason': 'checkbox_clicked'}


async def _watch_turnstile(cdp_url: str, stop: Event, *, target_id: str, progress) -> dict[str, str]:
    from pydoll.connection.connection_handler import ConnectionHandler

    endpoint = urlsplit(cdp_url)
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
                    result = await _scan(connection, browser_connection, endpoint, stop)
                    if result != last or result['outcome'] == 'clicked':
                        await progress(result)
                        last = result
                    # De-duplicate controls within each scan and space input by
                    # this cancelable observation interval. Re-locate even an
                    # unchanged unchecked control after an ignored click.
                    await asyncio.sleep(.5)
        except Exception:
            result = {'outcome': 'waiting', 'reason': 'cdp_unavailable'}
            if result != last:
                await progress(result)
                last = result
            await asyncio.sleep(.5)
    return {'outcome': 'not_executed', 'reason': 'canceled'}
