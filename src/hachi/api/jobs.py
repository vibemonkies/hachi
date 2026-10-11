"""Background job threads. Job state lives in SQLite, so a restart can recover every job."""

import logging
import queue
import threading
from collections.abc import Callable

log = logging.getLogger("hachi.api")

_STOP = object()


class JobRunner:
    """One worker thread per job kind; jobs of a kind run one at a time, in submission order.

    Imports are CPU/disk heavy and reports may queue for a shared model, so serial execution
    per kind keeps a laptop responsive and keeps GPU use to one job at a time.
    """

    def __init__(self, handlers: dict[str, Callable[[str], None]]) -> None:
        self._handlers = handlers
        self._queues: dict[str, queue.Queue] = {kind: queue.Queue() for kind in handlers}
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for kind, jobs in self._queues.items():
            thread = threading.Thread(
                target=self._work, args=(kind, jobs), name=f"hachi-{kind}-jobs", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def submit(self, kind: str, job_id: str) -> None:
        self._queues[kind].put(job_id)

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """For tests and the handoff check: wait until every submitted job has finished."""
        done = threading.Event()

        def join() -> None:
            for jobs in self._queues.values():
                jobs.join()
            done.set()

        threading.Thread(target=join, daemon=True).start()
        return done.wait(timeout)

    def stop(self, timeout: float = 10.0) -> None:
        for jobs in self._queues.values():
            jobs.put(_STOP)
        for thread in self._threads:
            thread.join(timeout)
        self._threads.clear()

    def _work(self, kind: str, jobs: queue.Queue) -> None:
        handler = self._handlers[kind]
        while True:
            job_id = jobs.get()
            try:
                if job_id is _STOP:
                    return
                handler(job_id)
            except Exception as exc:  # a handler records its own failure; never kill the worker
                # Type only: validation messages can quote input values.
                log.error("%s job %s crashed (%s)", kind, job_id, type(exc).__name__)
            finally:
                jobs.task_done()
