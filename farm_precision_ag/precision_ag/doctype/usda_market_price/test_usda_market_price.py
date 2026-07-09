"""Stub tests for USDA Market Price.

TODO(Phase 2): once a bench test site exists, assert that inserting two prices
with the same DEDUP_FIELDS raises frappe.DuplicateEntryError, and that differing
on any one dedup field is allowed.
"""

import unittest


class TestUSDAMarketPrice(unittest.TestCase):
    def test_placeholder(self):
        self.assertTrue(True)
