"""Dynamic admission exercises actual worker lifetimes, rather than queue snapshots."""
import threading
import time

import pytest

from allfold.application.dynamic_dispatch import DynamicScheduler


def test_dynamic_service_round_robin_caps_and_idle_reuse():
    entered, release = threading.Event(), threading.Event()
    order, lock = [], threading.Lock()

    def work(label, block=False):
        with lock:
            order.append(label)
        if block:
            entered.set()
            assert release.wait(3)
        return label

    scheduler = DynamicScheduler(limit=1, group_limit=1)
    try:
        first = scheduler.submit('old', lambda: work('first', True))
        assert entered.wait(2)
        old = [scheduler.submit('old', lambda i=i: work(f'old-{i}')) for i in range(4)]
        new = scheduler.submit('new', lambda: work('new'))
        release.set()
        assert first.result(3) == 'first'
        assert new.result(3) == 'new'
        assert order.index('new') <= 2
        for future in old:
            future.result(3)
        assert scheduler.submit(None, lambda: work('after-idle')).result(3) == 'after-idle'
    finally:
        release.set()
        scheduler.close()
        scheduler.join()


def test_cancelled_and_expired_queue_settle_without_late_start():
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    scheduler = DynamicScheduler(limit=1, group_limit=1)

    def held():
        entered.set()
        assert release.wait(3)

    try:
        running = scheduler.submit('a', held)
        assert entered.wait(2)
        cancelled = scheduler.submit('b', lambda: pytest.fail('cancelled work started'),
            cancel_event=stopped, discarded=lambda reason: reason)
        expired = scheduler.submit('c', lambda: pytest.fail('expired work started'),
            deadline=time.monotonic() + .04, discarded=lambda reason: reason)
        assert cancelled.cancel() is False  # a Future is not resource cancellation
        stopped.set()
        scheduler.wake()
        assert cancelled.result(2) == 'cancelled'
        assert expired.result(2) == 'expired'
        assert not running.done()
    finally:
        release.set()
        scheduler.close()
        scheduler.join()


def test_global_and_service_limits_hold_until_workers_really_return():
    barrier = threading.Barrier(3)
    release = threading.Event()
    scheduler = DynamicScheduler(limit=2, group_limit=1)

    def held():
        barrier.wait(3)
        assert release.wait(3)

    try:
        a = scheduler.submit('a', held)
        a2_entered = threading.Event()
        a2 = scheduler.submit('a', a2_entered.set)
        b = scheduler.submit('b', held)
        barrier.wait(3)
        assert not a2_entered.is_set()
        release.set()
        for future in (a, a2, b):
            future.result(3)
        assert a2_entered.is_set()
    finally:
        release.set()
        scheduler.close()
        scheduler.join()
