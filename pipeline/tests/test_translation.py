import hashlib
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from artrend_mag.translation import (
    ArgosPivotBackend,
    BackendUnavailable,
    LocalTranslationBackend,
    MODEL_NAME,
    detect_language,
    translate_metadata,
)
from artrend_mag.opus_korean import MODEL_VERSION as OPUS_MODEL_VERSION


class MockBackend:
    model_name = "mock-en-ko"
    model_version = "test-1"

    def __init__(self, fail=False, output=None):
        self.calls = []
        self.fail = fail
        self.output = output

    def translate(self, text, source_lang, target_lang):
        self.calls.append((text, source_lang, target_lang))
        if self.fail:
            raise RuntimeError("mock failure")
        return self.output if self.output is not None else "한국어 번역문"


class BatchMockBackend(MockBackend):
    def __init__(self, failed_texts=()):
        super().__init__()
        self.failed_texts = set(failed_texts)
        self.batch_calls = []

    def translate_many(self, texts, source_lang, target_lang):
        self.batch_calls.append((list(texts), source_lang, target_lang))
        outputs = []
        for text in texts:
            self.calls.append((text, source_lang, target_lang))
            if text in self.failed_texts:
                outputs.append(RuntimeError("failed: " + text))
            else:
                outputs.append("한국어 번역문")
        return outputs


def confidence_values(best=0.96, second=0.02):
    return [SimpleNamespace(value=value, language=SimpleNamespace(
        iso_code_639_1=SimpleNamespace(name=code))) for code, value in [('EN', best), ('DE', second)]]


def make_connection():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE events(event_id TEXT, title TEXT, title_lang TEXT, description_excerpt TEXT);
        CREATE TABLE articles(article_id TEXT, title TEXT, lang TEXT, excerpt TEXT);
        CREATE TABLE works(work_id TEXT, title TEXT);
        CREATE TABLE reports(report_id TEXT, title TEXT);
        CREATE TABLE report_metrics(metric_id TEXT, excerpt TEXT);
        """
    )
    return con


def make_argos_pivot_backend(encode_error=None, batch_error=None):
    class FakeTokenizer:
        target_prefix = ">>en<<"

        def encode(self, text):
            if text == encode_error:
                raise ValueError("tokenization failed: " + text)
            return [text]

        def decode(self, tokens):
            return " ".join(tokens)

    class FakeTranslator:
        def __init__(self):
            self.calls = []

        def translate_batch(self, tokenized, **kwargs):
            self.calls.append((tokenized, kwargs))
            if batch_error is not None and len(tokenized) > 1:
                raise RuntimeError("simulated source batch failure")
            results = []
            for tokens in tokenized:
                text = tokens[0]
                if batch_error == text:
                    raise ValueError("source inference failed: " + text)
                results.append(
                    SimpleNamespace(
                        hypotheses=[[">>en<<", "English " + text]],
                        scores=[-0.1],
                    )
                )
            return results

    translator = FakeTranslator()
    pkg = SimpleNamespace(
        tokenizer=FakeTokenizer(),
        target_prefix=">>en<<",
        package_path="/local/argos-ja-en",
        type="sbd",
    )
    package_translation = SimpleNamespace(pkg=pkg, translator=translator)
    backend = ArgosPivotBackend.__new__(ArgosPivotBackend)
    backend._translations = {"ja": package_translation}
    backend._translate_module = SimpleNamespace(
        ITranslation=SimpleNamespace(split_into_paragraphs=lambda text: text.split("\n")),
        settings=SimpleNamespace(device="cpu"),
    )
    return backend, translator


class TranslationTests(unittest.TestCase):
    def test_translation_preserves_source_and_is_idempotent(self):
        con = make_connection()
        con.execute("INSERT INTO events VALUES (?, ?, ?, ?)", ("event-1", "Open Forms", "en", None))
        excerpt = "A short article excerpt."
        con.execute("INSERT INTO articles VALUES (?, ?, ?, ?)", ("article-1", "News", "en", excerpt))
        backend = MockBackend()

        first = translate_metadata(con, backend=backend, batch_size=1)
        second = translate_metadata(con, backend=backend, batch_size=1)

        row = con.execute(
            "SELECT * FROM metadata_translations WHERE source_table='events'"
        ).fetchone()
        self.assertEqual(first["translated"], 3)
        self.assertEqual(second["scanned"], 0)
        self.assertEqual(len(backend.calls), 3)
        self.assertEqual(row["original_text"], "Open Forms")
        self.assertEqual(row["source_text_hash"], hashlib.sha256(b"Open Forms").hexdigest())
        self.assertEqual(row["translation_ko"], "한국어 번역문")
        self.assertEqual(row["model"], "mock-en-ko")
        self.assertEqual(row["model_version"], "test-1")
        self.assertEqual(row["source_lang"], "en")
        self.assertEqual(row["language_basis"], "metadata")
        self.assertEqual(
            row["language_detector_version"],
            "lingua-language-detector==2.0.2;script-rules=1",
        )
        self.assertEqual(row["language_confidence"], 1.0)
        self.assertIsNone(row["language_margin"])
        self.assertEqual(row["needs_review"], 1)
        excerpt_row = con.execute(
            "SELECT * FROM metadata_translations WHERE source_table='articles' "
            "AND source_field='excerpt'"
        ).fetchone()
        self.assertEqual(excerpt_row["original_text"], excerpt)
        self.assertEqual(excerpt_row["translation_ko"], "한국어 번역문")

    def test_missing_local_model_leaves_english_pending_without_fabricating_output(self):
        con = make_connection()
        con.execute("INSERT INTO events VALUES (?, ?, ?, ?)", ("event-1", "Open Forms", "en", None))

        stats = translate_metadata(con, backend=None, unavailable_reason="model not installed")
        row = con.execute("SELECT * FROM metadata_translations").fetchone()

        self.assertEqual(stats["pending"], 1)
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["status_reason"], "model not installed")
        self.assertIsNone(row["translation_ko"])

    def test_changed_source_text_retranslates_and_replaces_stale_original(self):
        con = make_connection()
        con.execute("INSERT INTO events VALUES (?, ?, ?, ?)", ("event-1", "Old title", "en", None))
        backend = MockBackend()
        translate_metadata(con, backend=backend)
        con.execute("UPDATE events SET title='New title' WHERE event_id='event-1'")

        result = translate_metadata(con, backend=backend)
        row = con.execute(
            "SELECT * FROM metadata_translations WHERE source_table='events'"
        ).fetchone()

        self.assertEqual(result["translated"], 1)
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(row["original_text"], "New title")
        self.assertEqual(row["translation_ko"], "한국어 번역문")
        self.assertEqual(row["source_text_hash"], hashlib.sha256(b"New title").hexdigest())

    def test_unknown_unsupported_remain_pending_and_oversized_excerpt_is_not_read(self):
        con = make_connection()
        con.execute("INSERT INTO articles VALUES (?, ?, ?, ?)", ("a1", "Unknown", "xx", None))
        con.execute("INSERT INTO articles VALUES (?, ?, ?, ?)", ("a2", "Unspecified", None, None))
        con.execute("INSERT INTO articles VALUES (?, ?, ?, ?)", ("a3", "Long", "en", "x" * 301))
        backend = BatchMockBackend()

        stats = translate_metadata(con, backend=backend)
        rows = con.execute(
            "SELECT source_key, status, status_reason, translation_ko FROM metadata_translations "
            "ORDER BY source_key"
        ).fetchall()

        self.assertEqual(stats["pending"], 2)
        self.assertEqual(stats["translated"], 1)
        self.assertEqual(len(backend.calls), 1)
        self.assertIn("unsupported source language", rows[0]["status_reason"])
        self.assertIn("not recorded", rows[1]["status_reason"])
        self.assertEqual(backend.batch_calls, [(["Long"], "en", "ko")])
        self.assertEqual(
            con.execute(
                "SELECT COUNT(*) FROM metadata_translations "
                "WHERE source_table='articles' AND source_field='excerpt'"
            ).fetchone()[0],
            0,
        )

    def test_korean_original_skips_and_invalid_model_output_is_error(self):
        con = make_connection()
        con.execute("INSERT INTO events VALUES (?, ?, ?, ?)", ("ko", "한국어 제목", "ko", None))
        con.execute("INSERT INTO events VALUES (?, ?, ?, ?)", ("bad", "English title", "en", None))
        backend = MockBackend(output="English title")

        stats = translate_metadata(con, backend=backend)
        rows = {
            row["source_key"]: row
            for row in con.execute("SELECT * FROM metadata_translations")
        }

        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["error"], 1)
        self.assertEqual(rows["ko"]["status"], "skipped")
        self.assertEqual(rows["bad"]["status"], "error")
        self.assertIsNone(rows["bad"]["translation_ko"])

    def test_backend_errors_are_recorded_for_retry(self):
        con = make_connection()
        con.execute("INSERT INTO events VALUES (?, ?, ?, ?)", ("event-1", "Open Forms", "en", None))

        stats = translate_metadata(con, backend=MockBackend(fail=True))
        row = con.execute("SELECT * FROM metadata_translations").fetchone()

        self.assertEqual(stats["error"], 1)
        self.assertEqual(row["status"], "error")
        self.assertIn("mock failure", row["status_reason"])
        self.assertIsNone(row["translation_ko"])

    @patch('artrend_mag.translation._get_lingua_detector')
    def test_language_detection_is_conservative_and_records_its_basis(self, detector):
        detector.return_value.compute_language_confidence_values.return_value = confidence_values()
        decision = detect_language("The Gallery of the City and the River")
        japanese = detect_language("東京のアート展", "en")
        ambiguous_han = detect_language("東京美術館", "en")
        tagged_japanese_han = detect_language("東京美術館", "ja")

        self.assertEqual(decision.language, "en")
        self.assertEqual(decision.basis, "lingua:confidence")
        self.assertGreaterEqual(decision.confidence, 0.90)
        self.assertGreaterEqual(decision.margin, 0.50)
        self.assertEqual(japanese.language, "ja")
        self.assertEqual(japanese.basis, "script:kana")
        self.assertIsNone(ambiguous_han.language)
        self.assertEqual(ambiguous_han.basis, "script:han-ambiguous")
        self.assertEqual(tagged_japanese_han.language, "ja")
        self.assertEqual(tagged_japanese_han.basis, "metadata")

    @patch('artrend_mag.translation._get_lingua_detector')
    def test_low_detector_confidence_is_not_promoted_to_translation(self, detector):
        detector.return_value.compute_language_confidence_values.return_value = confidence_values(0.62, 0.05)
        decision = detect_language("The Gallery is open to visitors and the public every day")
        self.assertIsNone(decision.language)
        self.assertEqual(decision.basis, 'lingua:low-confidence')
        self.assertEqual(decision.confidence, 0.62)

    def test_missing_detector_keeps_untagged_latin_text_pending(self):
        con = make_connection()
        con.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?)",
            ("event-1", "The art gallery is open to visitors every day", None, None),
        )
        backend = MockBackend()

        with patch("artrend_mag.translation._get_lingua_detector", return_value=None):
            stats = translate_metadata(con, backend=backend)
        row = con.execute("SELECT * FROM metadata_translations").fetchone()

        self.assertEqual(stats["pending"], 1)
        self.assertEqual(row["status"], "pending")
        self.assertIsNone(row["source_lang"])
        self.assertEqual(row["language_basis"], "lingua:unavailable")
        self.assertEqual(row["language_detector_version"], "unavailable")
        self.assertIsNone(row["translation_ko"])
        self.assertEqual(backend.calls, [])

    @patch('artrend_mag.translation._get_lingua_detector')
    def test_duplicate_text_reuses_translation_but_keeps_each_source_record(self, detector):
        detector.return_value.compute_language_confidence_values.return_value = confidence_values()
        con = make_connection()
        con.executemany(
            "INSERT INTO works VALUES (?, ?)",
            [
                ("work-1", "The Gallery is open to visitors and the public every day"),
                ("work-2", "The Gallery is open to visitors and the public every day"),
            ],
        )
        backend = MockBackend()

        stats = translate_metadata(con, backend=backend)
        rows = con.execute(
            "SELECT source_key, translation_ko, source_lang, language_basis, "
            "language_confidence, language_margin, needs_review FROM metadata_translations "
            "WHERE source_table='works' ORDER BY source_key"
        ).fetchall()

        self.assertEqual(stats["translated"], 2)
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual([row["source_key"] for row in rows], ["work-1", "work-2"])
        self.assertEqual(rows[0]["translation_ko"], rows[1]["translation_ko"])
        self.assertTrue(all(row["source_lang"] == "en" for row in rows))
        self.assertTrue(all(row["language_basis"] == "lingua:confidence" for row in rows))
        self.assertTrue(all(row["language_confidence"] >= 0.90 for row in rows))
        self.assertTrue(all(row["language_margin"] >= 0.50 for row in rows))
        self.assertTrue(all(row["needs_review"] for row in rows))

    def test_worklist_batches_unique_eligible_text_and_keeps_each_record(self):
        con = make_connection()
        con.executemany(
            "INSERT INTO articles VALUES (?, ?, 'en', NULL)",
            [
                ("article-1", "A complete first gallery exhibition"),
                ("article-2", "A complete second gallery exhibition"),
                ("article-3", "A complete first gallery exhibition"),
            ],
        )
        backend = BatchMockBackend()

        first = translate_metadata(con, backend=backend, batch_size=100)
        second = translate_metadata(con, backend=backend, batch_size=100)
        rows = con.execute(
            "SELECT source_key, original_text, source_text_hash, translation_ko, status "
            "FROM metadata_translations ORDER BY source_key"
        ).fetchall()

        self.assertEqual(first["translated"], 3)
        self.assertEqual(second["scanned"], 0)
        self.assertEqual(len(backend.batch_calls), 1)
        self.assertEqual(
            backend.batch_calls[0],
            (
                [
                    "A complete first gallery exhibition",
                    "A complete second gallery exhibition",
                ],
                "en",
                "ko",
            ),
        )
        self.assertEqual(
            [row["source_key"] for row in rows], ["article-1", "article-2", "article-3"]
        )
        expected_texts = [
            "A complete first gallery exhibition",
            "A complete second gallery exhibition",
            "A complete first gallery exhibition",
        ]
        self.assertEqual([row["original_text"] for row in rows], expected_texts)
        self.assertEqual(
            [row["source_text_hash"] for row in rows],
            [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in expected_texts],
        )
        self.assertEqual(rows[0]["source_text_hash"], rows[2]["source_text_hash"])
        self.assertEqual(rows[0]["translation_ko"], rows[2]["translation_ko"])
        self.assertTrue(all(row["status"] == "translated" for row in rows))

    def test_batch_failure_isolated_and_preserves_failed_source_record(self):
        con = make_connection()
        con.executemany(
            "INSERT INTO articles VALUES (?, ?, 'en', NULL)",
            [
                ("article-1", "A complete successful title"),
                ("article-2", "A complete failing title"),
                ("article-3", "A complete second successful title"),
            ],
        )
        backend = BatchMockBackend(failed_texts={"A complete failing title"})

        stats = translate_metadata(con, backend=backend)
        rows = con.execute(
            "SELECT source_key, original_text, translation_ko, status, status_reason "
            "FROM metadata_translations ORDER BY source_key"
        ).fetchall()

        self.assertEqual(stats["translated"], 2)
        self.assertEqual(stats["error"], 1)
        self.assertEqual(len(backend.batch_calls), 1)
        self.assertEqual(rows[1]["original_text"], "A complete failing title")
        self.assertEqual(rows[1]["status"], "error")
        self.assertIn("failed: A complete failing title", rows[1]["status_reason"])
        self.assertIsNone(rows[1]["translation_ko"])
        self.assertEqual(rows[0]["status"], "translated")
        self.assertEqual(rows[2]["status"], "translated")

    def test_model_batches_are_capped_at_32_unique_texts(self):
        con = make_connection()
        con.executemany(
            "INSERT INTO articles VALUES (?, ?, 'en', NULL)",
            [
                ("article-{}".format(index), "Unique complete gallery exhibition title {}".format(index))
                for index in range(35)
            ],
        )
        backend = BatchMockBackend()

        stats = translate_metadata(con, backend=backend, batch_size=100)

        self.assertEqual(stats["translated"], 35)
        self.assertEqual([len(call[0]) for call in backend.batch_calls], [32, 3])
        self.assertTrue(all(len(call[0]) <= 32 for call in backend.batch_calls))

    def test_exact_curated_art_title_labels_are_versioned_and_reviewable(self):
        con = make_connection()
        labels = [
            ("work-1", "Untitled", "en"),
            ("work-2", "Sans titre", "fr"),
            ("work-3", "Ohne Titel", "de"),
            ("work-4", "Sin título", "es"),
            ("work-5", "Senza titolo", "it"),
            ("work-6", "Untitled", "en"),
        ]
        con.executemany(
            "INSERT INTO works VALUES (?, ?)",
            [(key, label) for key, label, _ in labels],
        )
        con.execute("INSERT INTO events VALUES (?, ?, ?, ?)", ("event-1", "Untitled II", None, None))

        stats = translate_metadata(con, backend=None)
        rows = con.execute(
            "SELECT source_key, source_lang, language_basis, language_detector_version, "
            "translation_ko, model, model_version, needs_review FROM metadata_translations "
            "WHERE source_table='works' ORDER BY source_key"
        ).fetchall()
        pending = con.execute(
            "SELECT status, translation_ko FROM metadata_translations "
            "WHERE source_table='events'"
        ).fetchone()

        self.assertEqual(stats["translated"], len(labels))
        self.assertEqual(stats["pending"], 1)
        self.assertEqual([row["source_lang"] for row in rows], [lang for _, _, lang in labels])
        self.assertTrue(
            all(row["language_basis"] == "curated:art-title-label" for row in rows)
        )
        self.assertTrue(
            all(row["language_detector_version"] == "curated-art-title-glossary==1" for row in rows)
        )
        self.assertTrue(all(row["translation_ko"] == "무제" for row in rows))
        self.assertTrue(
            all(row["model"] == "curated-art-title-glossary" for row in rows)
        )
        self.assertTrue(all(row["model_version"] == "1" for row in rows))
        self.assertTrue(all(row["needs_review"] for row in rows))
        self.assertEqual(pending["status"], "pending")
        self.assertIsNone(pending["translation_ko"])

    def test_limit_processes_new_titles_before_existing_rows_without_revisiting(self):
        con = make_connection()
        con.executemany(
            "INSERT INTO events VALUES (?, ?, 'en', NULL)",
            [("evt-1", "First title"), ("evt-2", "Second title"), ("evt-3", "Third title")],
        )
        backend = MockBackend()

        first = translate_metadata(con, backend=backend, limit=1, source_table="events")
        second = translate_metadata(con, backend=backend, limit=1, source_table="events")
        done = con.execute(
            "SELECT source_key FROM metadata_translations ORDER BY source_key"
        ).fetchall()

        self.assertEqual(first["scanned"], 1)
        self.assertEqual(second["scanned"], 1)
        self.assertEqual([row[0] for row in done], ["evt-1", "evt-2"])
        self.assertEqual(len(backend.calls), 2)

    def test_changed_model_version_retranslates_identical_source(self):
        con = make_connection()
        con.execute("INSERT INTO events VALUES (?, ?, 'en', NULL)", ("evt", "The New Public Gallery"))
        backend = MockBackend()
        translate_metadata(con, backend=backend)
        backend.model_version = "test-2"

        stats = translate_metadata(con, backend=backend)
        row = con.execute("SELECT * FROM metadata_translations").fetchone()

        self.assertEqual(stats["translated"], 1)
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(row["model_version"], "test-2")

    def test_detector_float_noise_does_not_retranslate(self):
        con = make_connection()
        con.execute("INSERT INTO events VALUES (?, ?, 'en', NULL)", ("evt", "The New Public Gallery"))
        backend = MockBackend()
        translate_metadata(con, backend=backend)
        # Observed 2026-10-29: lingua scores differ in the last float bits between runs.
        con.execute("UPDATE metadata_translations SET language_confidence=language_confidence+1e-15, "
                    "language_margin=language_margin-1e-15")
        stats = translate_metadata(con, backend=backend)
        self.assertEqual((stats["translated"], stats["unchanged"]), (0, 1))
        self.assertEqual(len(backend.calls), 1)

    def test_local_backend_routes_all_korean_output_through_opus(self):
        backend = LocalTranslationBackend.__new__(LocalTranslationBackend)
        backend._korean = Mock()
        backend._korean.translate_many.side_effect = lambda texts: ["KO:" + text for text in texts]
        backend._pivots = Mock()
        backend._pivots.model_version_for.return_value = "1.9"
        backend._pivots.translate_to_english_many.return_value = ["English pivot"]

        english = backend.translate("English title", "en", "ko")
        french = backend.translate("Titre français", "fr", "ko")

        self.assertEqual(english, "KO:English title")
        self.assertEqual(french, "KO:English pivot")
        self.assertEqual(backend._korean.translate_many.call_args_list[0].args, (["English title"],))
        self.assertEqual(backend._korean.translate_many.call_args_list[1].args, (["English pivot"],))
        backend._pivots.translate_to_english_many.assert_called_once_with(
            ["Titre français"], "fr"
        )
        self.assertIsNotNone(backend.model_version_for("en"))
        self.assertIn("argos-fr-en=1.9", backend.model_version_for("fr"))

    def test_local_backend_batches_english_and_pivoted_korean_stages(self):
        backend = LocalTranslationBackend.__new__(LocalTranslationBackend)
        backend._korean = Mock()
        backend._korean.translate_many.side_effect = lambda texts: [
            "한국어 번역문" for _ in texts
        ]
        backend._pivots = Mock()
        backend._pivots.model_version_for.return_value = "1.9"
        backend._pivots.translate_to_english_many.return_value = ["English one", "English two"]

        english = backend.translate_many(["One", "Two"], "en", "ko")
        french = backend.translate_many(["Un", "Deux"], "fr", "ko")

        self.assertEqual(english, ["한국어 번역문", "한국어 번역문"])
        self.assertEqual(french, ["한국어 번역문", "한국어 번역문"])
        self.assertEqual(backend._korean.translate_many.call_args_list[0].args, (["One", "Two"],))
        self.assertEqual(
            backend._korean.translate_many.call_args_list[1].args,
            (["English one", "English two"],),
        )
        backend._pivots.translate_to_english_many.assert_called_once_with(["Un", "Deux"], "fr")

    def test_japanese_inputs_share_one_argos_source_batch_and_one_opus_batch(self):
        pivots, translator = make_argos_pivot_backend()
        backend = LocalTranslationBackend.__new__(LocalTranslationBackend)
        backend._pivots = pivots
        backend._korean = Mock()
        backend._korean.translate_many.side_effect = lambda texts: [
            "한국어 번역문" for _ in texts
        ]

        outputs = backend.translate_many(["一つ目\n二つ目", "三つ目"], "ja", "ko")

        self.assertEqual(outputs, ["한국어 번역문", "한국어 번역문"])
        self.assertEqual(len(translator.calls), 1)
        tokenized, options = translator.calls[0]
        self.assertEqual(tokenized, [["一つ目"], ["二つ目"], ["三つ目"]])
        self.assertEqual(options["target_prefix"], [[">>en<<"]] * 3)
        self.assertTrue(options["replace_unknowns"])
        self.assertEqual(options["max_batch_size"], 32)
        self.assertEqual(options["beam_size"], 4)
        self.assertEqual(options["num_hypotheses"], 1)
        self.assertEqual(options["length_penalty"], 0.2)
        self.assertTrue(options["return_scores"])
        backend._korean.translate_many.assert_called_once_with(
            ["English 一つ目\nEnglish 二つ目", "English 三つ目"]
        )

    def test_argos_pivot_tokenization_and_inference_failures_are_per_record(self):
        pivots, translator = make_argos_pivot_backend(
            encode_error="TOKEN-ERROR", batch_error="INFERENCE-ERROR"
        )
        backend = LocalTranslationBackend.__new__(LocalTranslationBackend)
        backend._pivots = pivots
        backend._korean = Mock()
        backend._korean.translate_many.side_effect = lambda texts: [
            "한국어 번역문" for _ in texts
        ]

        outputs = backend.translate_many(
            ["GOOD-ONE", "TOKEN-ERROR", "INFERENCE-ERROR", "GOOD-TWO"], "ja", "ko"
        )

        self.assertEqual(outputs[0], "한국어 번역문")
        self.assertIsInstance(outputs[1], ValueError)
        self.assertIn("tokenization failed", str(outputs[1]))
        self.assertIsInstance(outputs[2], ValueError)
        self.assertIn("source inference failed", str(outputs[2]))
        self.assertEqual(outputs[3], "한국어 번역문")
        self.assertEqual(len(translator.calls), 4)
        self.assertEqual(translator.calls[0][0], [["GOOD-ONE"], ["INFERENCE-ERROR"], ["GOOD-TWO"]])
        backend._korean.translate_many.assert_called_once_with(
            ["English GOOD-ONE", "English GOOD-TWO"]
        )

    def test_argos_paragraph_batches_are_bounded_to_32(self):
        pivots, translator = make_argos_pivot_backend()
        text = "\n".join("Paragraph {}".format(index) for index in range(33))

        outputs = pivots.translate_to_english_many([text], "ja")

        self.assertEqual(len(translator.calls), 2)
        self.assertEqual([len(call[0]) for call in translator.calls], [32, 1])
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0].count("English Paragraph"), 33)

    def test_opus_unavailable_fails_backend_construction_without_argos_fallback(self):
        with patch(
            "artrend_mag.translation.OpusKoreanBackend",
            side_effect=RuntimeError("OPUS unavailable"),
        ), patch("artrend_mag.translation.ArgosPivotBackend") as argos:
            with self.assertRaisesRegex(BackendUnavailable, "OPUS unavailable"):
                LocalTranslationBackend()
        argos.assert_not_called()

    def test_old_argos_korean_results_are_invalidated_for_opus(self):
        con = make_connection()
        con.execute(
            "INSERT INTO events VALUES (?, ?, 'en', NULL)",
            ("evt", "A complete exhibition title"),
        )
        old_backend = MockBackend()
        old_backend.model_name = "argos-translate-pivot"
        old_backend.model_version = "en-ko=1.1"
        translate_metadata(con, backend=old_backend)

        stats = translate_metadata(
            con, backend=None, unavailable_reason="OPUS model is not installed"
        )
        row = con.execute("SELECT * FROM metadata_translations").fetchone()

        self.assertEqual(stats["pending"], 1)
        self.assertEqual(row["status"], "pending")
        self.assertIsNone(row["translation_ko"])
        self.assertEqual(row["model"], MODEL_NAME)
        self.assertEqual(row["model_version"], OPUS_MODEL_VERSION)


if __name__ == "__main__":
    unittest.main()


class KoreanOutputQualityTests(unittest.TestCase):
    def test_retained_source_names_do_not_reject_korean_translation(self):
        from artrend_mag.translation import _mostly_hangul
        source = "Marshall Brown Projects: Dequindre Civic Academy"
        self.assertTrue(_mostly_hangul("마셜 브라운 프로젝트 : Dequindre Civic Academy", source))
        self.assertTrue(_mostly_hangul("MoMA 소장 : Carrie Mae Weems (1 작품)", "MoMA accession: Carrie Mae Weems (1 work)"))

    def test_invented_or_untranslated_latin_is_still_rejected(self):
        from artrend_mag.translation import _mostly_hangul
        source = "Best Exhibitions Starting in April 2026"
        self.assertFalse(_mostly_hangul("각 Redeemer arianpatienting", source))
        self.assertFalse(_mostly_hangul("Dequindre Civic Academy", "Dequindre Civic Academy"))
        self.assertFalse(_mostly_hangul("Best Exhibitions Starting in April 의", source))


class ReaderKoreanTests(unittest.TestCase):
    def test_polish_turns_polite_endings_into_headline_style(self):
        from artrend_mag.ko_polish import polish
        self.assertEqual(polish("도서관이 약탈품을 돌려줍니다."), "도서관이 약탈품을 돌려준다.")
        self.assertEqual(polish("가치가 있습니다"), "가치가 있다")
        self.assertEqual(polish("4 개월 50 억 엔"), "4개월 50억 엔")
        self.assertEqual(polish("Wan Tuo 와 Ruo Yan 의 역사"), "Wan Tuo와 Ruo Yan의 역사")

    def test_output_that_lost_numbers_or_content_is_not_shown(self):
        from artrend_mag.ko_polish import reader_ko
        self.assertIsNone(reader_ko("ニューヨークが文化に500億円を投じる理由", "뉴욕은 왜 50억 엔을 냈을까", "ja"))
        self.assertIsNone(reader_ko("アートウィーク東京2026の注目展覧会をチェック。6つのバスルートで巡る展覧会ガイド", "아트 위크 도쿄 2026", "ja"))
        self.assertIsNone(reader_ko("Louis Eisner by Addis Goldman", "아디스 골드만의 루이 아이스너", "en"))
        self.assertEqual(reader_ko("Simone Fattal en 2 minutes", "2 분 시몬 Fattal", "fr"), "2분 시몬 Fattal")

    def test_japanese_titles_are_split_and_names_romanized_for_the_pivot(self):
        from artrend_mag.ko_polish import prepare
        segs = [s for s, _ in prepare("故郷を離れて見えてきたもの。ワン・トゥオ×ルオ・ヤンが語る", "ja")]
        self.assertEqual(len(segs), 2)
        self.assertIn("Wan Tuo and Ruo Yan", segs[1])
        self.assertEqual(prepare("釜山ビエンナーレ2026（４）", "ja")[0][0], "Busan Biennale 2026(4)")
