"""Previous video keyframe time from an MP4/MOV sample index.

Preview opens with VLC ``:start-time``. On a long GOP that lands between
keyframes, D3D11VA decodes without references and the picture stays broken
until the next keyframe. Starting on the previous sync sample avoids that.
"""

from __future__ import annotations

import os
import struct

_CACHE: dict[tuple, tuple[float, ...]] = {}
_FRAG: dict[tuple, bool] = {}
_CACHE_LIMIT = 32


def is_fragmented_mp4(path: str) -> bool:
    """True when sync samples live in moof fragments, not in moov."""
    text = os.fspath(path or "")
    if not text or text.lower().startswith(("http://", "https://")):
        return False
    try:
        stat = os.stat(text)
    except OSError:
        return False
    key = (os.path.normcase(os.path.normpath(text)), int(stat.st_size), int(stat.st_mtime))
    _sync_points(text)
    return bool(_FRAG.get(key, False))


def _remember_fragmented(path: str, fragmented: bool) -> None:
    try:
        stat = os.stat(path)
    except OSError:
        return
    key = (os.path.normcase(os.path.normpath(path)), int(stat.st_size), int(stat.st_mtime))
    _FRAG[key] = bool(fragmented)
    if len(_FRAG) > _CACHE_LIMIT:
        _FRAG.clear()
        _FRAG[key] = bool(fragmented)


def previous_sync_seconds(path: str, target_sec: float) -> float | None:
    """Latest keyframe at or just before ``target_sec``.

    Returns None when the file is not a readable MP4/MOV, or it has no sync
    sample index. Callers then keep the requested start time.
    """
    points = _sync_points(path)
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


def _sync_points(path: str) -> tuple[float, ...] | None:
    text = os.fspath(path or "")
    if not text or text.lower().startswith(("http://", "https://")):
        return None
    try:
        stat = os.stat(text)
    except OSError:
        return None
    key = (os.path.normcase(os.path.normpath(text)), int(stat.st_size), int(stat.st_mtime))
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    try:
        points = tuple(_read_sync_points(text))
    except (OSError, struct.error, ValueError):
        return None
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.clear()
    _CACHE[key] = points
    return points


def _read_sync_points(path: str) -> list[float]:
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        file_end = handle.tell()
        moov = _find_child(handle, 0, file_end, b"moov")
        if moov is None:
            return []
        moov_start, moov_end = moov
        track = _video_track(handle, moov_start, moov_end)
        if track is None:
            return []
        track_id, timescale, points = track
        if points:
            _remember_fragmented(path, False)
            return points
        # Fragmented MP4 keeps one sync sample at the start of each video moof.
        fragment_points = _fragment_sync_points(handle, file_end, track_id, timescale)
        _remember_fragmented(path, bool(fragment_points))
        return fragment_points


def _video_track(handle, moov_start: int, moov_end: int):
    for typ, trak_start, trak_end in _iter_atoms(handle, moov_start, moov_end):
        if typ != b"trak":
            continue
        points = _video_track_points(handle, trak_start, trak_end)
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


def _fragment_sync_points(handle, file_end: int, track_id: int, timescale: int) -> list[float]:
    points: list[float] = []
    for typ, start, end in _iter_atoms(handle, 0, file_end):
        if typ != b"moof":
            continue
        for child, child_start, child_end in _iter_atoms(handle, start, end):
            if child != b"traf":
                continue
            pts = _traf_sync_seconds(handle, child_start, child_end, track_id, timescale)
            if pts is not None:
                points.append(pts)
    points.sort()
    return points


def _traf_sync_seconds(handle, start: int, end: int, track_id: int, timescale: int) -> float | None:
    tfhd = _find_child(handle, start, end, b"tfhd")
    tfdt = _find_child(handle, start, end, b"tfdt")
    trun = _find_child(handle, start, end, b"trun")
    if tfhd is None or tfdt is None or trun is None:
        return None
    parsed = _parse_tfhd(handle, tfhd[0], tfhd[1])
    if parsed is None or parsed[0] != track_id:
        return None
    default_flags = parsed[1]
    if not _trun_starts_on_sync(handle, trun[0], trun[1], default_flags):
        return None
    base = _tfdt_base(handle, tfdt[0], tfdt[1])
    if base is None:
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


def _trun_starts_on_sync(handle, start: int, end: int, default_flags: int | None) -> bool:
    if end - start < 8:
        return False
    handle.seek(start)
    flags = struct.unpack(">I", handle.read(4))[0] & 0xFFFFFF
    handle.read(4)  # sample_count
    if flags & 0x000001:
        handle.read(4)
    sample_flags = default_flags
    if flags & 0x000004:
        if end - handle.tell() < 4:
            return False
        sample_flags = struct.unpack(">I", handle.read(4))[0]
    if sample_flags is None:
        return False
    # Bit 16 set means this sample is not a sync sample.
    return (int(sample_flags) & 0x00010000) == 0


def _video_track_points(handle, trak_start: int, trak_end: int) -> list[float] | None:
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
    deltas = _read_pairs(handle, stts[0], stts[1])
    sync_samples = _read_samples(handle, stss[0], stss[1])
    if not deltas or not sync_samples:
        return []
    ctts_box = _find_child(handle, stbl[0], stbl[1], b"ctts")
    offsets = _read_pairs(handle, ctts_box[0], ctts_box[1], signed=True) if ctts_box else []
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


def _read_pairs(handle, start: int, end: int, *, signed: bool = False) -> list[tuple[int, int]]:
    if end - start < 8:
        return []
    handle.seek(start + 4)
    count = struct.unpack(">I", handle.read(4))[0]
    need = 8 + count * 8
    if count <= 0 or end - start < need:
        return []
    fmt = ">i" if signed else ">I"
    pairs = []
    for _ in range(count):
        sample_count = struct.unpack(">I", handle.read(4))[0]
        value = struct.unpack(fmt, handle.read(4))[0]
        pairs.append((sample_count, value))
    return pairs


def _read_samples(handle, start: int, end: int) -> list[int]:
    if end - start < 8:
        return []
    handle.seek(start + 4)
    count = struct.unpack(">I", handle.read(4))[0]
    if count <= 0 or end - start < 8 + count * 4:
        return []
    return [struct.unpack(">I", handle.read(4))[0] for _ in range(count)]


def _keyframe_seconds(deltas, sync_samples, offsets, timescale: int) -> list[float]:
    wanted = {int(sample) for sample in sync_samples if int(sample) > 0}
    if not wanted:
        return []
    last = max(wanted)
    offset_at: dict[int, int] = {}
    if offsets:
        index = 1
        for count, value in offsets:
            end = index + max(0, int(count))
            if end > index:
                for sample in wanted:
                    if index <= sample < end:
                        offset_at[sample] = int(value)
            index = end
            if index > last:
                break
    points: list[float] = []
    dts = 0
    index = 1
    pending = set(wanted)
    for count, delta in deltas:
        count = max(0, int(count))
        delta = int(delta)
        end = index + count
        hit = [sample for sample in pending if index <= sample < end]
        for sample in sorted(hit):
            ticks = dts + (sample - index) * delta + offset_at.get(sample, 0)
            points.append(max(0.0, ticks / float(timescale)))
            pending.discard(sample)
        dts += count * delta
        index = end
        if not pending:
            break
    points.sort()
    return points


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
