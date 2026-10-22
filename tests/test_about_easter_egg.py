from ui.dialogs.about import _EASTER_EGG_CLICKS, _EASTER_EGG_WINDOW_MS


def test_easter_egg_thresholds_are_sane():
    assert _EASTER_EGG_CLICKS == 7
    assert 1000 <= _EASTER_EGG_WINDOW_MS <= 10_000
