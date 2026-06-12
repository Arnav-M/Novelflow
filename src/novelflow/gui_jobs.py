"""Background job execution for the Novelflow GUI.

Centralizes the worker-thread pattern the GUI used to copy-paste: every job
runs on a daemon thread, gets its *own* cancel event (so cancelling one job
can never abort an unrelated one), and is guaranteed to report exactly one
outcome (done / cancelled / error) back on the UI thread — no matter how the
worker exits — so the UI can never be left stuck in a busy state.
"""

from __future__ import annotations

import threading
from typing import Callable


class JobCancelled(Exception):
    """Raised by job workers to signal a cooperative cancellation."""


class JobRunner:
    """Runs one logical background job at a time for the GUI.

    ``ui`` marshals a function call onto the Tk main thread (the app's
    queue-based dispatcher). Workers receive their cancel event as the sole
    argument and should check it at safe points; raising :class:`JobCancelled`
    routes to ``on_cancelled``.
    """

    def __init__(self, ui: Callable) -> None:
        self._ui = ui
        self._cancel_event = threading.Event()

    @property
    def cancel_event(self) -> threading.Event:
        """Cancel event of the most recently started job."""
        return self._cancel_event

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(
        self,
        work: Callable[[threading.Event], object],
        *,
        on_done: Callable | None = None,
        on_cancelled: Callable | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> threading.Event:
        """Run ``work(cancel_event)`` on a daemon thread.

        Exactly one of the callbacks fires on the UI thread when the worker
        finishes. ``on_done`` receives the worker's return value; ``on_error``
        receives a message string.
        """
        cancel = threading.Event()
        self._cancel_event = cancel

        def runner() -> None:
            try:
                result = work(cancel)
            except JobCancelled:
                if on_cancelled is not None:
                    self._ui(on_cancelled)
            except BaseException as exc:  # noqa: BLE001 - never leave the UI stuck busy
                if on_error is not None:
                    self._ui(on_error, str(exc) or type(exc).__name__)
            else:
                if on_done is not None:
                    self._ui(on_done, result)

        threading.Thread(target=runner, daemon=True).start()
        return cancel
