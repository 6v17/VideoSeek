import os
import struct
import tempfile
import threading
import time
import unittest

os.environ.setdefault("VIDEOSEEK_TEST_MODE", "1")


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + typ + payload


def _write_sync_mp4(path: str) -> None:
    """10 one-second samples, keyframes at 0s and 8s, plus an audio track."""
    mdhd = _box(b"mdhd", struct.pack(">IIIIIHH", 0, 0, 0, 1000, 10000, 0x55C4, 0))
    hdlr = _box(
        b"hdlr",
        struct.pack(">II4s", 0, 0, b"vide") + b"\x00" * 12 + b"Video\x00",
    )
    stts = _box(b"stts", struct.pack(">IIII", 0, 1, 10, 1000))
    stss = _box(b"stss", struct.pack(">III", 0, 2, 1) + struct.pack(">I", 9))
    stbl = _box(b"stbl", stts + stss)
    minf = _box(b"minf", stbl)
    mdia = _box(b"mdia", mdhd + hdlr + minf)
    video = _box(b"trak", mdia)

    audio_hdlr = _box(
        b"hdlr",
        struct.pack(">II4s", 0, 0, b"soun") + b"\x00" * 12 + b"Audio\x00",
    )
    audio = _box(b"trak", _box(b"mdia", audio_hdlr))
    moov = _box(b"moov", audio + video)
    ftyp = _box(b"ftyp", b"isom" + b"\x00\x00\x00\x00" + b"isom")
    with open(path, "wb") as handle:
        handle.write(ftyp + moov)


class Mp4SyncTests(unittest.TestCase):
    def test_previous_sync_uses_the_sample_index(self):
        from src.media.mp4_sync import previous_sync_seconds

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "clip.mp4")
        _write_sync_mp4(path)
        self.addCleanup(lambda: os.remove(path))

        self.assertEqual(previous_sync_seconds(path, 12.0), 8.0)
        self.assertEqual(previous_sync_seconds(path, 8.0), 8.0)
        self.assertEqual(previous_sync_seconds(path, 3.0), 0.0)
        self.assertIsNone(previous_sync_seconds(path + ".missing", 1.0))

    def test_real_long_gop_snaps_before_the_broken_span(self):
        from src.media.mp4_sync import previous_sync_seconds

        path = r"E:\素材\网络素材\13384448_1920_1080_30fps.mp4"
        if not os.path.isfile(path):
            self.skipTest("sample file is not on this machine")
        sync = previous_sync_seconds(path, 12.0)
        self.assertIsNotNone(sync)
        self.assertAlmostEqual(sync, 8.341667, places=3)
        self.assertAlmostEqual(previous_sync_seconds(path, 8.341667), 8.341667, places=3)
        from src.media.mp4_sync import is_fragmented_mp4

        self.assertTrue(is_fragmented_mp4(path))

    def test_lookup_without_load_does_not_parse(self):
        from src.media.mp4_sync import ensure_sync_index, is_fragmented_mp4, previous_sync_seconds

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "clip.mp4")
        _write_sync_mp4(path)
        self.addCleanup(lambda: os.remove(path))

        self.assertIsNone(previous_sync_seconds(path, 12.0, load=False))
        self.assertFalse(is_fragmented_mp4(path, load=False))
        ensure_sync_index(path)
        self.assertEqual(previous_sync_seconds(path, 12.0, load=False), 8.0)

    def test_schedule_parses_off_the_caller_thread(self):
        from src.media.mp4_sync import previous_sync_seconds, schedule_sync_index

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "clip.mp4")
        _write_sync_mp4(path)
        self.addCleanup(lambda: os.remove(path))
        done = threading.Event()
        caller = threading.get_ident()
        seen = {}

        def _ready(ready_path):
            seen["path"] = ready_path
            seen["same_thread"] = threading.get_ident() == caller
            done.set()

        schedule_sync_index(path, _ready)
        self.assertTrue(done.wait(2.0))
        self.assertEqual(seen["path"], path)
        self.assertFalse(seen["same_thread"])
        self.assertEqual(previous_sync_seconds(path, 12.0, load=False), 8.0)

    def test_composition_offsets_move_the_sync_time(self):
        from src.media.mp4_sync import _keyframe_seconds

        deltas = [(1, 1000)] * 4
        offsets = [(1, 0), (1, 1000), (1, -1000), (1, 0)]
        self.assertEqual(_keyframe_seconds(deltas, [1, 3], offsets, 1000), [0.0, 1.0])

    def test_per_sample_table_stays_fast(self):
        from src.media.mp4_sync import _keyframe_seconds

        count = 80_000
        deltas = [(1, 1000)] * count
        keyframes = list(range(1, count + 1, 50))
        started = time.perf_counter()
        points = _keyframe_seconds(deltas, keyframes, [], 1000)
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertEqual(len(points), len(keyframes))
        self.assertEqual(points[0], 0.0)
        self.assertEqual(points[1], 50.0)

    def test_oversized_sample_table_is_rejected(self):
        from io import BytesIO

        from src.media.mp4_sync import _MAX_TABLE_ENTRIES, _read_pairs

        count = _MAX_TABLE_ENTRIES + 1
        handle = BytesIO(struct.pack(">II", 0, count))
        started = time.perf_counter()
        self.assertEqual(_read_pairs(handle, 0, 8 + count * 8), [])
        self.assertLess(time.perf_counter() - started, 0.2)

    def test_fragment_flags_follow_trex_then_trun(self):
        from src.media.mp4_sync import is_fragmented_mp4, previous_sync_seconds

        folder = tempfile.mkdtemp()
        inherited = os.path.join(folder, "inherited.mp4")
        overridden = os.path.join(folder, "overridden.mp4")
        restored = os.path.join(folder, "restored.mp4")
        tfhd_blocks = os.path.join(folder, "tfhd.mp4")
        for path in (inherited, overridden, restored, tfhd_blocks):
            self.addCleanup(lambda path=path: os.remove(path) if os.path.exists(path) else None)

        _write_fragment_mp4(inherited, trex_flags=0, trun=_trun_plain())
        self.assertTrue(is_fragmented_mp4(inherited))
        self.assertEqual(previous_sync_seconds(inherited, 5.0), 5.0)

        _write_fragment_mp4(
            overridden,
            trex_flags=0,
            trun=_trun_sample_flags(0x00010000),
        )
        self.assertTrue(is_fragmented_mp4(overridden))
        self.assertIsNone(previous_sync_seconds(overridden, 9.0))

        _write_fragment_mp4(
            restored,
            trex_flags=0x00010000,
            trun=_trun_first_flags(0),
        )
        self.assertEqual(previous_sync_seconds(restored, 5.0), 5.0)

        _write_fragment_mp4(
            tfhd_blocks,
            trex_flags=0,
            trun=_trun_plain(),
            tfhd_default_flags=0x00010000,
        )
        self.assertTrue(is_fragmented_mp4(tfhd_blocks))
        self.assertIsNone(previous_sync_seconds(tfhd_blocks, 9.0))


def _write_gop_mp4(path: str, samples: int, keyframes: list[int]) -> None:
    mdhd = _box(b"mdhd", struct.pack(">IIIIIHH", 0, 0, 0, 1000, samples * 1000, 0x55C4, 0))
    hdlr = _box(b"hdlr", struct.pack(">II4s", 0, 0, b"vide") + b"\x00" * 12 + b"Video\x00")
    stts = _box(b"stts", struct.pack(">IIII", 0, 1, samples, 1000))
    stss = _box(
        b"stss",
        struct.pack(">II", 0, len(keyframes)) + b"".join(struct.pack(">I", sample) for sample in keyframes),
    )
    trak = _box(b"trak", _box(b"mdia", mdhd + hdlr + _box(b"minf", _box(b"stbl", stts + stss))))
    with open(path, "wb") as handle:
        handle.write(_box(b"ftyp", b"isom" + b"\x00" * 4 + b"isom") + _box(b"moov", trak))


def _video_moov(trex_flags: int) -> bytes:
    tkhd = _box(b"tkhd", struct.pack(">IIII", 0, 0, 0, 1))
    mdhd = _box(b"mdhd", struct.pack(">IIIIIHH", 0, 0, 0, 1000, 10000, 0x55C4, 0))
    hdlr = _box(b"hdlr", struct.pack(">II4s", 0, 0, b"vide") + b"\x00" * 12 + b"Video\x00")
    trex = _box(b"trex", struct.pack(">IIIIII", 0, 1, 1, 0, 0, trex_flags))
    trak = _box(b"trak", tkhd + _box(b"mdia", mdhd + hdlr))
    return _box(b"moov", trak + _box(b"mvex", trex))


def _trun_plain() -> bytes:
    return _box(b"trun", struct.pack(">II", 0, 1))


def _trun_first_flags(sample_flags: int) -> bytes:
    return _box(b"trun", struct.pack(">III", 0x4, 1, sample_flags))


def _trun_sample_flags(sample_flags: int) -> bytes:
    return _box(b"trun", struct.pack(">III", 0x400, 1, sample_flags))


def _write_fragment_mp4(
    path: str,
    *,
    trex_flags: int,
    trun: bytes,
    tfhd_default_flags: int | None = None,
    base: int = 5000,
) -> None:
    if tfhd_default_flags is None:
        tfhd = _box(b"tfhd", struct.pack(">II", 0, 1))
    else:
        tfhd = _box(b"tfhd", struct.pack(">III", 0x20, 1, tfhd_default_flags))
    tfdt = _box(b"tfdt", struct.pack(">II", 0, base))
    moof = _box(b"moof", _box(b"traf", tfhd + tfdt + trun))
    with open(path, "wb") as handle:
        handle.write(_box(b"ftyp", b"isom" + b"\x00" * 4 + b"isom") + _video_moov(trex_flags) + moof)
