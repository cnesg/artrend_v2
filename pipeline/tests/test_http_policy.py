import unittest
from unittest.mock import Mock

import requests

from artrend_mag.http import Blocked, Fetcher
from artrend_mag.robots import Robots


class RobotsFailureClassificationTests(unittest.TestCase):
    def fetcher(self):
        fetcher = Fetcher.__new__(Fetcher)
        fetcher.api_policy_url = None
        fetcher._robots = {}
        fetcher._robots_state = {}
        fetcher._last = {}
        fetcher.stats = {}
        fetcher.s = Mock()
        return fetcher

    def test_connection_failure_is_not_permission_denial(self):
        fetcher = self.fetcher()
        fetcher.s.get.side_effect = requests.ConnectionError("offline fixture")
        with self.assertRaises(Blocked) as raised:
            fetcher.get("https://example.org/results")
        self.assertEqual(raised.exception.kind, "robots_unavailable")
        self.assertIn("ConnectionError", raised.exception.detail)
        self.assertEqual(fetcher.s.get.call_count, 1)
        self.assertEqual(fetcher.s.get.call_args.args[0], "https://example.org/robots.txt")

    def test_unavailable_robots_http_status_never_fetches_target(self):
        for status in (403, 429, 503):
            with self.subTest(status=status):
                fetcher = self.fetcher()
                fetcher.s.get.return_value = Mock(status_code=status)
                with self.assertRaises(Blocked) as raised:
                    fetcher.get("https://example.org/results")
                self.assertEqual(raised.exception.kind, "robots_unavailable")
                self.assertIn(str(status), raised.exception.detail)
                self.assertEqual(fetcher.s.get.call_count, 1)

    def test_explicit_disallow_remains_permission_denial(self):
        fetcher = self.fetcher()
        fetcher._robots["example.org"] = Robots("User-agent: *\nDisallow: /")
        fetcher._robots_state["example.org"] = "parsed"
        with self.assertRaises(Blocked) as raised:
            fetcher.get("https://example.org/results")
        self.assertEqual(raised.exception.kind, "robots_disallow")
        fetcher.s.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
