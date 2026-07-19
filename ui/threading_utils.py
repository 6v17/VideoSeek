def shutdown_thread(thread, stop_first=False, allow_terminate=True, wait_ms=1500):
    """Stop a QThread. On app quit, prefer allow_terminate=True so the process can exit."""
    if not thread or not thread.isRunning():
        return
    if stop_first and hasattr(thread, "stop"):
        thread.stop()
    thread.requestInterruption()
    thread.quit()
    # Soft path (allow_terminate=False) still needs a finite wait — never hang forever.
    soft_wait = max(int(wait_ms), 3000) if not allow_terminate else int(wait_ms)
    if thread.wait(soft_wait):
        return
    thread.requestInterruption()
    if thread.wait(min(soft_wait, 2000)):
        return
    if allow_terminate:
        thread.terminate()
        thread.wait(1000)
