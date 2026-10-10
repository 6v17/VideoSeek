"""Release a daemon server thread without freezing the UI thread."""

from __future__ import annotations

import threading


def release_server_thread(thread, *, wait: bool | None = None, timeout: float = 3.0) -> threading.Thread | None:
    """Join ``thread`` here only when the caller is not the UI thread.

    A click or quit on the UI thread asks the server to exit and joins it in
    the background. Worker threads still wait, so a restart can bind the port.
    """
    if thread is None:
        return None
    if wait is None:
        wait = threading.current_thread() is not threading.main_thread()
    if wait:
        thread.join(timeout=timeout)
        return None
    waiter = threading.Thread(
        target=thread.join,
        kwargs={"timeout": timeout},
        name="ServerStop",
        daemon=True,
    )
    waiter.start()
    return waiter
