"""Regression tests for export data loss, deadlines and destination collisions."""

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.media import export_clip as media
from src.services import clip_export_service as service


@pytest.fixture
def files(tmp_path):
    source = tmp_path / "source.mp4"
    target = tmp_path / "result.mp4"
    source.write_bytes(b"source")
    return source, target


def run_export(source, target, *, status=0, data=b"new", **kwargs):
    def encode(cmd, **options):
        Path(cmd[-1]).write_bytes(data)
        return subprocess.CompletedProcess(cmd, status, b"", b"encode error")

    with (
        patch.object(media, "get_ffmpeg_path", return_value="ffmpeg"),
        patch("src.app.config.load_config", return_value={"test": True}),
        patch.object(media.subprocess, "run", side_effect=encode),
    ):
        return media.export_original_clip(source, 0, 1, target, **kwargs)


def test_failed_encode_preserves_existing_file(files):
    source, target = files
    target.write_bytes(b"old")
    assert run_export(source, target, status=1).returncode == 1
    assert target.read_bytes() == b"old"
    assert not list(target.parent.glob(".videoseek-*"))


def test_success_replaces_file_only_after_encoding(files):
    source, target = files
    target.write_bytes(b"old")
    assert run_export(source, target).returncode == 0
    assert target.read_bytes() == b"new"
    assert source.read_bytes() == b"source"
    assert not list(target.parent.glob(".videoseek-*"))


def test_empty_success_does_not_destroy_old_file(files):
    source, target = files
    target.write_bytes(b"old")
    with pytest.raises(RuntimeError, match="no video output"):
        run_export(source, target, data=b"")
    assert target.read_bytes() == b"old"


def test_source_and_hardlink_are_rejected(files):
    source, target = files
    os.link(source, target)
    for destination in (source, target):
        with pytest.raises(ValueError, match="differ"):
            media.export_original_clip(source, 0, 1, destination)
    assert source.read_bytes() == b"source"


def test_no_overwrite_publication_refuses_existing_file(files):
    source, target = files
    target.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        run_export(source, target, overwrite=False)
    assert target.read_bytes() == b"old"
    assert not list(target.parent.glob(".videoseek-*"))


def test_no_overwrite_publication_creates_file(files):
    source, target = files
    run_export(source, target, overwrite=False)
    assert target.read_bytes() == b"new"
    assert not list(target.parent.glob(".videoseek-*"))


def test_spawn_failure_cleans_temp_and_preserves_target(files):
    source, target = files
    target.write_bytes(b"old")
    with patch.object(media, "build_export_original_clip_command", side_effect=FileNotFoundError):
        with pytest.raises(FileNotFoundError):
            media.export_original_clip(source, 0, 1, target)
    assert target.read_bytes() == b"old"
    assert not list(target.parent.glob(".videoseek-*"))


def test_replace_failure_cleans_temp_and_preserves_target(files):
    source, target = files
    target.write_bytes(b"old")
    with patch.object(media.os, "replace", side_effect=PermissionError("locked")):
        with pytest.raises(PermissionError, match="locked"):
            run_export(source, target)
    assert target.read_bytes() == b"old"
    assert not list(target.parent.glob(".videoseek-*"))


def test_cancelled_desktop_export_keeps_original(files):
    source, target = files
    target.write_bytes(b"old")
    temporary = media._temporary_export_path(target)
    Path(temporary).write_bytes(b"partial")
    process = SimpleNamespace(returncode=0, export_temp_path=temporary, export_output_path=target)
    media.finish_export_process(process, commit=False)
    assert target.read_bytes() == b"old"
    assert not Path(temporary).exists()


def test_successful_desktop_export_publishes(files):
    _, target = files
    temporary = media._temporary_export_path(target)
    Path(temporary).write_bytes(b"new")
    process = SimpleNamespace(returncode=0, export_temp_path=temporary, export_output_path=target)
    media.finish_export_process(process)
    assert target.read_bytes() == b"new"
    assert not Path(temporary).exists()


def test_timeout_kills_and_reaps_real_child(files):
    source, target = files
    target.write_bytes(b"old")
    children = []
    popen = subprocess.Popen

    def launch(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child

    with (
        patch.object(media, "build_export_original_clip_command", return_value=[
            sys.executable, "-c", "import time; time.sleep(10)",
        ]),
        patch.object(media.subprocess, "Popen", side_effect=launch),
    ):
        with pytest.raises(RuntimeError, match="timed out"):
            media.export_original_clip(source, 0, 1, target, timeout_sec=0.1)
    assert children and children[0].poll() is not None
    assert target.read_bytes() == b"old"
    assert not list(target.parent.glob(".videoseek-*"))


def test_expired_deadline_does_not_launch_process(files):
    source, target = files
    token = media.EXPORT_DEADLINE.set(time.monotonic() - 1)
    try:
        with patch.object(media.subprocess, "run") as run:
            with pytest.raises(RuntimeError, match="timed out"):
                media.export_original_clip(source, 0, 1, target)
            run.assert_not_called()
    finally:
        media.EXPORT_DEADLINE.reset(token)


def test_timeout_releases_export_slot(files):
    source, target = files
    with (
        patch.object(service, "output_path_allowed", return_value=True),
        patch.object(service, "resolve_clip_window", return_value=(0, 1)),
        patch("src.utils.has_ffmpeg", return_value=True),
        patch.object(media, "build_export_original_clip_command", return_value=[
            sys.executable, "-c", "import time; time.sleep(10)",
        ]),
    ):
        token = media.EXPORT_DEADLINE.set(time.monotonic() + 0.1)
        try:
            with pytest.raises(RuntimeError, match="timed out"):
                service.execute_export_clip(
                    video_path=str(source), start_sec=0, end_sec=1, output_path=str(target),
                )
        finally:
            media.EXPORT_DEADLINE.reset(token)
    assert_all_copy_slots_available()
    assert not service._active_destinations


def assert_all_copy_slots_available():
    semaphore = service._copy_export_semaphore
    acquired = [semaphore.acquire(blocking=False) for _ in range(service.MAX_CONCURRENT_COPY_EXPORTS)]
    try:
        assert all(acquired)
        assert not semaphore.acquire(blocking=False)
    finally:
        for held in acquired:
            if held:
                semaphore.release()


def test_batch_rejects_duplicate_destinations_before_starting(files):
    source, target = files
    item = SimpleNamespace(video_path=str(source), output_path=str(target))
    body = SimpleNamespace(items=[item, item])
    with patch.object(service, "_run_batch_export_item") as run:
        with pytest.raises(ValueError, match="distinct"):
            service.execute_batch_export_clips(body)
        run.assert_not_called()


def test_generated_names_preserve_milliseconds_and_source_identity(tmp_path):
    from src.web.agent_api import export_ops

    with (
        patch.object(export_ops, "output_path_allowed", return_value=True),
        patch.object(export_ops, "load_config", return_value={}),
    ):
        paths = [export_ops.resolve_export_clip_output_path(
            output_dir=str(tmp_path), video_path=source, start_sec=start, end_sec=end,
        ) for source, start, end in (
            ("a/clip.mp4", 1.1, 2.1), ("a/clip.mp4", 1.8, 2.8),
            ("b/clip.mp4", 1.1, 2.1), ("a/clip.mp4", 1.1, 2.1),
        )]
    assert len(set(paths)) == 4
    assert "_1100ms_2100ms_" in paths[0]
    assert "_1800ms_2800ms_" in paths[1]
    assert Path(paths[0]).name.split("_")[1] != Path(paths[2]).name.split("_")[1]


def test_api_and_batch_threads_receive_deadline(files):
    from src.web.agent_api.service import _run_export_with_deadline

    source, target = files
    item = SimpleNamespace(video_path=str(source), output_path=str(target), start_sec=0, end_sec=1)
    body = SimpleNamespace(items=[item])
    observed = []

    def export(**kwargs):
        observed.append(media.EXPORT_DEADLINE.get())
        return {"ok": True}

    with (
        patch("src.utils.has_ffmpeg", return_value=True),
        patch.object(service, "load_config", return_value={}),
        patch.object(service, "execute_export_clip", side_effect=export),
    ):
        asyncio.run(_run_export_with_deadline(service.execute_batch_export_clips, body, timeout=2))
    assert observed and observed[0] is not None
    assert media.EXPORT_DEADLINE.get() is None


def test_api_timeout_stops_child_and_returns_slot(files):
    from src.web.agent_api.service import _run_export_with_deadline

    source, target = files
    children = []
    popen = subprocess.Popen

    def launch(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child

    with (
        patch.object(service, "output_path_allowed", return_value=True),
        patch.object(service, "resolve_clip_window", return_value=(0, 1)),
        patch("src.utils.has_ffmpeg", return_value=True),
        patch.object(media, "build_export_original_clip_command", return_value=[
            sys.executable, "-c", "import time; time.sleep(10)",
        ]),
        patch.object(media.subprocess, "Popen", side_effect=launch),
    ):
        with pytest.raises((TimeoutError, RuntimeError)):
            asyncio.run(_run_export_with_deadline(
                service.execute_export_clip, video_path=str(source), start_sec=0,
                end_sec=1, output_path=str(target), timeout=0.1,
            ))
    assert children and children[0].poll() is not None
    assert not service._active_destinations
    assert_all_copy_slots_available()
    assert not list(target.parent.glob(".videoseek-*"))
