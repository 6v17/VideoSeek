import sys
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from src.app.single_instance import (
    SingleInstanceServer,
    single_instance_server_name,
    try_activate_existing_instance,
)


class SingleInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication(sys.argv)

    def test_server_name_is_stable_for_session(self):
        self.assertEqual(single_instance_server_name(), single_instance_server_name())

    def test_secondary_launch_connects_to_primary(self):
        name = f"{single_instance_server_name()}_test_connect"
        server = SingleInstanceServer(server_name=name)
        self.addCleanup(server._server.close)
        self.assertTrue(try_activate_existing_instance(server_name=name))

    def test_activate_handler_dispatched(self):
        name = f"{single_instance_server_name()}_test_dispatch"
        activated = []
        server = SingleInstanceServer(server_name=name)
        server.set_activate_handler(lambda: activated.append(True))
        with patch("src.app.single_instance.QTimer.singleShot", side_effect=lambda _ms, fn: fn()):
            server._dispatch_activate()
        self.assertEqual(activated, [True])


if __name__ == "__main__":
    unittest.main()
