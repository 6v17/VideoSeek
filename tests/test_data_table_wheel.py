import unittest

from ui.widgets.table_scroll import table_wheel_pixel_delta


class DataTableWheelTests(unittest.TestCase):
    def test_one_notch_moves_three_rows(self):
        delta = table_wheel_pixel_delta(0, 120, row_height=36)
        self.assertEqual(delta, 108)

    def test_precision_burst_is_capped(self):
        delta = table_wheel_pixel_delta(2400, 120, row_height=36)
        self.assertEqual(delta, 144)

    def test_pixel_delta_preferred_when_small(self):
        delta = table_wheel_pixel_delta(40, 120, row_height=36)
        self.assertEqual(delta, 40)
