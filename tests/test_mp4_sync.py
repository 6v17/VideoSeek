import os
import struct
import tempfile
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
