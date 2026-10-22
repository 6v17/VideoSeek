from src.services.bundled_runtime_errors import (
    check_disk_space_for_import,
    classify_bundled_import_error,
    format_bundled_import_error,
)


def test_classify_disk_full():
    assert classify_bundled_import_error("disk_full: need about 100 MB") == "disk_full"
    assert classify_bundled_import_error("WinError 112") == "disk_full"
    assert classify_bundled_import_error("空间不足") == "disk_full"


def test_format_bundled_import_error_uses_i18n():
    texts = {"runtime_bundled_error_disk_full": "磁盘空间不足"}
    assert format_bundled_import_error("disk_full: x", texts) == "磁盘空间不足"


def test_check_disk_space_returns_none_when_enough(monkeypatch, tmp_path):
    target = tmp_path / "models"
    target.mkdir()
    seed = tmp_path / "big.zip"
    seed.write_bytes(b"x" * 1024)

    class Usage:
        free = 10 * 1024 * 1024 * 1024

    monkeypatch.setattr("shutil.disk_usage", lambda _p: Usage())
    assert check_disk_space_for_import([str(seed)], target_dir=str(target)) is None


def test_check_disk_space_returns_message_when_low(monkeypatch, tmp_path):
    target = tmp_path / "models"
    target.mkdir()
    seed = tmp_path / "big.zip"
    seed.write_bytes(b"x" * (64 * 1024 * 1024))

    class Usage:
        free = 1024

    monkeypatch.setattr("shutil.disk_usage", lambda _p: Usage())
    msg = check_disk_space_for_import([str(seed)], target_dir=str(target))
    assert msg is not None
    assert classify_bundled_import_error(msg) == "disk_full"
