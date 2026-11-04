import sqlite3
import tempfile
import unittest
from pathlib import Path

from artrend_mag import db, translation_merge
from artrend_mag.translation import translate_metadata


class Backend:
    model_name = 'test'
    model_version = '1'

    def translate(self, text, source_lang, target_lang):
        return '한국어 번역문'

    def translate_many(self, texts, source_lang, target_lang):
        return [self.translate(text, source_lang, target_lang) for text in texts]


def connection(path):
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    db.init_schema(con)
    db.upsert_source(con, 'test', name='Test', source_kind='museum', access_method='local')
    return con


def event(con, key, title, lang='en'):
    return db.upsert_event(con, {}, source_id='test', source_event_key=key, event_type='exhibition',
                           title=title, title_lang=lang, url='https://example.org/' + key, parser_version='test-1')


class TranslationMergeTests(unittest.TestCase):
    def test_only_current_text_and_language_merge_and_repeat_is_unchanged(self):
        root = translation_merge.WORK_ROOT / 'work' / 'tmp'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(root)) as directory:
            source_path = Path(directory) / 'source.sqlite'
            source, target = connection(source_path), connection(Path(directory) / 'target.sqlite')
            for key in ('good', 'changed', 'language', 'removed'):
                event(source, key, 'Original title')
            good = event(target, 'good', 'Original title')
            event(target, 'changed', 'Changed title')
            event(target, 'language', 'Original title', 'ja')
            translate_metadata(source, backend=Backend())
            source.commit()
            source.close()
            result = translation_merge.merge_translations(target, source_path)
            self.assertEqual(result['merged_changes'], 1)
            self.assertEqual(result['rejected_stale_or_missing'], 3)
            self.assertEqual(translation_merge.merge_translations(target, source_path)['merged_changes'], 0)
            self.assertEqual(target.execute('SELECT title FROM events WHERE event_id=?', (good,)).fetchone()[0], 'Original title')
            event(target, 'good', 'A new source title')
            self.assertEqual(translation_merge.invalidate_stale_translations(target), 1)
            row = target.execute('SELECT status,translation_ko,status_reason FROM metadata_translations').fetchone()
            self.assertEqual(tuple(row), ('pending', None, 'source_changed_or_removed'))
            target.close()

    def test_corrupt_source_text_hash_is_not_accepted(self):
        root = translation_merge.WORK_ROOT / 'work' / 'tmp'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(root)) as directory:
            path = Path(directory) / 'source.sqlite'
            source, target = connection(path), connection(Path(directory) / 'target.sqlite')
            event(source, 'same', 'Original title')
            event(target, 'same', 'Original title')
            translate_metadata(source, backend=Backend())
            source.execute("UPDATE metadata_translations SET source_text_hash='corrupt'")
            source.commit()
            source.close()
            result = translation_merge.merge_translations(target, path)
            self.assertEqual(result['merged_changes'], 0)
            self.assertEqual(result['rejected_stale_or_missing'], 1)
            target.close()


if __name__ == '__main__':
    unittest.main()
