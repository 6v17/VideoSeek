"""Previous video keyframe time from an MP4/MOV sample index.

Preview opens with VLC ``:start-time``. On a long GOP that lands between
keyframes, D3D11VA decodes without references and the picture stays broken
until the next keyframe. Starting on the previous sync sample avoids that.

This is not a demuxer. It reads only the boxes needed to name a sync sample
(stts/stss/ctts, or the first sample of a fragment). Anything incomplete,
over the caps, or past the time budget becomes "no index": playback still
opens at the requested time. A file that contains ``moof`` is still marked
fragmented so the player can pick the ffmpeg demuxer.
"""

from __future__ import annotations

import os
import struct
import threading
import time
from typing import Callable

_CACHE: dict[tuple, tuple[float, ...]] = {}
_FRAG: dict[tuple, bool] = {}
_UNREADABLE: set[str] = set()
_INFLIGHT: dict[str, list[Callable[[str], None]]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_LIMIT = 32
# A two-hour 60 fps file is well under these. Larger tables are treated as
# hostile or out of scope and produce no index instead of a long parse.
_MAX_TABLE_ENTRIES = 1_500_000
_MAX_SAMPLE_SPAN = 8_000_000
_MAX_MOOF = 20_000
_MAX_PARSE_SECONDS = 0.35
# ISO/IEC 14496-12 sample_flags bit: sample_is_non_sync_sample.
_SAMPLE_NON_SYNC = 0x00010000


class _ParseLimit(Exception):
    """Raised when a parse exceeds the time budget. Not a corrupt file."""


def _ignored_path(path: str) -> bool:
    text = os.fspath(path or "")
    return (not text) or text.lower().startswith(("http://", "https://"))


def _norm_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(path)))


def _cache_key(path: str):
    stat = os.stat(path)
    return (_norm_path(path), int(stat.st_size), int(stat.st_mtime))


def sync_index_ready(path: str) -> bool:
    """True when this path will not do file IO on the next lookup."""
    if _ignored_path(path):
        return True
    text = os.fspath(path)
    norm = _norm_path(text)
    try:
        key = _cache_key(text)
    except OSError:
        with _CACHE_LOCK:
            return norm in _UNREADABLE
    with _CACHE_LOCK:
        return key in _CACHE


def ensure_sync_index(path: str) -> None:
    """Read the sync index on the caller's thread. Safe to call from a worker."""
    if _ignored_path(path):
        return
    text = os.fspath(path)
    norm = _norm_path(text)
    try:
        key = _cache_key(text)
    except OSError:
        with _CACHE_LOCK:
            _UNREADABLE.add(norm)
        return
    with _CACHE_LOCK:
        _UNREADABLE.discard(norm)
        if key in _CACHE:
            return
    try:
        points, fragmented = _read_sync_points(text)
    except (OSError, struct.error, ValueError, _ParseLimit):
        points, fragmented = [], False
    stored = tuple(points)
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.clear()
            _FRAG.clear()
        _CACHE[key] = stored
        _FRAG[key] = bool(fragmented)


def schedule_sync_index(path: str, on_ready: Callable[[str], None]) -> None:
    """Parse off the caller thread. ``on_ready(path)`` runs on the worker.

    Already-cached paths call ``on_ready`` on the caller thread instead.
    """
    if sync_index_ready(path):
        on_ready(path)
        return
    text = os.fspath(path)
    with _CACHE_LOCK:
        waiters = _INFLIGHT.get(text)
        if waiters is not None:
            waiters.append(on_ready)
            return
        _INFLIGHT[text] = [on_ready]

    def _work() -> None:
        try:
            ensure_sync_index(text)
        finally:
            with _CACHE_LOCK:
                callbacks = _INFLIGHT.pop(text, [])
            for callback in callbacks:
                try:
                    callback(text)
                except Exception:
                    pass

    threading.Thread(target=_work, name="Mp4SyncIndex", daemon=True).start()


def is_fragmented_mp4(path: str, *, load: bool = True) -> bool:
    """True when a ``moof`` was seen. Empty sync lists still count."""
    if _ignored_path(path):
        return False
    flag = _cached_fragmented(path)
    if flag is None and load:
        ensure_sync_index(path)
        flag = _cached_fragmented(path)
    return bool(flag)


def previous_sync_seconds(path: str, target_sec: float, *, load: bool = True) -> float | None:
    """Latest keyframe at or just before ``target_sec``.

    Returns None when the file is not a readable MP4/MOV, the index is over
    the safety caps, or it has no sync sample. Callers then keep the requested
    start time. ``load=False`` never touches the disk.
    """
    if _ignored_path(path):
        return None
    points = _cached_points(path)
    if points is None:
        if not load:
            return None
        ensure_sync_index(path)
        points = _cached_points(path)
    if not points:
        return None
    target = max(0.0, float(target_sec))
    best = points[0]
    for pts in points:
        if pts <= target + 0.001:
            best = pts
        else:
            break
    return best


def _cached_points(path: str) -> tuple[float, ...] | None:
    try:
        key = _cache_key(path)
    except OSError:
        return None
    with _CACHE_LOCK:
        return _CACHE.get(key)


def _cached_fragmented(path: str) -> bool | None:
    try:
        key = _cache_key(path)
    except OSError:
        return None
    with _CACHE_LOCK:
        if key not in _FRAG:
            return None
        return bool(_FRAG[key])


def _read_sync_points(path: str) -> tuple[list[float], bool]:
    deadline = time.monotonic() + _MAX_PARSE_SECONDS
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        file_end = handle.tell()
        try:
            moov = _find_child(handle, 0, file_end, b"moov")
            if moov is None:
                return [], _saw_moof(handle, file_end, deadline)
            moov_start, moov_end = moov
            track = _video_track(handle, moov_start, moov_end, deadline)
            if track is None:
                return [], _saw_moof(handle, file_end, deadline)
            track_id, timescale, points = track
            if points:
                return points, False
            trex = _read_trex_flags(handle, moov_start, moov_end)
            fragment_points, saw_moof = _fragment_sync_points(
                handle,
                file_end,
                track_id,
                timescale,
                trex,
                deadline,
            )
            return fragment_points, saw_moof
        except _ParseLimit:
            return [], _saw_moof(handle, file_end, time.monotonic() + 0.05)


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise _ParseLimit()


def _saw_moof(handle, file_end: int, deadline: float) -> bool:
    """Header-only scan. Seeking past mdat does not read sample bytes."""
    seen = 0
    for typ, _start, _end in _iter_atoms(handle, 0, file_end):
        if seen == 0 or seen % 64 == 0:
            _check_deadline(deadline)
        seen += 1
        if typ == b"moof":
            return True
        if seen >= _MAX_MOOF:
            return False
    return False


def _video_track(handle, moov_start: int, moov_end: int, deadline: float):
    for typ, trak_start, trak_end in _iter_atoms(handle, moov_start, moov_end):
        if typ != b"trak":
            continue
        _check_deadline(deadline)
        points = _video_track_points(handle, trak_start, trak_end, deadline)
        if points is None:
            continue
        track_id = _track_id(handle, trak_start, trak_end)
        timescale = _track_timescale(handle, trak_start, trak_end)
        if points:
            return track_id or 0, timescale or 1, points
        if track_id is None or timescale <= 0:
            continue
        return track_id, timescale, points
    return None


def _track_id(handle, trak_start: int, trak_end: int) -> int | None:
    tkhd = _find_child(handle, trak_start, trak_end, b"tkhd")
    if tkhd is None or tkhd[1] - tkhd[0] < 16:
        return None
    handle.seek(tkhd[0])
    version = handle.read(1)[0]
    offset = 20 if version == 1 else 12
    if tkhd[1] - tkhd[0] < offset + 4:
        return None
    handle.seek(tkhd[0] + offset)
    return struct.unpack(">I", handle.read(4))[0]


def _track_timescale(handle, trak_start: int, trak_end: int) -> int:
    mdia = _find_child(handle, trak_start, trak_end, b"mdia")
    if mdia is None:
        return 0
    mdhd = _find_child(handle, mdia[0], mdia[1], b"mdhd")
    if mdhd is None:
        return 0
    return _timescale(handle, mdhd[0], mdhd[1])


def _read_trex_flags(handle, moov_start: int, moov_end: int) -> dict[int, int]:
    """``trex`` default_sample_flags keyed by track id. Missing box → empty."""
    mvex = _find_child(handle, moov_start, moov_end, b"mvex")
    if mvex is None:
        return {}
    found: dict[int, int] = {}
    for typ, start, end in _iter_atoms(handle, mvex[0], mvex[1]):
        if typ != b"trex" or end - start < 24:
            continue
        handle.seek(start + 4)
        raw = handle.read(20)
        if len(raw) < 20:
            continue
        track_id, _desc, _dur, _size, sample_flags = struct.unpack(">IIIII", raw)
        found[int(track_id)] = int(sample_flags)
    return found


def _fragment_sync_points(
    handle,
    file_end: int,
    track_id: int,
    timescale: int,
    trex_flags: dict[int, int],
    deadline: float,
) -> tuple[list[float], bool]:
    """Sync time of each video fragment's first sample, plus whether any moof exists.

    Only the first ``trun`` is timed, from ``tfdt``. Later truns need a duration
    sum this preview helper does not keep. Unknown flags yield no timestamp;
    the moof still marks the file fragmented.
    """
    points: list[float] = []
    saw_moof = False
    moof_count = 0
    for typ, start, end in _iter_atoms(handle, 0, file_end):
        if typ != b"moof":
            continue
        moof_count += 1
        if moof_count == 1 or moof_count % 32 == 0:
            _check_deadline(deadline)
        if moof_count > _MAX_MOOF:
            break
        saw_moof = True
        for child, child_start, child_end in _iter_atoms(handle, start, end):
            if child != b"traf":
                continue
            pts = _traf_sync_seconds(
                handle,
                child_start,
                child_end,
                track_id,
                timescale,
                trex_flags.get(track_id),
            )
            if pts is not None:
                points.append(pts)
    points.sort()
    return points, saw_moof


def _traf_sync_seconds(
    handle,
    start: int,
    end: int,
    track_id: int,
    timescale: int,
    trex_default_flags: int | None,
) -> float | None:
    tfhd = _find_child(handle, start, end, b"tfhd")
    tfdt = _find_child(handle, start, end, b"tfdt")
    trun = _find_child(handle, start, end, b"trun")
    if tfhd is None or tfdt is None or trun is None:
        return None
    parsed = _parse_tfhd(handle, tfhd[0], tfhd[1])
    if parsed is None or parsed[0] != track_id:
        return None
    # tfhd default_sample_flags overrides trex; absence falls through.
    default_flags = parsed[1] if parsed[1] is not None else trex_default_flags
    sample_flags = _trun_first_sample_flags(handle, trun[0], trun[1], default_flags)
    if sample_flags is None or (int(sample_flags) & _SAMPLE_NON_SYNC) != 0:
        return None
    base = _tfdt_base(handle, tfdt[0], tfdt[1])
    if base is None or timescale <= 0:
        return None
    return max(0.0, base / float(timescale))


def _parse_tfhd(handle, start: int, end: int):
    if end - start < 8:
        return None
    handle.seek(start)
    flags = struct.unpack(">I", handle.read(4))[0] & 0xFFFFFF
    track_id = struct.unpack(">I", handle.read(4))[0]
    default_flags = None
    if flags & 0x000001:
        handle.read(8)
    if flags & 0x000002:
        handle.read(4)
    if flags & 0x000008:
        handle.read(4)
    if flags & 0x000010:
        handle.read(4)
    if flags & 0x000020:
        if end - handle.tell() < 4:
            return None
        default_flags = struct.unpack(">I", handle.read(4))[0]
    return track_id, default_flags


def _tfdt_base(handle, start: int, end: int) -> int | None:
    if end - start < 8:
        return None
    handle.seek(start)
    version = handle.read(1)[0]
    handle.seek(start + 4)
    if version == 1:
        if end - start < 12:
            return None
        return struct.unpack(">Q", handle.read(8))[0]
    return struct.unpack(">I", handle.read(4))[0]


def _trun_first_sample_flags(handle, start: int, end: int, default_flags: int | None) -> int | None:
    """Flags for trun sample 0.

    Priority (ISO/IEC 14496-12): ``first_sample_flags``, else the first
    per-sample flags, else tfhd/trex defaults. ``None`` means unknown.
    """
    if end - start < 8:
        return None
    handle.seek(start)
    header = handle.read(8)
    if len(header) < 8:
        return None
    flags, sample_count = struct.unpack(">II", header)
    flags &= 0xFFFFFF
    if sample_count <= 0:
        return None
    pos = start + 8
    if flags & 0x000001:  # data-offset-present
        pos += 4
    if flags & 0x000004:  # first-sample-flags-present
        if end - pos < 4:
            return None
        handle.seek(pos)
        raw = handle.read(4)
        if len(raw) < 4:
            return None
        return struct.unpack(">I", raw)[0]
    if flags & 0x000400:  # sample-flags-present
        offset = 0
        if flags & 0x000100:  # sample-duration-present
            offset += 4
        if flags & 0x000200:  # sample-size-present
            offset += 4
        if end - (pos + offset) < 4:
            return None
        handle.seek(pos + offset)
        raw = handle.read(4)
        if len(raw) < 4:
            return None
        return struct.unpack(">I", raw)[0]
    return default_flags


def _video_track_points(handle, trak_start: int, trak_end: int, deadline: float) -> list[float] | None:
    """Sync times from ``stss``. None means this trak is not video."""
    mdia = _find_child(handle, trak_start, trak_end, b"mdia")
    if mdia is None:
        return None
    mdia_start, mdia_end = mdia
    hdlr = _find_child(handle, mdia_start, mdia_end, b"hdlr")
    if hdlr is None or not _is_video_handler(handle, hdlr[0], hdlr[1]):
        return None
    mdhd = _find_child(handle, mdia_start, mdia_end, b"mdhd")
    if mdhd is None:
        return None
    timescale = _timescale(handle, mdhd[0], mdhd[1])
    if timescale <= 0:
        return None
    minf = _find_child(handle, mdia_start, mdia_end, b"minf")
    if minf is None:
        return []
    stbl = _find_child(handle, minf[0], minf[1], b"stbl")
    if stbl is None:
        return []
    stts = _find_child(handle, stbl[0], stbl[1], b"stts")
    stss = _find_child(handle, stbl[0], stbl[1], b"stss")
    if stts is None or stss is None:
        return []
    deltas = _read_pairs(handle, stts[0], stts[1], deadline=deadline)
    sync_samples = _read_samples(handle, stss[0], stss[1], deadline=deadline)
    if not deltas or not sync_samples:
        return []
    ctts_box = _find_child(handle, stbl[0], stbl[1], b"ctts")
    offsets = (
        _read_pairs(handle, ctts_box[0], ctts_box[1], signed=True, deadline=deadline)
        if ctts_box
        else []
    )
    return _keyframe_seconds(deltas, sync_samples, offsets, timescale)


def _is_video_handler(handle, start: int, end: int) -> bool:
    # version/flags (4) + pre_defined (4) + handler_type (4)
    if end - start < 12:
        return False
    handle.seek(start + 8)
    return handle.read(4) == b"vide"


def _timescale(handle, start: int, end: int) -> int:
    if end - start < 16:
        return 0
    handle.seek(start)
    version = handle.read(1)[0]
    if version == 0:
        handle.seek(start + 12)
    else:
        if end - start < 24:
            return 0
        handle.seek(start + 20)
    return struct.unpack(">I", handle.read(4))[0]


def _read_pairs(
    handle,
    start: int,
    end: int,
    *,
    signed: bool = False,
    deadline: float | None = None,
) -> list[tuple[int, int]]:
    if end - start < 8:
        return []
    handle.seek(start + 4)
    count = struct.unpack(">I", handle.read(4))[0]
    if count <= 0 or count > _MAX_TABLE_ENTRIES:
        return []
    need = 8 + count * 8
    if end - start < need:
        return []
    fmt = ">i" if signed else ">I"
    pairs = []
    for index in range(count):
        if deadline is not None and index % 4096 == 0:
            _check_deadline(deadline)
        sample_count = struct.unpack(">I", handle.read(4))[0]
        value = struct.unpack(fmt, handle.read(4))[0]
        pairs.append((sample_count, value))
    return pairs


def _read_samples(handle, start: int, end: int, *, deadline: float | None = None) -> list[int]:
    if end - start < 8:
        return []
    handle.seek(start + 4)
    count = struct.unpack(">I", handle.read(4))[0]
    if count <= 0 or count > _MAX_TABLE_ENTRIES or end - start < 8 + count * 4:
        return []
    samples = []
    for index in range(count):
        if deadline is not None and index % 4096 == 0:
            _check_deadline(deadline)
        samples.append(struct.unpack(">I", handle.read(4))[0])
    return samples


def _keyframe_seconds(deltas, sync_samples, offsets, timescale: int) -> list[float]:
    """Map sync sample numbers to seconds in one pass over each table."""
    if timescale <= 0:
        return []
    wanted = sorted({int(sample) for sample in sync_samples if 0 < int(sample) <= _MAX_SAMPLE_SPAN})
    if not wanted or len(wanted) > _MAX_TABLE_ENTRIES:
        return []
    offset_at = _offsets_for_samples(offsets, wanted)
    if offset_at is None:
        return []
    points: list[float] = []
    dts = 0
    index = 1
    cursor = 0
    count_wanted = len(wanted)
    for raw_count, delta in deltas:
        count = max(0, int(raw_count))
        if count > _MAX_SAMPLE_SPAN:
            return []
        end = index + count
        if end > _MAX_SAMPLE_SPAN:
            return []
        delta = int(delta)
        while cursor < count_wanted and wanted[cursor] < index:
            cursor += 1
        while cursor < count_wanted and wanted[cursor] < end:
            sample = wanted[cursor]
            ticks = dts + (sample - index) * delta + offset_at.get(sample, 0)
            points.append(max(0.0, ticks / float(timescale)))
            cursor += 1
        dts += count * delta
        index = end
        if cursor >= count_wanted:
            break
    points.sort()
    return points


def _offsets_for_samples(offsets, wanted: list[int]) -> dict[int, int] | None:
    found: dict[int, int] = {}
    if not offsets:
        return found
    cursor = 0
    index = 1
    count_wanted = len(wanted)
    for raw_count, value in offsets:
        count = max(0, int(raw_count))
        if count > _MAX_SAMPLE_SPAN:
            return None
        end = index + count
        if end > _MAX_SAMPLE_SPAN:
            return None
        while cursor < count_wanted and wanted[cursor] < index:
            cursor += 1
        while cursor < count_wanted and wanted[cursor] < end:
            found[wanted[cursor]] = int(value)
            cursor += 1
        index = end
        if cursor >= count_wanted:
            break
    return found


def _find_child(handle, start: int, end: int, name: bytes):
    for typ, payload_start, payload_end in _iter_atoms(handle, start, end):
        if typ == name:
            return payload_start, payload_end
    return None


def _iter_atoms(handle, start: int, end: int):
    pos = int(start)
    end = int(end)
    while pos + 8 <= end:
        handle.seek(pos)
        header = handle.read(8)
        if len(header) < 8:
            return
        size, typ = struct.unpack(">I4s", header)
        header_len = 8
        if size == 1:
            extra = handle.read(8)
            if len(extra) < 8:
                return
            size = struct.unpack(">Q", extra)[0]
            header_len = 16
        elif size == 0:
            size = end - pos
        if size < header_len:
            return
        atom_end = pos + size
        if atom_end > end or atom_end <= pos:
            return
        yield typ, pos + header_len, atom_end
        pos = atom_end
