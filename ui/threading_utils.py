# Still-running QThreads kept here so Qt does not destroy them on quit.
_PARKED_THREADS: list = []


def parked_threads() -> list:
    return list(_PARKED_THREADS)


def park_running_thread(thread) -> None:
    """Retain ``thread`` if it is still running."""
    if thread is None:
        return
    try:
        running = bool(thread.isRunning())
    except Exception:
        running = True
    if not running:
        return
    if thread not in _PARKED_THREADS:
        _PARKED_THREADS.append(thread)


def release_finished_thread(owner, attr: str, thread) -> None:
    """Drop ``owner.attr`` when it still points at ``thread``, then delete it.

    Call this from ``QThread.finished``, not from a signal emitted inside
    ``run()``. A thread that is still running is parked and not deleted.
    """
    if thread is None:
        return
    if getattr(owner, attr, None) is thread:
        setattr(owner, attr, None)
    try:
        running = bool(thread.isRunning())
    except Exception:
        running = True
    if running:
        park_running_thread(thread)
        return
    try:
        thread.deleteLater()
    except Exception:
        pass


def connect_on_receiver(sender, signature: str, receiver, slot):
    """Queue ``slot`` onto ``receiver``'s thread.

    A bare lambda has no QObject, so a worker can run it before ``run()``
    returns. ``signature`` is the Qt signal, such as ``result_ready(QVariantMap)``.
    """
    from PySide6.QtCore import QObject, SIGNAL

    connection = QObject.connect(sender, SIGNAL(signature), receiver, slot)
    if not connection:
        raise RuntimeError(f"Could not connect {signature}")
    return connection


def bind_thread_release(owner, attr: str, thread) -> None:
    """Release ``thread`` after Qt reports that it has stopped."""
    if thread is None:
        return
    thread.finished.connect(lambda finished=thread, name=attr: release_finished_thread(owner, name, finished))


def shutdown_thread(thread, stop_first=False, allow_terminate=False, wait_ms=1500):
    """Stop a QThread without destroying it while it is still running.

    ``allow_terminate`` stays off unless the caller is sure the thread is stuck
    in native I/O and does not hold the library write lock. A thread that is
    still running after the wait is parked so its QObject is not deleted.
    """
    if not thread or not thread.isRunning():
        return
    try:
        thread.blockSignals(True)
    except Exception:
        pass
    if stop_first and hasattr(thread, "stop"):
        thread.stop()
    thread.requestInterruption()
    thread.quit()
    # Soft path still needs a finite wait — never hang forever.
    soft_wait = max(int(wait_ms), 3000) if not allow_terminate else int(wait_ms)
    if thread.wait(soft_wait):
        return
    thread.requestInterruption()
    if thread.wait(min(soft_wait, 2000)):
        return
    if allow_terminate:
        thread.terminate()
        if thread.wait(1000):
            return
    park_running_thread(thread)
