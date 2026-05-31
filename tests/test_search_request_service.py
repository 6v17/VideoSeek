import unittest
from unittest.mock import patch

from src.services.search_request_service import (
    default_agent_image_precision_mode,
    normalize_search_precision_mode,
    validate_inline_image_query,
)


class SearchRequestServiceTests(unittest.TestCase):
    @patch("src.services.search_request_service.load_config")
    def test_default_agent_image_precision_mode(self, mock_load_config):
        mock_load_config.return_value = {"agent_api_default_image_precision": "precise"}
        self.assertEqual(default_agent_image_precision_mode(), "precise")

    @patch("src.services.search_request_service.load_config")
    def test_normalize_search_precision_mode_agent_default(self, mock_load_config):
        mock_load_config.return_value = {"agent_api_default_image_precision": "precise"}
        self.assertEqual(
            normalize_search_precision_mode(
                None,
                is_text=False,
                has_image=True,
                use_agent_default=True,
            ),
            "precise",
        )
        self.assertEqual(
            normalize_search_precision_mode(
                None,
                is_text=True,
                has_image=False,
                use_agent_default=True,
            ),
            "fast",
        )

    def test_normalize_search_precision_mode_without_agent_default(self):
        self.assertEqual(
            normalize_search_precision_mode(None, is_text=False, has_image=True),
            "fast",
        )

    def test_validate_inline_image_query_missing(self):
        with self.assertRaises(ValueError):
            validate_inline_image_query("D:/missing.png")
