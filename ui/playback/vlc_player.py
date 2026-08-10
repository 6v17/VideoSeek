import os
import sys

from PySide6.QtCore import Qt, QTimer

from src.app.logging_utils import get_logger
from src.utils import get_resource_path

logger = get_logger("vlc_player")


def _log_vlc_warning(action: str, exc: BaseException | None = None) -> None:
    if exc is not None:
        logger.warning("VLC %s failed: %s", action, exc, exc_info=True)
    else:
        logger.warning("VLC %s failed", action)


def _log_vlc_debug(action: str, exc: BaseException | None = None) -> None:
    if exc is not None:
        logger.debug("VLC %s: %s", action, exc, exc_info=True)
    else:
        logger.debug("VLC %s skipped", action)


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
        except OSError as exc:
            _log_vlc_debug("add_dll_directory", exc)
    if sys.platform == "win32":
        os.environ["PYTHON_VLC_LIB_PATH"] = os.path.join(vlc_dir, "libvlc.dll")
    else:
        # Bundled Windows DLLs must not override host libvlc discovery.
        os.environ.pop("PYTHON_VLC_LIB_PATH", None)

    try:
        import vlc
    except ImportError:
        return None, None
    return vlc, vlc_dir


def is_http_media_url(video_path: str) -> bool:
    text = str(video_path or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


# Back-compat alias used inside this module.
_is_http_media_url = is_http_media_url


def _vlc_embed_instance_args():
    # Network caching helps HTTP team play_url; keep modest so start is still snappy.
    args = [
        "--quiet",
        "--no-video-title-show",
        "--network-caching=800",
        "--http-caching=800",
    ]
    if sys.platform.startswith("linux"):
        args.append("--no-xlib")
    return args


def _build_vlc_media_options(video_path: str, start_sec: float) -> list[str]:
    """Media options for preview. HTTP avoids :start-time (slow linear demux over HTTP)."""
    options: list[str] = []
    if _is_http_media_url(video_path):
        options.extend(
            [
                ":network-caching=800",
                ":http-caching=800",
            ]
        )
        return options
    start = max(0.0, float(start_sec or 0.0))
    if start > 0.0:
        options.append(f":start-time={start:.3f}")
    return options


def create_vlc_preview_instance():
    """One libvlc Instance for multiple MediaPlayers (e.g. remix compare). Returns None if VLC is unavailable."""
    vlc_module, _ = _prepare_vlc_runtime()
    if vlc_module is None:
        return None
    try:
        return vlc_module.Instance(_vlc_embed_instance_args())
    except Exception as exc:
        _log_vlc_warning("create preview instance", exc)
        return None


def warmup_vlc_runtime():
    vlc_module, _vlc_dir = _prepare_vlc_runtime()
    if vlc_module is None:
        return False

    args = _vlc_embed_instance_args()

    instance = None
    player = None
    try:
        instance = vlc_module.Instance(args)
        player = instance.media_player_new()
        return player is not None
    except Exception as exc:
        _log_vlc_warning("warmup runtime", exc)
        return False
    finally:
        if player is not None:
            try:
                player.release()
            except Exception as exc:
                _log_vlc_debug("release warmup player", exc)
        if instance is not None:
            try:
                instance.release()
            except Exception as exc:
                _log_vlc_debug("release warmup instance", exc)


class VlcPreviewPlayer:
    def __init__(self, host_widget, *, shared_instance=None):
        self.host_widget = host_widget
        self.host_widget.setAttribute(Qt.WA_NativeWindow, True)
        self._timer = QTimer(self.host_widget)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._handle_timeout)
        self._stop_at_ms = -1
        self._locked_stop_at_ms = -1
        self._user_unlocked = False
        self._owns_instance = shared_instance is None
        self._instance = None
        self._player = None
        self._current_media = None
        self._released = False
        self._current_video_path = ""
        self._pending_seek_ms = None
        self._play_busy = False
        self._session_active = False
        if shared_instance is not None:
            self._instance = shared_instance
            try:
                self._player = self._instance.media_player_new()
            except Exception as exc:
                _log_vlc_warning("create media player", exc)
                self._player = None
        else:
            self._initialize()

    def is_available(self):
        return self._player is not None and not self._released

    def play(self, video_path, start_sec, stop_sec=None):
        if not self.is_available():
            return False
        if getattr(self, "_play_busy", False):
            return False
        self._play_busy = True
        try:
            return self._play_impl(video_path, start_sec, stop_sec=stop_sec)
        finally:
            self._play_busy = False

    def _play_impl(self, video_path, start_sec, stop_sec=None):
        if not self.is_available():
            return False

        self._current_video_path = os.fspath(video_path)
        self._pending_seek_ms = None
        start_sec = max(0.0, float(start_sec))
        stop_sec = None if stop_sec is None else max(start_sec, float(stop_sec))
        remote = _is_http_media_url(self._current_video_path)

        self._reset_for_replay()
        if not self.is_available():
            return False
        # Keep hwnd bound across media swaps; clearing to None first can spawn a
        # standalone "VLC (Direct3D11 output)" window on the second play.
        self.rebind_output_window()
        try:
            options = _build_vlc_media_options(self._current_video_path, start_sec)
            media = self._instance.media_new(self._current_video_path, *options)
            self._set_media(media)
            self.rebind_output_window()
        except Exception as exc:
            _log_vlc_warning("prepare media playback", exc)
            return False
        self._stop_at_ms = -1 if stop_sec is None else int(stop_sec * 1000)
        self._locked_stop_at_ms = self._stop_at_ms
        self._user_unlocked = False
        try:
            result = self._player.play()
        except Exception as exc:
            self._stop_at_ms = -1
            self._locked_stop_at_ms = -1
            _log_vlc_warning("start playback", exc)
            return False
        if result == -1:
            self._stop_at_ms = -1
            self._locked_stop_at_ms = -1
            return False
        try:
            self._player.audio_set_mute(False)
        except Exception as exc:
            _log_vlc_debug("unmute on play", exc)
        # One immediate + one delayed rebind is enough; stacking many timers under
        # rapid enlarge-preview clicks made the UI feel frozen.
        self.rebind_output_window()
        QTimer.singleShot(80, self.rebind_output_window)
        if remote and start_sec > 0.05:
            # Browser-like: open stream first, then byte-range seek — much faster than :start-time.
            self._pending_seek_ms = int(start_sec * 1000)
            self._schedule_pending_seek()
        if self._stop_at_ms > 0:
            self._timer.start()
        self._session_active = True
        return True

    def release_native_output(self):
        """Detach libvlc from the host HWND so QMediaPlayer can use the same widget."""
        self.suspend()
        self._detach_output_window()

    def _schedule_pending_seek(self, attempt: int = 0) -> None:
        if self._released or self._player is None or self._pending_seek_ms is None:
            return
        target_ms = int(self._pending_seek_ms)
        applied = False
        try:
            length_ms = int(self._player.get_length() or 0)
            playing = bool(self._player.is_playing())
            if playing or length_ms > 0 or attempt >= 4:
                self._player.set_time(target_ms)
                applied = True
                current = int(self._player.get_time() or -1)
                if current >= 0 and abs(current - target_ms) <= 1500:
                    self._pending_seek_ms = None
                    return
        except Exception as exc:
            _log_vlc_debug("pending http seek", exc)
        if attempt >= 20:
            self._pending_seek_ms = None
            return
        delay_ms = 80 if applied else 120
        QTimer.singleShot(delay_ms, lambda: self._schedule_pending_seek(attempt + 1))

    def stop(self):
        """Hard stop. Prefer ``suspend()`` / ``clear_session()`` from UI paths to avoid hangs."""
        self.clear_session()

    def suspend(self):
        """Pause and mute without detaching the embed hwnd."""
        if self._released or self._player is None:
            return
        self._timer.stop()
        self._stop_at_ms = -1
        self._locked_stop_at_ms = -1
        self._pending_seek_ms = None
        try:
            self._player.audio_set_mute(True)
        except Exception as exc:
            _log_vlc_debug("mute on suspend", exc)
        self._set_paused(True)

    def clear_session(self):
        """End the current clip so UI cannot resume it; avoids native stop()/set_media(None)."""
        self.suspend()
        self._current_video_path = ""
        self._session_active = False
        self._user_unlocked = False

    def shutdown(self, fast=False):
        """Stop playback and release libvlc resources.

        ``fast=True`` skips native ``stop()`` / ``release()`` which can block the UI
        thread on Windows. Prefer ``suspend()`` when merely hiding a dialog.
        """
        if self._released:
            return
        self._released = True
        self._timer.stop()
        self._stop_at_ms = -1
        self._locked_stop_at_ms = -1
        self._user_unlocked = False
        self._pending_seek_ms = None
        self._current_video_path = ""
        if self._player is not None:
            try:
                self._player.audio_set_mute(True)
            except Exception as exc:
                _log_vlc_debug("mute before shutdown", exc)
            self._set_paused(True)
            if fast:
                # Keep hwnd attached; only drop media. Detaching while alive spawns D3D popup.
                try:
                    self._player.set_media(None)
                except Exception as exc:
                    _log_vlc_debug("fast clear media", exc)
                old = self._current_media
                self._current_media = None
                self._release_media_object(old)
                self._player = None
                self._instance = None
                return
            try:
                self._player.stop()
            except Exception as exc:
                _log_vlc_debug("stop before shutdown", exc)
            self._clear_media()
            self._detach_output_window()
            try:
                self._player.release()
            except Exception as exc:
                _log_vlc_debug("release player", exc)
            self._player = None
        if self._owns_instance and self._instance is not None:
            try:
                self._instance.release()
            except Exception as exc:
                _log_vlc_debug("release instance", exc)
        self._instance = None

    def _initialize(self):
        vlc_module, vlc_dir = _prepare_vlc_runtime()
        if vlc_module is None:
            return

        args = _vlc_embed_instance_args()

        try:
            self._instance = vlc_module.Instance(args)
            self._player = self._instance.media_player_new()
        except Exception as exc:
            _log_vlc_warning("initialize player", exc)
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
        if self._player is None or self._released or not self._session_active:
            return False
        return bool(self._player.is_playing())

    def pause(self):
        if self._player is None or self._released:
            return
        self._set_paused(True)

    def _set_paused(self, paused: bool) -> None:
        """Force pause/resume. Prefer this over ``pause()``, which toggles in libvlc."""
        if self._player is None or self._released:
            return
        try:
            self._player.set_pause(1 if paused else 0)
            return
        except Exception as exc:
            _log_vlc_debug("set_pause", exc)
        # Fallback: only toggle when needed.
        try:
            playing = bool(self._player.is_playing())
            if paused and playing:
                self._player.pause()
            elif (not paused) and (not playing):
                self._player.pause()
        except Exception as exc:
            _log_vlc_debug("pause toggle fallback", exc)

    def resume(self):
        if self._player is None or self._released or not self._session_active:
            return False
        if self._pending_seek_ms is not None and self._restart_from_ms(self._pending_seek_ms):
            return True
        if self._should_restart_media():
            restart_ms = self._pending_seek_ms
            if restart_ms is None:
                restart_ms = 0
            if self._restart_from_ms(restart_ms):
                return True
        result = self._player.play()
        if result == -1:
            return False
        try:
            self._player.audio_set_mute(False)
        except Exception as exc:
            _log_vlc_debug("unmute on resume", exc)
        self._pending_seek_ms = None
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
        self._pending_seek_ms = max(0, int(ms))
        try:
            self._player.set_time(self._pending_seek_ms)
        except Exception as exc:
            _log_vlc_debug("set playback time", exc)

    def has_locked_window(self):
        return not self._released and self._locked_stop_at_ms > 0 and not self._user_unlocked

    def set_host_widget(self, host_widget) -> None:
        """Move the embed surface to another native host (one player, many surfaces)."""
        if host_widget is None or host_widget is self.host_widget:
            return
        previous = self.host_widget
        if previous is not None and hasattr(previous, "set_player"):
            try:
                previous.set_player(None)
            except Exception as exc:
                _log_vlc_debug("clear previous host player", exc)
        self.host_widget = host_widget
        self.host_widget.setAttribute(Qt.WA_NativeWindow, True)
        if hasattr(self.host_widget, "set_player"):
            try:
                self.host_widget.set_player(self)
            except Exception as exc:
                _log_vlc_debug("attach host player", exc)
        # Keep the QTimer alive on a living QObject; re-parent to the new host.
        try:
            if self._timer is not None:
                self._timer.setParent(self.host_widget)
        except Exception as exc:
            _log_vlc_debug("reparent playback timer", exc)
        self.rebind_output_window()
        QTimer.singleShot(80, self.rebind_output_window)

    def rebind_output_window(self):
        """Re-attach libvlc output after host resize / fullscreen toggles."""
        self._bind_output_window()

    def _bind_output_window(self):
        if self._player is None or self._released:
            return
        try:
            # Force native window creation before reading winId.
            self.host_widget.setAttribute(Qt.WA_NativeWindow, True)
            window_id = int(self.host_widget.winId())
        except Exception as exc:
            _log_vlc_debug("read host window id", exc)
            return
        try:
            if sys.platform == "win32":
                self._player.set_hwnd(window_id)
            elif sys.platform == "darwin":
                self._player.set_nsobject(window_id)
            else:
                self._player.set_xwindow(window_id)
        except Exception as exc:
            _log_vlc_debug("bind output window", exc)

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
        except Exception as exc:
            _log_vlc_debug("detach output window", exc)

    def _release_media_object(self, media) -> None:
        if media is None:
            return
        try:
            media.release()
        except Exception as exc:
            _log_vlc_debug("release media", exc)

    def _clear_media(self) -> None:
        if self._player is not None:
            try:
                self._player.set_media(None)
            except Exception as exc:
                _log_vlc_debug("clear player media", exc)
        old = self._current_media
        self._current_media = None
        self._release_media_object(old)

    def _set_media(self, media) -> None:
        old = self._current_media
        self._current_media = media
        try:
            self._player.set_media(media)
        except Exception:
            self._current_media = old
            self._release_media_object(media)
            raise
        self._release_media_object(old)

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
        self._pending_seek_ms = None
        if self._player is None:
            return
        self._set_paused(True)
        # Intentionally do not set_media(None) here. On Windows that often tears down
        # the embedded Direct3D11 vout and opens a separate "VLC (Direct3D11 output)"
        # window on the next play(). The following _set_media() replaces media in place.

    def _pause_at_stop_time(self):
        stop_at_ms = self._stop_at_ms
        self._timer.stop()
        self._stop_at_ms = -1
        if self._player is None or self._released:
            return
        try:
            if stop_at_ms > 0:
                self._player.set_time(stop_at_ms)
        except Exception as exc:
            _log_vlc_debug("seek to stop time", exc)
        self._set_paused(True)

    def _should_restart_media(self):
        if not self._current_video_path:
            return False
        length_ms = self.get_length()
        current_ms = self.get_time()
        if current_ms < 0:
            return True
        return length_ms > 0 and current_ms >= max(0, length_ms - 250)

    def _restart_from_ms(self, target_ms):
        if (
            self._player is None
            or self._released
            or not self._session_active
            or self._instance is None
            or not self._current_video_path
        ):
            return False
        start_sec = max(0.0, float(target_ms) / 1000.0)
        remote = _is_http_media_url(self._current_video_path)
        try:
            options = _build_vlc_media_options(self._current_video_path, start_sec)
            media = self._instance.media_new(self._current_video_path, *options)
            self.rebind_output_window()
            self._set_media(media)
            self.rebind_output_window()
            result = self._player.play()
        except Exception as exc:
            _log_vlc_warning("prepare media playback", exc)
            return False
        if result == -1:
            return False
        self.rebind_output_window()
        QTimer.singleShot(0, self.rebind_output_window)
        QTimer.singleShot(80, self.rebind_output_window)
        if remote and start_sec > 0.05:
            self._pending_seek_ms = int(start_sec * 1000)
            self._schedule_pending_seek()
        else:
            self._pending_seek_ms = None
        if self._stop_at_ms > 0:
            self._timer.start()
        return True
