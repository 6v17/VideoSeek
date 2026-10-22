from ui.dialogs.about import _VERSION_TAP_COUNT, _VERSION_TAP_WINDOW_MS


def test_version_tap_thresholds_are_sane():
    assert _VERSION_TAP_COUNT == 7
    assert 1000 <= _VERSION_TAP_WINDOW_MS <= 10_000
