import unittest

from ui.widgets.table_scroll import table_wheel_pixel_delta


class DataTableWheelTests(unittest.TestCase):
    def test_one_notch_moves_one_row(self):
        delta = table_wheel_pixel_delta(0, 120, row_height=36)
        self.assertEqual(delta, 36)

    def test_precision_burst_is_capped(self):
        delta = table_wheel_pixel_delta(2400, 120, row_height=36)
        self.assertEqual(delta, 72)

    def test_pixel_delta_preferred_when_small(self):
        delta = table_wheel_pixel_delta(40, 120, row_height=36)
        self.assertEqual(delta, 40)

    def test_tall_search_row_one_notch(self):
        delta = table_wheel_pixel_delta(0, 120, row_height=88)
        self.assertEqual(delta, 88)
