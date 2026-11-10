from concurrent.futures import Future
from threading import Event, Thread

from allfold.application.bounded_dispatch import bounded_dispatch


def test_dispatch_rotates_services_and_waits_for_actual_settlement():
    jobs = [('a', 1), ('a', 2), ('a', 3), ('b', 1), ('c', 1)]
    launched = []
    pending = {}
    first_wave, second_wave, last_wave = Event(), Event(), Event()

    def start(job):
        future = pending[job] = Future()
        launched.append(job)
        if len(launched) == 3:
            first_wave.set()
        if len(launched) == 4:
            second_wave.set()
        if len(launched) == 5:
            last_wave.set()
        return future

    finished = []
    worker = Thread(target=lambda: finished.extend(
        bounded_dispatch(jobs, key=lambda job: job[0], start=start,
                         limit=3, group_limit=1, stopped=lambda: False)), daemon=True)
    worker.start()
    assert first_wave.wait(2)
    assert launched == [('a', 1), ('b', 1), ('c', 1)]
    pending['b', 1].set_result('saved')
    pending['c', 1].set_result('saved')
    assert not second_wave.wait(.05)  # Spare global slots cannot override the Service limit.
    pending['a', 1].set_result('saved')
    assert second_wave.wait(2)
    pending['a', 2].set_result('saved')
    assert last_wave.wait(2)
    assert worker.is_alive()
    pending['a', 3].set_result('saved')
    worker.join(2)
    assert not worker.is_alive()
    assert {job for job, result in finished if result.result() == 'saved'} == set(jobs)


def test_dispatch_stop_prevents_new_work_and_drains_already_started_operations():
    pending = {}
    queued = Event()
    stopped = Event()

    def start(job):
        future = pending[job] = Future()
        if len(pending) == 2:
            queued.set()
        return future

    outcomes = {}

    def execute():
        for job, result in bounded_dispatch(range(5), key=lambda job: job, start=start,
                                            limit=2, group_limit=1, stopped=stopped.is_set):
            outcomes[job] = result.result()
            if outcomes[job] == 'uncertain':
                stopped.set()

    worker = Thread(target=execute, daemon=True)
    worker.start()
    assert queued.wait(2)
    pending[0].set_result('uncertain')
    assert stopped.wait(2)
    assert worker.is_alive()
    pending[1].set_result('confirmed')
    worker.join(2)
    assert not worker.is_alive()
    assert outcomes == {0: 'uncertain', 1: 'confirmed'}
    assert list(pending) == [0, 1]
