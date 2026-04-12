def shutdown_thread(thread, stop_first=False, allow_terminate=True):
    if not thread or not thread.isRunning():
        return
    if stop_first and hasattr(thread, "stop"):
        thread.stop()
    thread.quit()
    if thread.wait(1500):
        return
    thread.requestInterruption()
    if thread.wait(1500):
        return
    if allow_terminate:
        thread.terminate()
        thread.wait(1000)
