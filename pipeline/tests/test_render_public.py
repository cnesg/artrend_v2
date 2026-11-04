import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from artrend_mag import render_public


class PublicRendererPolicyTests(unittest.TestCase):
    def setUp(self):
        self.origin = "https://www.guggenheim.org"

    def test_normal_css_and_scripts_are_not_access_challenges(self):
        response = SimpleNamespace(content_type="text/css", content=b".g-recaptcha {display:block}",
                                   url="https://kiaf.org/app.css", status=200)
        render_public._reject_challenge(response)
        render_public._reject_challenge_text(
            '<html><title>Exhibitors</title><style>.g-recaptcha{}</style>'
            '<script>const label="verify you are human";</script><main>Public exhibitor list</main></html>',
            "https://kiaf.org/exhibitors-index", 200)

    def test_real_html_access_challenges_still_stop(self):
        for html in ('<title>Captcha verification</title>', '<main>Verify you are human</main>',
                     '<title>Just a moment...</title><script src="/cdn-cgi/challenge-platform/x"></script>'):
            with self.subTest(html=html), self.assertRaises(render_public.Blocked):
                render_public._reject_challenge_text(html, "https://example.org", 200)

    def test_same_origin_public_get_allowlist(self):
        self.assertTrue(render_public.request_allowed(
            "https://www.guggenheim.org/wp-content/site.js", "GET", "script", {}, self.origin))
        self.assertTrue(render_public.request_allowed(
            "https://www.guggenheim.org/exhibitions", "GET", "fetch", {}, self.origin))
        self.assertFalse(render_public.request_allowed(
            "https://cdn.example.org/site.js", "GET", "script", {}, self.origin))
        self.assertFalse(render_public.request_allowed(
            "https://www.guggenheim.org/image.jpg", "GET", "image", {}, self.origin))
        self.assertFalse(render_public.request_allowed(
            "https://www.guggenheim.org/submit", "POST", "xhr", {}, self.origin))

    def test_credentials_and_key_tokens_are_rejected(self):
        for url in (
            "https://www.guggenheim.org/data?apiKey=secret",
            "https://www.guggenheim.org/data?access_token=secret",
            "https://www.guggenheim.org/data?privateKey=secret",
        ):
            with self.subTest(url=url):
                self.assertFalse(render_public.request_allowed(url, "GET", "fetch", {}, self.origin))
        self.assertFalse(render_public.request_allowed(
            "https://www.guggenheim.org/data", "GET", "fetch", {"authorization": "Bearer secret"}, self.origin))
        self.assertFalse(render_public.request_allowed(
            "https://www.guggenheim.org/data", "GET", "fetch", {"cookie": "session=secret"}, self.origin))

    def test_rendered_dom_is_archived_with_hash_and_index_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = SimpleNamespace(source_id="guggenheim_exhibitions",
                                      fetcher=SimpleNamespace(run_stamp="render-test"))
            body = "<html><main>Public exhibitions</main></html>"
            with patch.object(render_public, "WORK_ROOT", root), \
                 patch.object(render_public, "RAW_ROOT", root / "raw"), \
                 patch.object(render_public, "iso_now", return_value="2026-10-28T09:00:00+09:00"):
                response = render_public._archive_rendered(
                    context, "https://www.guggenheim.org/exhibitions",
                    "https://www.guggenheim.org/exhibitions", body, 200)

            archived = root / response.raw_path
            self.assertEqual(archived.read_text(encoding="utf-8"), body)
            self.assertEqual(response.sha256, hashlib.sha256(body.encode("utf-8")).hexdigest())
            self.assertEqual(response.status, 200)
            record = json.loads((archived.parent / "_index.jsonl").read_text(encoding="utf-8"))
            self.assertTrue(record["rendered"])
            self.assertEqual(record["sha256"], response.sha256)
            self.assertEqual(record["fetched_at"], response.fetched_at)


if __name__ == "__main__":
    unittest.main()
