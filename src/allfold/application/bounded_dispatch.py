"""Fair bounded dispatch over operations whose Futures represent actual settlement."""
from collections import Counter, deque
from collections.abc import Callable, Hashable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, wait
from typing import TypeVar

Item = TypeVar("Item")
Result = TypeVar("Result")


def bounded_dispatch(
    items: Iterable[Item], *, key: Callable[[Item], Hashable],
    start: Callable[[Item], Future[Result]], limit: int, group_limit: int,
    stopped: Callable[[], bool],
) -> Iterator[tuple[Item, Future[Result]]]:
    """Yield settled work before admitting replacements, including after a stop.

    Callers serialize final admission with their cancellation/authority checks
    inside start. They can stop dispatch while consuming a result and still
    receive every already-started operation's result.
    """
    if limit < 1 or group_limit < 1:
        raise ValueError("Concurrency limits must be positive")
    queues: dict[Hashable, deque[Item]] = {}
    for item in items:
        queues.setdefault(key(item), deque()).append(item)
    groups = deque(queues)
    running: Counter[Hashable] = Counter()
    pending: dict[Future[Result], tuple[Hashable, Item]] = {}
    try:
        while pending or (groups and not stopped()):
            settled = [future for future in pending if future.done()]
            if settled:
                for future in settled:
                    group, item = pending.pop(future)
                    running[group] -= 1
                    yield item, future
                continue

            if len(pending) < limit and groups and not stopped():
                for _ in range(len(groups)):
                    group = groups.popleft()
                    queue = queues[group]
                    if running[group] >= group_limit:
                        groups.append(group)
                        continue
                    item = queue.popleft()
                    if queue:
                        groups.append(group)
                    try:
                        future = start(item)
                    except Exception as error:
                        future = Future()
                        future.set_exception(error)
                    pending[future] = group, item
                    running[group] += 1
                    break
                else:
                    wait(pending, return_when=FIRST_COMPLETED)
            elif pending:
                wait(pending, return_when=FIRST_COMPLETED)
    finally:
        # Abandoning the iterator cannot revoke an operation already dispatched.
        wait(pending)
