import argparse
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from artrend_mag import cli, config, runner
from artrend_mag.sources._common import parse_date_range
from artrend_mag.sources import gl_media
from artrend_mag.http import _is_login_url


class PipelineContracts(unittest.TestCase):
    def test_runtime_temporaries_stay_inside_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.object(config, 'WORK_ROOT', root), patch.dict(os.environ), patch.object(tempfile, 'tempdir', None):
                path = config.configure_local_temporary_files()
                self.assertEqual(path, root / 'work' / 'tmp')
                self.assertEqual(Path(tempfile.gettempdir()), path)
                self.assertEqual(os.environ['SQLITE_TMPDIR'], str(path))
                self.assertTrue(path.is_dir())

    def test_login_endpoints_not_exhibition_titles(self):
        for url in ('https://example.org/login?next=/art', 'https://example.org/account/sign-in',
                    'https://example.org/signin.aspx', 'https://login.example.org/',
                    'https://example.org/%6cogin'):
            self.assertTrue(_is_login_url(url), url)
        for url in ('https://www.e-flux.com/criticism/601648/tina-girouard-s-sign-in',
                    'https://example.org/art?title=sign-in'):
            self.assertFalse(_is_login_url(url), url)

    def test_archive_backfill_passes_known_prefix(self):
        urls = [f"https://www.e-flux.com/criticism/{i}/test" for i in range(302, 0, -1)]
        xml = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(
            f'<url><loc>{url}</loc></url>' for url in urls) + '</urlset>'
        for mode, expected_details in [('initial', 1), ('incremental', 0)]:
            with self.subTest(mode=mode):
                ctx = Mock()
                ctx.mode = mode
                ctx.source_id = 'eflux_criticism'
                ctx.meta = {'entry_url': 'https://www.e-flux.com/sitemaps/criticism.xml'}
                ctx.fetch.side_effect = [Mock(content=xml.encode()), Mock(text='')]
                with patch.object(gl_media, '_known', side_effect=lambda c, url: url != urls[-1]), \
                     patch.object(gl_media, 'jsonld_objects', return_value=[{'@type': 'Review', 'headline': 'Archive review'}]), \
                     patch.object(gl_media, '_store') as store:
                    gl_media._collect_eflux(ctx)
                self.assertEqual(store.call_count, expected_details)
                self.assertEqual(ctx.fetch.call_count, 1 + expected_details)

    def test_date_ranges(self):
        cases = {
            'December 1–5, 2026': ('2026-12-01', 'day', '2026-12-05', 'day'),
            'Feb 4 – 21, 2021': ('2021-02-04', 'day', '2021-02-21', 'day'),
            '4–21 February 2026': ('2026-02-04', 'day', '2026-02-21', 'day'),
            '6 set 2025 – 11 jan 2026': ('2025-09-06', 'day', '2026-01-11', 'day'),
            'Through January 4, 2027': (None, None, '2027-01-04', 'day'),
            # <sup>th</sup> rendered with get_text(' ') (observed on crousel.com, 2026-10-28)
            'October 19 th — November 21 st , 2026': ('2026-10-19', 'day', '2026-11-21', 'day'),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_date_range(text, default_year=2026), expected)

    def test_credential_check_matches_parameter_names_not_pagination_cursors(self):
        from artrend_mag.validate import has_credential_param
        self.assertFalse(has_credential_param(
            "https://data.rijksmuseum.nl/oai?verb=ListRecords&resumptionToken=abc"))
        self.assertTrue(has_credential_param("https://apis.data.go.kr/x?serviceKey=SECRET&pageNo=1"))
        self.assertTrue(has_credential_param("https://api.example.org/v1?api_key=SECRET"))
        self.assertTrue(has_credential_param("https://api.example.org/v1?Token=SECRET"))

    def test_restricted_feeds_disabled(self):
        registry = runner.discover()
        for sid in ('artnews_feed', 'art_in_america_feed', 'artforum_feed', 'artasiapacific_rss'):
            self.assertTrue(registry[sid][1]['disabled'])
            self.assertEqual(registry[sid][1]['operational_state'], 'blocked_permission')

    def test_region_update_order_and_export_on_validation_failure(self):
        calls = []
        registry = {'kr': (None, {'region_scope': 'KR'}), 'jp': (None, {'region_scope': 'JP'})}
        def collect(args):
            calls.append(('collect', args.sources))
        def validate(args):
            calls.append(('validate', None))
            raise SystemExit(1)
        with patch.object(runner, 'discover', return_value=registry), \
             patch.object(cli, 'cmd_collect', side_effect=collect), \
             patch.object(cli, 'cmd_derive', side_effect=lambda a: calls.append(('derive', None))), \
             patch.object(cli, 'cmd_validate', side_effect=validate), \
             patch.object(cli, 'cmd_export', side_effect=lambda a: calls.append(('export', None))):
            with self.assertRaises(SystemExit):
                cli.cmd_update(argparse.Namespace(region='KR', mode='incremental', translate=False))
        self.assertEqual(calls, [('collect', 'kr'), ('derive', None),
                                 ('collect', 'wikidata_ids,wikimedia_pageviews'),
                                 ('derive', None), ('validate', None), ('export', None)])

    def test_update_translates_after_collection_and_exports_on_translation_error(self):
        from artrend_mag import translation
        calls = []
        with patch.object(runner, 'discover', return_value={'kr': (None, {'region_scope': 'KR'})}), \
             patch.object(translation, 'model_availability', return_value={'available': True}), \
             patch.object(cli, 'cmd_collect', side_effect=lambda a: calls.append('collect')), \
             patch.object(cli, 'cmd_derive', side_effect=lambda a: calls.append('derive')), \
             patch.object(translation, 'main', side_effect=RuntimeError('inference failed')) as translate, \
             patch.object(cli, 'cmd_validate') as validate, \
             patch.object(cli, 'cmd_export', side_effect=lambda a: calls.append('export')):
            with self.assertRaisesRegex(RuntimeError, 'inference failed'):
                cli.cmd_update(argparse.Namespace(region='KR', mode='incremental', translate=True))
            translate.assert_called_once_with(['--batch-size', '128'])
            validate.assert_not_called()
        self.assertEqual(calls, ['collect', 'derive', 'collect', 'derive', 'export'])


if __name__ == '__main__':
    unittest.main()


class DiscoveryIsolationTests(unittest.TestCase):
    def test_broken_source_module_does_not_hide_other_sources(self):
        import importlib
        real = importlib.import_module

        def fake(name, *args, **kwargs):
            if name.endswith('.kr_kiaf'):
                raise IndentationError('expected an indented block')
            return real(name, *args, **kwargs)

        with patch('importlib.import_module', side_effect=fake):
            registry = runner.discover()
        self.assertIn('kr_kiaf', runner.IMPORT_ERRORS)
        self.assertNotIn('kiaf_seoul', registry)
        self.assertIn('eflux_criticism', registry)
        runner.discover()
        self.assertEqual(runner.IMPORT_ERRORS, {})
