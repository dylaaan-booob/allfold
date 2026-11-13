"""A long-lived, bounded, round-robin scheduler; pages keep their native budget."""
from collections import Counter, deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import threading
import time


class SettledFuture(Future):
    """Only the owner can settle work; Future.cancel is not physical cleanup."""

    def cancel(self):
        return False


@dataclass
class _Queued:
    group: object
    run: object
    future: Future
    cancel_event: object
    deadline: float | None
    discarded: object


class DynamicScheduler:
    """Count executing Paper jobs, including their finally/cleanup, by Service.

    None is the single public/API group. Queueing never creates pages or clients.
    Discard callbacks must perform only bounded local settlement without network.
    """

    def __init__(self, *, limit=4, group_limit=2):
        if type(limit) is not int or type(group_limit) is not int or not 1 <= group_limit <= limit <= 64:
            raise ValueError('Task limits require 1 <= group_limit <= limit <= 64')
        self._limit, self._group_limit = limit, group_limit
        self._condition = threading.Condition()
        self._queues, self._groups, self._running = {}, deque(), Counter()
        self._active = 0
        self._closed = False
        self._pool = ThreadPoolExecutor(max_workers=limit, thread_name_prefix='paper-work')
        self._thread = threading.Thread(target=self._dispatch, name='paper-dispatch', daemon=False)
        self._thread.start()

    def submit(self, group, run, *, cancel_event=None, deadline=None, discarded=None):
        future = SettledFuture()
        with self._condition:
            if self._closed:
                raise RuntimeError('Task scheduler is closed')
            if group not in self._queues:
                self._queues[group] = deque()
                self._groups.append(group)
            self._queues[group].append(_Queued(group, run, future, cancel_event, deadline, discarded))
            self._condition.notify_all()
        return future

    def wake(self):
        with self._condition:
            self._condition.notify_all()

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def join(self):
        self._thread.join()
        self._pool.shutdown(wait=True)

    @staticmethod
    def _settle(item, reason=None):
        try:
            result = item.discarded(reason) if reason and item.discarded else None if reason else item.run()
        except BaseException as error:
            item.future.set_exception(error)
        else:
            item.future.set_result(result)

    def _returned(self, item):
        with self._condition:
            self._active -= 1
            self._running[item.group] -= 1
            if not self._running[item.group]:
                del self._running[item.group]
            self._condition.notify_all()

    def _dispatch(self):
        while True:
            discarded, ready = [], []
            with self._condition:
                now, nearest = time.monotonic(), None
                for group in tuple(self._groups):
                    kept = deque()
                    for item in self._queues[group]:
                        reason = ('closed' if self._closed else
                                  'cancelled' if item.cancel_event is not None and item.cancel_event.is_set() else
                                  'expired' if item.deadline is not None and item.deadline <= now else None)
                        if reason:
                            discarded.append((item, reason))
                        else:
                            kept.append(item)
                            if item.deadline is not None:
                                nearest = item.deadline if nearest is None else min(nearest, item.deadline)
                    if kept:
                        self._queues[group] = kept
                    else:
                        del self._queues[group]
                        self._groups.remove(group)
                while self._active < self._limit and self._groups and not self._closed:
                    for _ in range(len(self._groups)):
                        group = self._groups.popleft()
                        if self._running[group] >= self._group_limit:
                            self._groups.append(group)
                            continue
                        item = self._queues[group].popleft()
                        if self._queues[group]:
                            self._groups.append(group)
                        else:
                            del self._queues[group]
                        self._active += 1
                        self._running[group] += 1
                        ready.append(item)
                        break
                    else:
                        break
                done = self._closed and not self._active and not self._groups
                if not discarded and not ready and not done:
                    self._condition.wait(None if nearest is None else max(0, nearest - time.monotonic()))
                    continue
            # No user callback, SQLite operation or finally runs under this lock.
            for item, reason in discarded:
                self._settle(item, reason)
            for item in ready:
                try:
                    actual = self._pool.submit(self._settle, item)
                except BaseException as error:
                    # A failed worker submission still has an owned qualification
                    # to settle. Its callback receives a fixed, non-sensitive code.
                    self._settle(item, 'submission_failed')
                    self._returned(item)
                else:
                    actual.add_done_callback(lambda _, item=item: self._returned(item))
            if done:
                return
