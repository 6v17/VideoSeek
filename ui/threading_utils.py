def shutdown_thread(thread, stop_first=False, allow_terminate=True, wait_ms=1500):
    if not thread or not thread.isRunning():
        return
    if stop_first and hasattr(thread, "stop"):
        thread.stop()
    thread.requestInterruption()
    thread.quit()
    total_wait = max(int(wait_ms), 8000) if not allow_terminate else int(wait_ms)
    if thread.wait(total_wait):
        return
    thread.requestInterruption()
    if thread.wait(total_wait):
        return
    if allow_terminate:
        thread.terminate()
        thread.wait(1000)
