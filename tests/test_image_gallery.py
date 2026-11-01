"""Image gallery diff, ranking, and Lance round-trip without a real CLIP model."""

from __future__ import annotations

import os
import tempfile
import unittest

import numpy as np

from src.media.formats import IMAGE_EXTS, is_supported_image_path
from src.services.image_gallery_index import (
    CatalogRecord,
    ScannedImage,
    diff_image_catalog,
    plan_image_sync,
    rank_image_vectors,
)
from src.core.image_io import extended_length_path, from_extended_length_path
from src.services.image_gallery_service import (
    _is_reparse_point,
    add_image_folder,
    ImageGalleryStopped,
    discover_image_gallery,
    gallery_status,
    scan_image_folders,
    search_image_gallery,
    sync_image_gallery,
)
from src.storage.image_gallery_store import search_image_vectors, upsert_image_vectors


def _record(path, folder, *, mtime_ns=10, size=5, profile_id="model-a", failed=False, pending=False):
    return CatalogRecord(
        path=path,
        folder=folder,
        mtime_ns=mtime_ns,
        size=size,
        profile_id=profile_id,
        failed=failed,
        pending=pending,
    )


def _stat(path, folder, *, mtime_ns=10, size=5):
    return ScannedImage(path=path, folder=folder, mtime_ns=mtime_ns, size=size)


class ImageGalleryDiffTests(unittest.TestCase):
    def test_new_file_is_embedded(self):
        folder = "d:/photos"
        scanned = {"d:/photos/a.jpg": _stat("d:/photos/a.jpg", folder)}
        diff = diff_image_catalog({}, scanned, active_profile_id="model-a", online_folders={folder})
        self.assertEqual([item.path for item in diff.to_embed], ["d:/photos/a.jpg"])
        self.assertEqual(diff.to_delete, ())

    def test_mtime_change_is_embedded_again(self):
        folder = "d:/photos"
        path = "d:/photos/a.jpg"
        records = {path: _record(path, folder, mtime_ns=10)}
        scanned = {path: _stat(path, folder, mtime_ns=20)}
        diff = diff_image_catalog(records, scanned, active_profile_id="model-a", online_folders={folder})
        self.assertEqual([item.path for item in diff.to_embed], [path])

    def test_unchanged_and_failed_files_are_left_alone(self):
        folder = "d:/photos"
        good = "d:/photos/a.jpg"
        bad = "d:/photos/b.jpg"
        records = {
            good: _record(good, folder),
            bad: _record(bad, folder, failed=True),
        }
        scanned = {
            good: _stat(good, folder),
            bad: _stat(bad, folder),
        }
        diff = diff_image_catalog(records, scanned, active_profile_id="model-a", online_folders={folder})
        self.assertEqual(diff.to_embed, ())
        self.assertEqual(diff.unchanged, (good, bad))

    def test_missing_file_in_online_folder_is_deleted(self):
        folder = "d:/photos"
        path = "d:/photos/a.jpg"
        records = {path: _record(path, folder)}
        diff = diff_image_catalog(records, {}, active_profile_id="model-a", online_folders={folder})
        self.assertEqual(diff.to_delete, (path,))

    def test_offline_folder_is_not_wiped(self):
        folder = "d:/photos"
        path = "d:/photos/a.jpg"
        records = {path: _record(path, folder)}
        diff = diff_image_catalog(records, {}, active_profile_id="model-a", online_folders=set())
        self.assertEqual(diff.to_delete, ())
        self.assertEqual(diff.to_embed, ())

    def test_profile_change_reembeds_and_drops_offline_rows(self):
        online = "d:/photos"
        offline = "e:/archive"
        live = "d:/photos/a.jpg"
        gone = "e:/archive/b.jpg"
        records = {
            live: _record(live, online, profile_id="model-a"),
            gone: _record(gone, offline, profile_id="model-a"),
        }
        scanned = {live: _stat(live, online)}
        plan = plan_image_sync(
            records,
            scanned,
            active_profile_id="model-b",
            online_folders={online},
        )
        self.assertTrue(plan.rebuild)
        self.assertEqual([item.path for item in plan.to_embed], [live])
        self.assertIn(gone, plan.to_delete)

    def test_pending_rows_do_not_force_a_rebuild(self):
        folder = "d:/photos"
        path = "d:/photos/a.jpg"
        records = {path: _record(path, folder, profile_id="", pending=True)}
        scanned = {path: _stat(path, folder)}
        plan = plan_image_sync(
            records,
            scanned,
            active_profile_id="model-a",
            online_folders={folder},
        )
        self.assertFalse(plan.rebuild)
        self.assertEqual([item.path for item in plan.to_embed], [path])


class ImageGalleryRankTests(unittest.TestCase):
    def test_rank_prefers_the_aligned_vector(self):
        query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        items = [
            ("far", np.array([0.0, 1.0, 0.0], dtype=np.float32)),
            ("near", np.array([0.9, 0.1, 0.0], dtype=np.float32)),
            ("mid", np.array([0.5, 0.5, 0.0], dtype=np.float32)),
        ]
        ranked = rank_image_vectors(query, items, top_k=2)
        self.assertEqual([item[0] for item in ranked], ["near", "mid"])
        self.assertGreater(ranked[0][1], ranked[1][1])

    def test_rank_skips_a_different_dimension(self):
        query = np.array([1.0, 0.0], dtype=np.float32)
        ranked = rank_image_vectors(
            query,
            [("bad", np.array([1.0, 0.0, 0.0], dtype=np.float32)), ("ok", np.array([0.2, 0.8], dtype=np.float32))],
            top_k=5,
        )
        self.assertEqual([item[0] for item in ranked], ["ok"])


class ImageGalleryScanTests(unittest.TestCase):
    def test_supported_suffixes(self):
        self.assertIn(".jpg", IMAGE_EXTS)
        self.assertIn(".heic", IMAGE_EXTS)
        self.assertTrue(is_supported_image_path("shot.JPEG"))
        self.assertFalse(is_supported_image_path("clip.mp4"))

    def test_scan_keeps_images_and_skips_other_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "photos")
            os.makedirs(folder)
            image_path = os.path.join(folder, "a.jpg")
            with open(image_path, "wb") as handle:
                handle.write(b"jpeg")
            with open(os.path.join(folder, "notes.txt"), "wb") as handle:
                handle.write(b"text")
            scanned, online = scan_image_folders([folder])
            self.assertEqual(len(online), 1)
            self.assertEqual(len(scanned), 1)
            only = next(iter(scanned.values()))
            self.assertTrue(only.path.lower().endswith("a.jpg"))
            self.assertEqual(only.size, 4)

    def test_scan_enters_nested_folders_and_skips_system_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "photos")
            nested = os.path.join(folder, "year", "trip")
            os.makedirs(nested)
            self._write(os.path.join(folder, "flat.jpg"))
            self._write(os.path.join(nested, "deep.jpg"))
            for skipped in ("Windows", "$RECYCLE.BIN", "node_modules", "AppData"):
                skipped_dir = os.path.join(folder, skipped)
                os.makedirs(skipped_dir)
                self._write(os.path.join(skipped_dir, "hidden.jpg"))
            try:
                os.symlink(nested, os.path.join(folder, "alias"), target_is_directory=True)
            except (OSError, NotImplementedError):
                pass
            if os.name == "nt":
                long_dir = os.path.join(folder, "nest", "x" * 180, "y" * 80)
                os.makedirs(extended_length_path(long_dir))
                with open(extended_length_path(os.path.join(long_dir, "long.jpg")), "wb") as handle:
                    handle.write(b"jpeg")
            counts = []
            scanned, online = scan_image_folders([folder], progress_callback=counts.append)
            self.assertEqual(len(online), 1)
            names = {os.path.basename(path) for path in scanned}
            self.assertIn("flat.jpg", names)
            self.assertIn("deep.jpg", names)
            self.assertNotIn("hidden.jpg", names)
            if os.name == "nt":
                self.assertIn("long.jpg", names)
            lowered = [path.replace("\\", "/").lower() for path in scanned]
            self.assertFalse(any("/alias/" in path for path in lowered))
            self.assertTrue(counts)
            self.assertEqual(counts[-1], len(scanned))
            owner = next(iter(scanned.values())).folder
            self.assertEqual(owner, next(iter(online)))

    def test_reparse_point_is_detected_without_following_it(self):
        class _Stat:
            st_file_attributes = 0x400

        class _Entry:
            def is_symlink(self):
                return False

            def stat(self, follow_symlinks=False):
                return _Stat()

        self.assertTrue(_is_reparse_point(_Entry()))

    def test_extended_path_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.abspath(tmp)
            extended = extended_length_path(folder)
            if os.name == "nt":
                self.assertTrue(extended.startswith("\\\\?\\"))
            self.assertEqual(os.path.normcase(from_extended_length_path(extended)), os.path.normcase(folder))

    def test_discover_lists_nested_files_before_embed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "photos")
            nested = os.path.join(folder, "album")
            os.makedirs(nested)
            self._write(os.path.join(folder, "flat.jpg"))
            self._write(os.path.join(nested, "deep.jpg"))
            self._write(os.path.join(folder, "Windows", "hidden.jpg"), make_dirs=True)
            root = os.path.join(tmp, "gallery")
            add_image_folder(folder, root=root)
            found = discover_image_gallery(root)
            self.assertFalse(found["stopped"])
            self.assertEqual(found["found"], 2)
            status = gallery_status(root, profile_id="model-a")
            self.assertEqual(status["indexed"], 0)
            self.assertEqual(
                {os.path.basename(row["path"]) for row in status["files"]},
                {"flat.jpg", "deep.jpg"},
            )
            self.assertTrue(all(row["pending"] for row in status["files"]))

            def load_image(_path):
                return np.zeros((4, 4, 3), dtype=np.uint8)

            def encode(images):
                return np.asarray([[1.0, 0.0]] * len(images), dtype=np.float32)

            synced = sync_image_gallery(
                root,
                profile_id="model-a",
                encode_images=encode,
                load_image=load_image,
            )
            self.assertFalse(synced["rebuild"])
            self.assertEqual(synced["embedded"], 2)
            listed = gallery_status(root, profile_id="model-a")
            self.assertEqual(listed["indexed"], 2)
            self.assertFalse(any(row["pending"] for row in listed["files"]))

    def test_cancelled_scan_does_not_drop_listed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "photos")
            os.makedirs(folder)
            image_path = os.path.join(folder, "keep.jpg")
            self._write(image_path)
            root = os.path.join(tmp, "gallery")
            add_image_folder(folder, root=root)
            discover_image_gallery(root)
            os.remove(image_path)
            stopped = discover_image_gallery(root, should_stop=lambda: True)
            self.assertTrue(stopped["stopped"])
            self.assertEqual(stopped["deleted"], 0)
            status = gallery_status(root, profile_id="model-a")
            self.assertEqual([os.path.basename(row["path"]) for row in status["files"]], ["keep.jpg"])

            with self.assertRaises(ImageGalleryStopped) as caught:
                sync_image_gallery(
                    root,
                    profile_id="model-a",
                    encode_images=lambda images: np.zeros((len(images), 2), dtype=np.float32),
                    load_image=lambda _path: np.zeros((2, 2, 3), dtype=np.uint8),
                    should_stop=lambda: True,
                )
            self.assertTrue(caught.exception.summary["stopped"])
            self.assertEqual(caught.exception.summary["deleted"], 0)
            self.assertEqual(len(gallery_status(root, profile_id="model-a")["files"]), 1)

    @staticmethod
    def _write(path: str, *, make_dirs: bool = False) -> None:
        if make_dirs:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"jpeg")


class ImageGalleryLanceTests(unittest.TestCase):
    def test_sync_search_roundtrip_and_failed_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "photos")
            os.makedirs(folder)
            good = os.path.join(folder, "near.jpg")
            other = os.path.join(folder, "far.jpg")
            bad = os.path.join(folder, "bad.jpg")
            for path in (good, other, bad):
                with open(path, "wb") as handle:
                    handle.write(b"x")
            root = os.path.join(tmp, "gallery")
            add_image_folder(folder, root=root)

            def load_image(path):
                name = os.path.basename(path).lower()
                if name == "bad.jpg":
                    return None
                if name == "near.jpg":
                    return np.zeros((4, 4, 3), dtype=np.uint8)
                return np.ones((4, 4, 3), dtype=np.uint8)

            def encode(images):
                rows = []
                for image in images:
                    if int(np.asarray(image).reshape(-1)[0]) == 0:
                        rows.append([1.0, 0.0, 0.0])
                    else:
                        rows.append([0.0, 1.0, 0.0])
                return np.asarray(rows, dtype=np.float32)

            first = sync_image_gallery(
                root,
                profile_id="model-a",
                encode_images=encode,
                load_image=load_image,
            )
            self.assertEqual(first["embedded"], 2)
            self.assertEqual(first["failed"], 1)

            second = sync_image_gallery(
                root,
                profile_id="model-a",
                encode_images=encode,
                load_image=load_image,
            )
            self.assertEqual(second["embedded"], 0)
            self.assertEqual(second["failed"], 0)
            self.assertGreaterEqual(second["unchanged"], 2)

            hits = search_image_gallery(
                "a red door",
                root,
                profile_id="model-a",
                embed_text=lambda _text: np.array([1.0, 0.0, 0.0], dtype=np.float32),
            )
            self.assertGreaterEqual(len(hits), 1)
            self.assertTrue(hits[0]["path"].lower().endswith("near.jpg"))
            self.assertGreater(hits[0]["score"], hits[1]["score"] if len(hits) > 1 else -1)

            rebuilt = sync_image_gallery(
                root,
                profile_id="model-b",
                encode_images=encode,
                load_image=load_image,
            )
            self.assertTrue(rebuilt["rebuild"])
            self.assertEqual(rebuilt["embedded"], 2)
            self.assertEqual(rebuilt["failed"], 1)

    def test_direct_vector_search_orders_by_cosine(self):
        with tempfile.TemporaryDirectory() as tmp:
            upsert_image_vectors(
                tmp,
                [
                    {"image_path": "far.jpg", "profile_id": "model-a", "vector": np.array([0.0, 1.0], dtype=np.float32)},
                    {"image_path": "near.jpg", "profile_id": "model-a", "vector": np.array([1.0, 0.0], dtype=np.float32)},
                    {"image_path": "other.jpg", "profile_id": "model-b", "vector": np.array([1.0, 0.0], dtype=np.float32)},
                ],
            )
            ranked = search_image_vectors(
                tmp,
                np.array([1.0, 0.0], dtype=np.float32),
                profile_id="model-a",
                top_k=5,
            )
            self.assertEqual([item[0] for item in ranked], ["near.jpg", "far.jpg"])
            from src.services.image_gallery_service import search_image_gallery_by_vector

            kept = search_image_gallery_by_vector(
                np.array([1.0, 0.0], dtype=np.float32),
                tmp,
                profile_id="model-a",
                min_score=0.5,
            )
            self.assertEqual([item["path"] for item in kept], ["near.jpg"])


if __name__ == "__main__":
    unittest.main()
