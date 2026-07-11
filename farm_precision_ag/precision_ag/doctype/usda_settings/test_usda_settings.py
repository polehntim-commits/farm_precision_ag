"""Stub tests for USDA Settings.

TODO(Phase 2): once a bench test site exists, assert that:
- get_api_key() prefers the Password field over site_config, falls back to it.
- validate() stamps api_key_last_rotated only when the key actually changes.
- api_key is not readable by HR Manager / Sales Manager (permlevel 1).
"""

import unittest


class TestUSDASettings(unittest.TestCase):
    def test_placeholder(self):
        self.assertTrue(True)
