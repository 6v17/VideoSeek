import os
import sys

from PySide6.QtCore import Qt, QTimer

from src.utils import get_resource_path


def _prepare_vlc_runtime():
    vlc_dir = get_resource_path("vlc_lib")
    if not os.path.isdir(vlc_dir):
        return None, None

    plugins_dir = os.path.join(vlc_dir, "plugins")
    os.environ["PATH"] = vlc_dir + os.pathsep + os.environ.get("PATH", "")
    if os.path.isdir(plugins_dir):
        os.environ["VLC_PLUGIN_PATH"] = plugins_dir
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(vlc_dir)
        except OSError:
            pass
    os.environ["PYTHON_VLC_LIB_PATH"] = os.path.join(vlc_dir, "libvlc.dll")

    try:
        import vlc
    except ImportError:
        return None, None
    return vlc, vlc_dir


def warmup_vlc_runtime():
    vlc_module, _vlc_dir = _prepare_vlc_runtime()
    if vlc_module is None:
        return False

    args = ["--quiet", "--no-video-title-show"]
    if sys.platform.startswith("linux"):
        args.append("--no-xlib")

    instance = None
    player = None
    try:
        instance = vlc_module.Instance(args)
        player = instance.media_player_new()
        return player is not None
    except Exception:
        return False
    finally:
        if player is not None:
            try:
                player.release()
            except Exception:
                pass
        if instance is not None:
            try:
                instance.release()
            except Exception:
                pass


class VlcPreviewPlayer:
    def __init__(self, host_widget):
        self.host_widget = host_widget
        self.host_widget.setAttribute(Qt.WA_NativeWindow, True)
        self._timer = QTimer(self.host_widget)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._handle_timeout)
        self._stop_at_ms = -1
        self._locked_stop_at_ms = -1
        self._user_unlocked = False
        self._instance = None
        self._player = None
        self._released = False
        self._initialize()

    def is_available(self):
        return self._player is not None and not self._released

    def play(self, video_path, start_sec, stop_sec=None):
        if not self.is_available():
            return False

        start_sec = max(0.0, float(start_sec))
        stop_sec = None if stop_sec is None else max(start_sec, float(stop_sec))

        self._reset_for_replay()
        media = self._instance.media_new(os.fspath(video_path), f":start-time={start_sec:.3f}")
        self._player.set_media(media)
        self._bind_output_window()
        self._stop_at_ms = -1 if stop_sec is None else int(stop_sec * 1000)
        self._locked_stop_at_ms = self._stop_at_ms
        self._user_unlocked = False
        result = self._player.play()
        if result == -1:
            self._stop_at_ms = -1
            self._locked_stop_at_ms = -1
            return False
        if self._stop_at_ms > 0:
            self._timer.start()
        return True

    def stop(self):
        if self._released:
            return
        self._timer.stop()
        self._stop_at_ms = -1
        self._locked_stop_at_ms = -1
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                pass
            try:
                self._player.set_media(None)
            except Exception:
                pass

    def shutdown(self):
        if self._released:
            return
        self._released = True
        self._timer.stop()
        self._stop_at_ms = -1
        self._locked_stop_at_ms = -1
        self._user_unlocked = False
        if self._player is not None:
            self._detach_output_window()
            try:
                self._player.stop()
            except Exception:
                pass
            try:
                self._player.set_media(None)
            except Exception:
                pass
            try:
                self._player.audio_set_mute(True)
            except Exception:
                pass
            self._player.release()
            self._player = None
        if self._instance is not None:
            self._instance.release()
            self._instance = None

    def _initialize(self):
        vlc_module, vlc_dir = _prepare_vlc_runtime()
        if vlc_module is None:
            return

        args = ["--quiet", "--no-video-title-show"]
        if sys.platform.startswith("linux"):
            args.append("--no-xlib")

        try:
            self._instance = vlc_module.Instance(args)
            self._player = self._instance.media_player_new()
        except Exception:
            self._instance = None
            self._player = None

    def get_time(self):
        if self._player is None or self._released:
            return -1
        return int(self._player.get_time())

    def get_length(self):
        if self._player is None or self._released:
            return -1
        return int(self._player.get_length())

    def is_playing(self):
        if self._player is None or self._released:
            return False
        return bool(self._player.is_playing())

    def pause(self):
        if self._player is None or self._released:
            return
        try:
            self._player.pause()
        except Exception:
            pass

    def resume(self):
        if self._player is None or self._released:
            return False
        result = self._player.play()
        if result == -1:
            return False
        if self._stop_at_ms > 0:
            self._timer.start()
        return True

    def unlock_full_playback(self):
        if self._released:
            return
        self._user_unlocked = True
        self._stop_at_ms = -1
        self._timer.stop()

    def set_time(self, ms, unlock=False):
        if self._player is None or self._released:
            return
        if unlock:
            self.unlock_full_playback()
        try:
            self._player.set_time(int(ms))
        except Exception:
            pass

    def has_locked_window(self):
        return not self._released and self._locked_stop_at_ms > 0 and not self._user_unlocked

    def _bind_output_window(self):
        if self._player is None or self._released:
            return
        window_id = int(self.host_widget.winId())
        if sys.platform == "win32":
            self._player.set_hwnd(window_id)
        elif sys.platform == "darwin":
            self._player.set_nsobject(window_id)
        else:
            self._player.set_xwindow(window_id)

    def _detach_output_window(self):
        if self._player is None:
            return
        try:
            if sys.platform == "win32":
                self._player.set_hwnd(0)
            elif sys.platform == "darwin":
                self._player.set_nsobject(0)
            else:
                self._player.set_xwindow(0)
        except Exception:
            pass

    def _handle_timeout(self):
        if self._player is None or self._released or self._stop_at_ms <= 0:
            return
        if self._player.get_time() >= self._stop_at_ms:
            self._pause_at_stop_time()

    def _reset_for_replay(self):
        if self._released:
            return
        self._timer.stop()
        self._stop_at_ms = -1
        self._locked_stop_at_ms = -1
        self._user_unlocked = False
        if self._player is None:
            return
        try:
            self._player.pause()
        except Exception:
            pass
        try:
            self._player.set_media(None)
        except Exception:
            pass

    def _pause_at_stop_time(self):
        stop_at_ms = self._stop_at_ms
        self._timer.stop()
        self._stop_at_ms = -1
        if self._player is None or self._released:
            return
        try:
            if stop_at_ms > 0:
                self._player.set_time(stop_at_ms)
        except Exception:
            pass
        try:
            self._player.pause()
        except Exception:
            pass
