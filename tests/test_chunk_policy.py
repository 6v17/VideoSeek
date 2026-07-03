import unittest

from src.app.config import DEFAULT_CONFIG
from src.core.chunk_policy import (
    CHUNK_POLICY_BALANCED,
    CHUNK_POLICY_CUSTOM,
    CHUNK_POLICY_SENSITIVE,
    CHUNK_POLICY_STABLE,
    apply_chunk_policy,
    detect_chunk_policy,
    resolve_chunk_policy_values,
)


class ChunkPolicyTests(unittest.TestCase):
    def test_resolve_balanced_preset(self):
        values = resolve_chunk_policy_values(CHUNK_POLICY_BALANCED)
        self.assertEqual(values["similarity_threshold"], 0.85)
        self.assertEqual(values["min_chunk_duration"], 0.0)
        self.assertEqual(values["min_chunk_size"], 2)

    def test_detect_balanced_from_default_config(self):
        policy = detect_chunk_policy(DEFAULT_CONFIG)
        self.assertEqual(policy, CHUNK_POLICY_BALANCED)

    def test_detect_custom_when_values_differ(self):
        config = dict(DEFAULT_CONFIG)
        config["similarity_threshold"] = 0.72
        self.assertEqual(detect_chunk_policy(config), CHUNK_POLICY_CUSTOM)

    def test_apply_sensitive_preset(self):
        config = apply_chunk_policy({}, CHUNK_POLICY_SENSITIVE)
        self.assertEqual(config["chunk_policy"], CHUNK_POLICY_SENSITIVE)
        self.assertEqual(config["similarity_threshold"], 0.88)
        self.assertEqual(config["min_chunk_duration"], 0.0)

    def test_apply_custom_does_not_overwrite_values(self):
        config = {"similarity_threshold": 0.91, "chunk_policy": CHUNK_POLICY_CUSTOM}
        updated = apply_chunk_policy(config, CHUNK_POLICY_CUSTOM)
        self.assertEqual(updated["similarity_threshold"], 0.91)
        self.assertEqual(updated["chunk_policy"], CHUNK_POLICY_CUSTOM)

    def test_detect_stable_preset(self):
        config = apply_chunk_policy({}, CHUNK_POLICY_STABLE)
        self.assertEqual(detect_chunk_policy(config), CHUNK_POLICY_STABLE)


if __name__ == "__main__":
    unittest.main()
