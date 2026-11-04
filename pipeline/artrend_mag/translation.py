"""Translate collected metadata into Korean with local pinned models.

English→Korean uses Helsinki-NLP's pinned OPUS model converted to int8
CTranslate2. Other supported source languages use a pinned local Argos
source→English pivot followed by that same Korean model; no hosted API is used.
The official package index is https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json.
Argos maintainers say model binaries use MIT/CC0, but the package index has no
per-package license field; bundled-component notices should be reviewed before
redistribution: https://github.com/argosopentech/argos-translate/issues/533.
Korean model: official OPUS eng-kor transformer-big, release 2022-07-28,
CC-BY-4.0. The original archive is pinned by SHA-256 in opus_korean.py and
converted with CTranslate2 4.0.0 MarianConverter, preserving separate source
and target vocabularies. The Hugging Face conversion failed real quality
checks and is not used. Downloads live under ``work/translation``. Additional source→English
pivots are pinned in ``PACKAGE_PINS`` to versions in the official Argos index.

Pinned runtime packages are available from PyPI at
https://pypi.org/project/argostranslate/1.9.6/ and
https://pypi.org/project/ctranslate2/4.0.0/; CTranslate2 4.0.0 publishes a
CPython 3.9 macOS ARM64 wheel. Original model conversion uses NumPy and
CTranslate2 directly, not Transformers or pickle checkpoints. The offline detector is
``lingua-language-detector==2.0.2`` (Apache-2.0, Python >=3.8, including a
CPython 3.9 macOS ARM64 wheel, about 74 MB):
https://pypi.org/project/lingua-language-detector/2.0.2/. Upstream license texts:
https://github.com/argosopentech/argos-translate/blob/master/LICENSE and
https://creativecommons.org/publicdomain/zero/1.0/.

Install the optional, pinned runtime and then explicitly download the model:

    python3.9 -m pip install -r requirements-translation.txt
    python3.9 -m artrend_mag.translation install-model --languages en,ja,fr,de,es,pt,pb,it,nl,zh,zt
    python3.9 -m artrend_mag.translation --source-table works --limit 1000
    python3.9 -m artrend_mag.translation availability

Model downloads and conversion occur only for the explicit ``install-model``
command. Model packages and Argos stores are redirected
under ``work/translation``, shared by production and scratch inference runs
after installation. No ``~/.local`` stores or external Snap package directories
are used. ``ARTREND_SCRATCH`` isolates the data DB. Inference is offline and
uses local-files-only tokenization; Argos pivots bypass its optional Stanza
sentence-segmentation path so translation cannot auto-download ancillary data.
For a safe scratch run, use the project DB convention, for example:

    ARTREND_SCRATCH=translation python3.9 -m artrend_mag.translation

Without installed local models or the detector wheel, other eligible records
stay pending. Five exact art-title labels use a versioned curated Korean
glossary; no substring or proper-name matching is done. Missing/contradictory
Latin-language metadata uses Lingua confidence values; classification requires
at least 4 words, 14 letters, confidence >=0.90 and a top-to-runner-up margin
>=0.50. Its detector version, confidence, margin, and language basis are stored
with each record. Clear Hangul/Kana scripts may override contradictory tags;
Han-only text and short proper names stay pending.
Languages are never inferred from venue/geography. Korean originals are left
untranslated.
Titles and existing excerpts of at most 300 characters are considered; no full
article/media bodies or person canonical names are read. Every machine result
is marked for human review. Quality and throughput depend on model, text and
hardware; no project-specific benchmark or quality guarantee is claimed.
Proper names, art terminology, and short ambiguous titles require review.
"""
from __future__ import annotations

from . import ko_polish

import argparse
import copy
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .config import DB_PATH, WORK_ROOT, iso_now, configure_local_temporary_files
from .opus_korean import (
    MODEL_VERSION as OPUS_MODEL_VERSION,
    OpusKoreanBackend,
    direct_network_environment,
    install_model as install_opus_model,
    is_installed as opus_model_is_installed,
)

ARGOS_INDEX = "https://raw.githubusercontent.com/argosopentech/argospm-index/main"
LANGUAGE_DETECTOR_VERSION = "lingua-language-detector==2.0.2;script-rules=1"
LINGUA_MIN_CONFIDENCE = 0.90
LINGUA_MIN_MARGIN = 0.50
LINGUA_MIN_WORDS = 4
LINGUA_MIN_LETTERS = 14


def _installed_language_detector_version() -> Optional[str]:
    try:
        from importlib.metadata import version

        return version("lingua-language-detector")
    except Exception:
        return None


def _argos_storage_root() -> Path:
    """Return the project-local model store; scratch data does not duplicate models."""
    return WORK_ROOT / "work" / "translation"


def configure_argos_paths() -> Path:
    """Pin Argos data/cache locations before importing any Argos module."""
    root = _argos_storage_root().resolve()
    try:
        root.relative_to(WORK_ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError("Argos model/cache path must remain inside the project root") from exc
    data = root / "data"
    cache = root / "cache"
    packages = root / "packages"
    for path in (data, cache, packages):
        try:
            path.resolve().relative_to(WORK_ROOT.resolve())
        except ValueError as exc:
            raise RuntimeError("Argos model/cache path must remain inside the project root") from exc
    os.environ["XDG_DATA_HOME"] = str(data)
    os.environ["XDG_CACHE_HOME"] = str(cache)
    os.environ["ARGOS_PACKAGES_DIR"] = str(packages)
    os.environ["ARGOS_TRANSLATE_PACKAGES_DIR"] = str(packages)
    os.environ["ARGOS_PACKAGE_INDEX"] = ARGOS_INDEX
    os.environ["ARGOS_MODEL_PROVIDER"] = "OPENNMT"
    os.environ["ARGOS_DEVICE_TYPE"] = "cpu"
    os.environ["ARGOS_STANZA_AVAILABLE"] = "true"
    os.environ.pop("SNAP", None)
    os.environ.pop("SNAP_USER_DATA", None)
    return root


# Argos reads these variables and creates its directories during import.
configure_argos_paths()

MODEL_NAME = "opus-mt-tc-big-en-ko-pivot"
TARGET_LANG = "ko"
MAX_EXCERPT_CHARS = 300

# Exact package_version values transcribed from the official Argos index.
# These packages are only source→English pivots; OPUS provides Korean output.
PACKAGE_PINS = {
    ("ja", "en"): "1.1",
    ("fr", "en"): "1.9",
    ("de", "en"): "1.3",
    ("es", "en"): "1.9",
    ("pt", "en"): "1.9",
    ("pb", "en"): "1.9",
    ("it", "en"): "1.0",
    ("nl", "en"): "1.8",
    ("zh", "en"): "1.9",
    ("zt", "en"): "1.9",
    ("ru", "en"): "1.9",
    ("ar", "en"): "1.0",
    ("pl", "en"): "1.9",
    ("sv", "en"): "1.5",
    ("da", "en"): "1.9",
    ("fi", "en"): "1.9",
    ("tr", "en"): "1.5",
    ("uk", "en"): "1.9",
    ("hi", "en"): "1.1",
    ("id", "en"): "1.9",
    ("vi", "en"): "1.9",
    ("th", "en"): "1.9",
}
SUPPORTED_LANGUAGES = frozenset(
    source for source, target in PACKAGE_PINS if target == "en"
).union({"en"})
_LINGUA_DETECTOR = None
_LINGUA_INITIALIZED = False

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS metadata_translations (
    source_table TEXT NOT NULL,
    source_key TEXT NOT NULL,
    source_field TEXT NOT NULL,
    source_text_hash TEXT NOT NULL,
    original_text TEXT NOT NULL,
    translation_ko TEXT,
    model TEXT NOT NULL,
    model_version TEXT NOT NULL,
    declared_lang TEXT,
    source_lang TEXT,
    language_basis TEXT NOT NULL,
    language_detector_version TEXT NOT NULL,
    language_confidence REAL,
    language_margin REAL,
    target_lang TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('translated', 'pending', 'skipped', 'error')),
    status_reason TEXT,
    needs_review INTEGER NOT NULL CHECK (needs_review IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source_table, source_key, source_field),
    CHECK (target_lang = 'ko'),
    CHECK ((status = 'translated' AND translation_ko IS NOT NULL) OR
           (status != 'translated' AND translation_ko IS NULL))
)
"""

# Deliberately enumerated fields: no bodies, evidence payloads, or arbitrary text.
CANDIDATE_SQL = """
SELECT 'events' AS source_table, event_id AS source_key, 'title' AS source_field,
       title AS original_text, title_lang AS source_lang
  FROM events WHERE title IS NOT NULL AND trim(title) != ''
UNION ALL
SELECT 'events', event_id, 'description_excerpt', description_excerpt, title_lang
  FROM events WHERE description_excerpt IS NOT NULL AND trim(description_excerpt) != ''
    AND length(description_excerpt) <= {max_excerpt}
UNION ALL
SELECT 'articles', article_id, 'title', title, lang
  FROM articles WHERE title IS NOT NULL AND trim(title) != ''
UNION ALL
SELECT 'articles', article_id, 'excerpt', excerpt, lang
  FROM articles WHERE excerpt IS NOT NULL AND trim(excerpt) != '' AND length(excerpt) <= {max_excerpt}
UNION ALL
SELECT 'works', work_id, 'title', title, NULL
  FROM works WHERE title IS NOT NULL AND trim(title) != ''
UNION ALL
SELECT 'reports', report_id, 'title', title, NULL
  FROM reports WHERE title IS NOT NULL AND trim(title) != ''
UNION ALL
SELECT 'report_metrics', metric_id, 'excerpt', excerpt, NULL
  FROM report_metrics WHERE excerpt IS NOT NULL AND trim(excerpt) != '' AND length(excerpt) <= {max_excerpt}
""".format(max_excerpt=MAX_EXCERPT_CHARS)


@dataclass(frozen=True)
class Candidate:
    source_table: str
    source_key: str
    source_field: str
    original_text: str
    source_lang: Optional[str]


class BackendUnavailable(RuntimeError):
    """The local translation runtime or required pivot package is unavailable."""


def model_availability() -> dict:
    """Report pinned local-model availability without network or DB writes."""
    configure_argos_paths()
    try:
        import argostranslate.package
        import argostranslate.translate

        installed = {
            (item.from_code, item.to_code): str(item.package_version)
            for item in argostranslate.package.get_installed_packages()
        }
    except Exception:
        installed = {}
    available = opus_model_is_installed()
    available_languages = ["en"] if available else []
    if available_languages:
        available_languages.extend(
            lang
            for lang in sorted(SUPPORTED_LANGUAGES - {"en"})
            if installed.get((lang, "en")) == PACKAGE_PINS[(lang, "en")]
        )
    return {
        "available": available,
        "model": MODEL_NAME,
        "model_version": OPUS_MODEL_VERSION if available else None,
        "source_lang": "en",
        "target_lang": TARGET_LANG,
        "supported_languages": available_languages,
        "language_detector_version": _installed_language_detector_version(),
        "reason": None if available else (
            "Pinned OPUS int8 model is not installed; run "
            "`python -m artrend_mag.translation install-model`."
        ),
    }


class ArgosPivotBackend:
    """Use pinned local Argos source→English packages without Stanza downloads."""

    def __init__(self):
        configure_argos_paths()
        try:
            import argostranslate.package
            import argostranslate.translate
            self._translate_module = argostranslate.translate
            installed_packages = {
                (item.from_code, item.to_code): item
                for item in argostranslate.package.get_installed_packages()
                if PACKAGE_PINS.get((item.from_code, item.to_code))
                == str(item.package_version)
            }
        except Exception as exc:
            raise BackendUnavailable(
                "Argos pivot runtime is unavailable; install requirements-translation.txt: {}"
                .format(exc)
            ) from exc

        self._translations = {}
        for source_lang in sorted(SUPPORTED_LANGUAGES - {"en"}):
            pair = (source_lang, "en")
            pkg = installed_packages.get(pair)
            if pkg is None:
                continue
            # The normal Argos inference path may fetch Stanza resources. Mark
            # this package as pre-segmented; paragraph splitting below mirrors
            # PackageTranslation without invoking any Stanza resources.
            direct_pkg = copy.copy(pkg)
            direct_pkg.type = "sbd"
            from_lang = argostranslate.translate.Language(pkg.from_code, pkg.from_name)
            to_lang = argostranslate.translate.Language(pkg.to_code, pkg.to_name)
            self._translations[source_lang] = argostranslate.translate.PackageTranslation(
                from_lang, to_lang, direct_pkg
            )

    def model_version_for(self, source_lang: str) -> Optional[str]:
        if source_lang not in self._translations:
            return None
        return PACKAGE_PINS[(source_lang, "en")]

    def translate_to_english(self, text: str, source_lang: str) -> str:
        result = self.translate_to_english_many([text], source_lang)[0]
        if isinstance(result, Exception):
            raise result
        return result

    def _translate_token_batch(self, translation, tokenized):
        """Apply Argos's packaged-translation options to already tokenized text."""
        pkg = translation.pkg
        target_prefix = None
        if pkg.target_prefix != "":
            target_prefix = [[pkg.target_prefix]] * len(tokenized)
        options = {
            "target_prefix": target_prefix,
            "replace_unknowns": True,
            "max_batch_size": INFERENCE_BATCH_SIZE,
            "beam_size": 4,
            "num_hypotheses": 1,
            "length_penalty": 0.2,
            "return_scores": True,
        }
        try:
            results = translation.translator.translate_batch(tokenized, **options)
            if len(results) != len(tokenized):
                raise RuntimeError("Argos returned an unexpected batch length")
        except Exception:
            results = []
            for tokens in tokenized:
                try:
                    single_options = dict(options)
                    single_options["target_prefix"] = (
                        [[pkg.target_prefix]] if pkg.target_prefix != "" else None
                    )
                    single = translation.translator.translate_batch(
                        [tokens], **single_options
                    )
                    if len(single) != 1:
                        raise RuntimeError("Argos returned an unexpected result length")
                    results.append(single[0])
                except Exception as exc:
                    results.append(exc)

        outputs = []
        for result in results:
            if isinstance(result, Exception):
                outputs.append(result)
                continue
            try:
                value = pkg.tokenizer.decode(result.hypotheses[0])
                if pkg.target_prefix != "" and value.startswith(pkg.target_prefix):
                    value = value[len(pkg.target_prefix):]
                if value.startswith(" "):
                    value = value[1:]
                outputs.append(value)
            except Exception as exc:
                outputs.append(exc)
        return outputs

    def translate_to_english_many(self, texts, source_lang: str):
        """Batch Argos source→English inference, preserving paragraphs and errors."""
        translation = self._translations.get(source_lang)
        if translation is None:
            return [
                BackendUnavailable(
                    "Pinned Argos package {}→English is not installed".format(source_lang)
                )
                for _ in texts
            ]

        pkg = translation.pkg
        if translation.translator is None:
            import ctranslate2

            translation.translator = ctranslate2.Translator(
                str(pkg.package_path / "model"),
                device=self._translate_module.settings.device,
            )

        outputs = [None] * len(texts)
        pending_tokens = []
        pending_locations = []
        paragraph_outputs = []
        for text_index, text in enumerate(texts):
            try:
                paragraphs = self._translate_module.ITranslation.split_into_paragraphs(text)
            except Exception as exc:
                outputs[text_index] = exc
                continue
            paragraph_outputs.append((text_index, [None] * len(paragraphs)))
            for paragraph_index, paragraph in enumerate(paragraphs):
                try:
                    tokens = pkg.tokenizer.encode(paragraph)
                    pending_tokens.append(tokens)
                    pending_locations.append((len(paragraph_outputs) - 1, paragraph_index))
                except Exception as exc:
                    paragraph_outputs[-1][1][paragraph_index] = exc

        for offset in range(0, len(pending_tokens), INFERENCE_BATCH_SIZE):
            token_batch = pending_tokens[offset:offset + INFERENCE_BATCH_SIZE]
            locations = pending_locations[offset:offset + INFERENCE_BATCH_SIZE]
            translated = self._translate_token_batch(translation, token_batch)
            for location, value in zip(locations, translated):
                paragraph_outputs[location[0]][1][location[1]] = value

        for text_index, paragraphs in paragraph_outputs:
            errors = [value for value in paragraphs if isinstance(value, Exception)]
            if errors:
                outputs[text_index] = errors[0]
                continue
            if any(value is None for value in paragraphs):
                outputs[text_index] = RuntimeError("Argos omitted a paragraph translation")
                continue
            outputs[text_index] = "\n".join(paragraphs).lstrip("\n")
        return outputs


class LocalTranslationBackend:
    """Use OPUS for Korean output and Argos only for non-English pivots."""

    model_name = MODEL_NAME

    def __init__(self):
        try:
            self._korean = OpusKoreanBackend()
        except Exception as exc:
            raise BackendUnavailable(str(exc)) from exc
        try:
            self._pivots = ArgosPivotBackend()
        except BackendUnavailable:
            self._pivots = None

    def model_version_for(self, source_lang: str) -> Optional[str]:
        if source_lang == "en":
            return OPUS_MODEL_VERSION
        if self._pivots is None:
            return None
        pivot_version = self._pivots.model_version_for(source_lang)
        if pivot_version is None:
            return None
        return "argos-{}-en={};{};{}".format(
            source_lang, pivot_version, OPUS_MODEL_VERSION, PIVOT_PREP_VERSION
        )

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        result = self.translate_many([text], source_lang, target_lang)[0]
        if isinstance(result, Exception):
            raise result
        return result

    def translate_many(self, texts, source_lang: str, target_lang: str):
        """Batch the Korean stage while isolating failures in source pivots."""
        if target_lang != TARGET_LANG:
            raise ValueError("Local translation backend only supports Korean output")
        if source_lang == "en":
            return self._korean.translate_many(texts)
        if self._pivots is None or self._pivots.model_version_for(source_lang) is None:
            return [
                BackendUnavailable(
                    "No pinned Argos source→English pivot is installed for {}".format(source_lang)
                )
                for _ in texts
            ]

        # Whole titles lose every clause after the first sentence and mangle katakana names: translate segments.
        plans = [ko_polish.prepare(t, source_lang) for t in texts]
        flat = [seg for plan in plans for seg, _ in plan]
        # Segments of a CJK title that are Latin after term/name preparation go straight to the Korean model.
        cjk_title = [bool(ko_polish.CJK.search(t or "")) for t, plan in zip(texts, plans) for _ in plan]
        direct = [i for i, seg in enumerate(flat) if source_lang in ("ja", "zh", "zt") and cjk_title[i] and not ko_polish.CJK.search(seg)]
        piv = [i for i in range(len(flat)) if i not in set(direct)]
        seg_out = [None] * len(flat)
        if piv:
            for i, r in zip(piv, self._translate_pivot_segments([flat[i] for i in piv], source_lang)):
                seg_out[i] = r
        if direct:
            try:
                for i, r in zip(direct, self._korean.translate_many([flat[i] for i in direct])):
                    seg_out[i] = r
            except Exception as exc:
                for i in direct:
                    seg_out[i] = exc
        outputs, k = [], 0
        for plan in plans:
            got = seg_out[k:k + len(plan)]
            k += len(plan)
            bad = next((g for g in got if isinstance(g, Exception)), None)
            outputs.append(bad if bad is not None else ko_polish.reassemble(got, [j for _, j in plan]))
        return outputs

    def _translate_pivot_segments(self, texts, source_lang: str):
        english = []
        valid_indices = []
        outputs = list(self._pivots.translate_to_english_many(texts, source_lang))
        if len(outputs) != len(texts):
            return [RuntimeError("Argos returned an unexpected batch length") for _ in texts]
        for index, result in enumerate(outputs):
            if isinstance(result, Exception):
                continue
            english.append(result)
            valid_indices.append(index)
        if english:
            try:
                translated = self._korean.translate_many(english)
                if len(translated) != len(valid_indices):
                    raise RuntimeError("Korean model returned an unexpected batch length")
            except Exception:
                translated = []
                for text in english:
                    try:
                        translated.append(self._korean.translate(text))
                    except Exception as exc:
                        translated.append(exc)
            for index, output in zip(valid_indices, translated):
                outputs[index] = output
        return outputs


PIVOT_PREP_VERSION = "segmented-pivot-v1"


def normalize_language(value: Optional[str]) -> Optional[str]:
    """Normalize declared ISO codes without guessing from geography or prose."""
    if not isinstance(value, str):
        return None
    text = value.strip().casefold().replace("_", "-")
    if not text:
        return None
    names = {
        "english": "en",
        "eng": "en",
        "korean": "ko",
        "kor": "ko",
    }
    if text in names:
        return names[text]
    if text in {"pt-br", "pt-pt"}:
        return "pb" if text == "pt-br" else "pt"
    if text in {"zh-hant", "zh-tw", "zh-hk", "zt"}:
        return "zt"
    if text in {"zh-hans", "zh-cn", "zh-sg"}:
        return "zh"
    return text.split("-", 1)[0]


@dataclass(frozen=True)
class LanguageDecision:
    language: Optional[str]
    basis: str
    confidence: Optional[float]
    margin: Optional[float]
    curated_translation: Optional[str] = None


_CURATED_ART_TITLE_LABELS = {
    "untitled": ("en", "무제"),
    "sans titre": ("fr", "무제"),
    "ohne titel": ("de", "무제"),
    "sin título": ("es", "무제"),
    "senza titolo": ("it", "무제"),
}


def _get_lingua_detector():
    global _LINGUA_DETECTOR, _LINGUA_INITIALIZED
    if _LINGUA_INITIALIZED:
        return _LINGUA_DETECTOR
    _LINGUA_INITIALIZED = True
    try:
        if _installed_language_detector_version() != "2.0.2":
            return None
        from lingua import LanguageDetectorBuilder

        _LINGUA_DETECTOR = LanguageDetectorBuilder.from_all_languages().build()
    except Exception:
        _LINGUA_DETECTOR = None
    return _LINGUA_DETECTOR


def detect_language(text: str, declared_lang: Optional[str] = None) -> LanguageDecision:
    """Use explicit tags/scripts first and high-confidence offline Lingua results."""
    declared = normalize_language(declared_lang)
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return LanguageDecision(
            declared, "metadata" if declared else "unknown", 1.0 if declared else None, None
        )

    hangul = sum("\uac00" <= char <= "\ud7a3" for char in letters)
    kana = sum("\u3040" <= char <= "\u30ff" for char in letters)
    han = sum("\u3400" <= char <= "\u9fff" for char in letters)
    if hangul and hangul * 2 >= len(letters):
        return LanguageDecision("ko", "script:hangul", 1.0, None)
    if kana >= 2 and (kana + han) * 2 >= len(letters):
        return LanguageDecision("ja", "script:kana", 1.0, None)

    # Han-only text does not reliably distinguish Japanese, Simplified Chinese,
    # or Traditional Chinese. Even an English parser tag cannot resolve that.
    if han and not kana and han * 2 >= len(letters):
        if declared in {"ja", "zh", "zt"}:
            return LanguageDecision(declared, "metadata", 1.0, None)
        return LanguageDecision(None, "script:han-ambiguous", None, None)
    curated = _CURATED_ART_TITLE_LABELS.get(text.strip().casefold())
    if curated is not None:
        return LanguageDecision(curated[0], "curated:art-title-label", 1.0, None, curated[1])
    if declared:
        return LanguageDecision(declared, "metadata", 1.0, None)

    tokens = re.findall(r"[^\W\d_]+", text, flags=re.UNICODE)
    if len(tokens) < LINGUA_MIN_WORDS or len(letters) < LINGUA_MIN_LETTERS:
        return LanguageDecision(None, "lingua:insufficient-text", None, None)
    detector = _get_lingua_detector()
    if detector is None:
        return LanguageDecision(None, "lingua:unavailable", None, None)
    try:
        confidence_values = detector.compute_language_confidence_values(text)
        if not confidence_values:
            return LanguageDecision(None, "lingua:no-result", None, None)
        best = confidence_values[0]
        second_value = confidence_values[1].value if len(confidence_values) > 1 else 0.0
        confidence = float(best.value)
        margin = confidence - float(second_value)
        language = best.language.iso_code_639_1
        code = language.name.casefold() if language is not None else None
    except Exception:
        return LanguageDecision(None, "lingua:error", None, None)
    if confidence < LINGUA_MIN_CONFIDENCE or margin < LINGUA_MIN_MARGIN:
        return LanguageDecision(None, "lingua:low-confidence", confidence, margin)
    if code is None:
        return LanguageDecision(None, "lingua:unsupported-code", confidence, margin)
    return LanguageDecision(code, "lingua:confidence", confidence, margin)


def _mostly_hangul(text: str, source: str | None = None) -> bool:
    """Require Hangul for at least half of letters not copied verbatim from the source.

    Capitalized names retained exactly from the original are not counted against the output;
    retained lowercase words and invented non-Korean tokens still are."""
    if source:
        copied = set(re.findall(r"[^\W\d_]+", source))
        text = " ".join(token for token in re.findall(r"[^\W\d_]+", text)
                        if token not in copied or not token[0].isupper())
    hangul = sum(1 for char in text if "\uac00" <= char <= "\ud7a3")
    letters = sum(1 for char in text if char.isalpha())
    return hangul > 0 and hangul * 2 >= max(1, letters)


def _same_score(stored: Optional[float], current: Optional[float]) -> bool:
    """Detector scores vary in the last float bits between runs; treat that noise as unchanged."""
    if stored is None or current is None:
        return stored is current
    return math.isclose(stored, current, rel_tol=0.0, abs_tol=1e-9)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ensure_translation_table(con: sqlite3.Connection) -> None:
    con.execute(CREATE_TABLE_SQL)
    con.execute(
        "CREATE INDEX IF NOT EXISTS metadata_translations_memo_idx ON "
        "metadata_translations(source_text_hash, source_lang, target_lang, model, model_version, status)"
    )


def _source_tables_present(con: sqlite3.Connection) -> None:
    present = {
        row[0]
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    required = {"events", "articles", "works", "reports", "report_metrics"}
    missing = sorted(required - present)
    if missing:
        raise RuntimeError(
            "Database is missing source tables: {}. Initialize the ARTREND database "
            "before running metadata translation.".format(", ".join(missing))
        )


def _planned_model_version(source_lang: Optional[str]) -> Optional[str]:
    if source_lang == "en":
        return OPUS_MODEL_VERSION
    if source_lang in SUPPORTED_LANGUAGES:
        return "argos-{}-en={};{};{}".format(
            source_lang,
            PACKAGE_PINS[(source_lang, "en")],
            OPUS_MODEL_VERSION,
            PIVOT_PREP_VERSION,
        )
    return None


def _backend_signature(backend, source_lang: Optional[str]):
    if backend is None or source_lang is None:
        return None
    version_for = getattr(backend, "model_version_for", None)
    if callable(version_for):
        version = version_for(source_lang)
    else:
        version = getattr(backend, "model_version", None)
    if not version:
        return None
    return getattr(backend, "model_name", MODEL_NAME), str(version)


def _decision_model_signature(backend, decision: LanguageDecision):
    if decision.curated_translation is not None:
        return "curated-art-title-glossary", "1"
    return _backend_signature(backend, decision.language)


def _decision_detector_version(decision: LanguageDecision) -> str:
    if decision.curated_translation is not None:
        return "curated-art-title-glossary==1"
    if decision.basis in {"lingua:unavailable", "lingua:error"}:
        return "unavailable"
    return LANGUAGE_DETECTOR_VERSION


def _save_record(
    con: sqlite3.Connection,
    candidate: Candidate,
    source_hash: str,
    source_lang: Optional[str],
    language_basis: str,
    language_detector_version: str,
    language_confidence: Optional[float],
    language_margin: Optional[float],
    status: str,
    reason: Optional[str],
    translation: Optional[str],
    model: str,
    model_version: str,
    needs_review: bool,
) -> bool:
    """Store the current source version; return whether its row changed."""
    old = con.execute(
        "SELECT source_text_hash, original_text, translation_ko, model, model_version, "
        "declared_lang, source_lang, language_basis, language_detector_version, "
        "language_confidence, language_margin, target_lang, "
        "status, status_reason, needs_review "
        "FROM metadata_translations WHERE source_table=? AND source_key=? AND source_field=?",
        (candidate.source_table, candidate.source_key, candidate.source_field),
    ).fetchone()
    values = (
        source_hash,
        candidate.original_text,
        translation,
        model,
        model_version,
        candidate.source_lang,
        source_lang,
        language_basis,
        language_detector_version,
        language_confidence,
        language_margin,
        TARGET_LANG,
        status,
        reason,
        int(needs_review),
    )
    if old is not None and tuple(old) == values:
        return False

    now = iso_now()
    con.execute(
        "INSERT INTO metadata_translations "
        "(source_table, source_key, source_field, source_text_hash, original_text, "
        "translation_ko, model, model_version, declared_lang, source_lang, "
        "language_basis, language_detector_version, language_confidence, language_margin, "
        "target_lang, status, "
        "status_reason, needs_review, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(source_table, source_key, source_field) DO UPDATE SET "
        "source_text_hash=excluded.source_text_hash, original_text=excluded.original_text, "
        "translation_ko=excluded.translation_ko, model=excluded.model, "
        "model_version=excluded.model_version, declared_lang=excluded.declared_lang, "
        "source_lang=excluded.source_lang, language_basis=excluded.language_basis, "
        "language_detector_version=excluded.language_detector_version, "
        "language_confidence=excluded.language_confidence, "
        "language_margin=excluded.language_margin, "
        "target_lang=excluded.target_lang, status=excluded.status, "
        "status_reason=excluded.status_reason, needs_review=excluded.needs_review, "
        "updated_at=excluded.updated_at",
        (
            candidate.source_table,
            candidate.source_key,
            candidate.source_field,
            *values,
            now,
            now,
        ),
    )
    return True


INFERENCE_BATCH_SIZE = 32


def _backend_translate_many(backend, texts, source_lang: str) -> list:
    """Use a backend batch API when available, isolating failures per text."""
    translate_many = getattr(backend, "translate_many", None)
    if callable(translate_many):
        try:
            results = list(translate_many(texts, source_lang, TARGET_LANG))
            if len(results) == len(texts):
                return results
            batch_error = RuntimeError("translation backend returned an unexpected batch length")
        except Exception as exc:
            batch_error = exc
    else:
        batch_error = None

    results = []
    translate = getattr(backend, "translate", None)
    for text in texts:
        if not callable(translate):
            results.append(batch_error or BackendUnavailable("translation backend has no translate method"))
            continue
        try:
            results.append(translate(text, source_lang, TARGET_LANG))
        except Exception as exc:
            results.append(exc)
    return results


def _process_candidates(
    con: sqlite3.Connection,
    candidates,
    backend,
    unavailable_reason: Optional[str],
    decisions,
    translation_cache: dict,
) -> list:
    """Process records together so local model inference can use bounded batches."""
    states = []
    inference = {}
    looked_up = set()

    for candidate, decision in zip(candidates, decisions):
        source_hash = _text_hash(candidate.original_text)
        source_lang = decision.language
        old = con.execute(
            "SELECT source_text_hash, declared_lang, source_lang, language_basis, "
            "language_detector_version, language_confidence, language_margin, "
            "target_lang, model, model_version, status "
            "FROM metadata_translations "
            "WHERE source_table=? AND source_key=? AND source_field=?",
            (candidate.source_table, candidate.source_key, candidate.source_field),
        ).fetchone()
        signature = _decision_model_signature(backend, decision)
        if (
            old is not None
            and old["source_text_hash"] == source_hash
            and old["declared_lang"] == candidate.source_lang
            and old["source_lang"] == source_lang
            and old["language_basis"] == decision.basis
            and old["language_detector_version"] == _decision_detector_version(decision)
            and _same_score(old["language_confidence"], decision.confidence)
            and _same_score(old["language_margin"], decision.margin)
            and old["target_lang"] == TARGET_LANG
            and old["status"] == "translated"
            and signature is not None
            and old["model"] == signature[0]
            and old["model_version"] == signature[1]
        ):
            states.append({"outcome": "unchanged"})
            continue

        model_name = signature[0] if signature else MODEL_NAME
        model_version = (
            signature[1]
            if signature
            else _planned_model_version(source_lang) or "not-installed-or-unsupported"
        )
        state = {
            "candidate": candidate,
            "decision": decision,
            "source_hash": source_hash,
            "source_lang": source_lang,
            "model": model_name,
            "model_version": model_version,
            "translation": None,
            "status": None,
            "reason": None,
            "needs_review": True,
        }
        states.append(state)

        if source_lang == "ko" or decision.basis == "script:hangul":
            state.update(
                status="skipped",
                reason="source text is already Korean or predominantly Hangul",
                needs_review=False,
            )
        elif decision.curated_translation is not None:
            state.update(status="translated", translation=decision.curated_translation)
        elif source_lang is None:
            state.update(
                status="pending",
                reason="source language is not recorded or local detection is not confident",
            )
        elif source_lang not in SUPPORTED_LANGUAGES:
            state.update(
                status="pending",
                reason="unsupported source language: {}; no pinned local pivot is configured".format(
                    source_lang
                ),
            )
        elif signature is None:
            state.update(
                status="pending",
                reason=unavailable_reason
                or "local pivot model is not installed for {}→Korean".format(source_lang),
            )
        else:
            cache_key = (source_hash, source_lang, TARGET_LANG, signature[0], signature[1])
            state["cache_key"] = cache_key
            cached = translation_cache.get(cache_key)
            if cached is None and cache_key not in looked_up:
                row = con.execute(
                    "SELECT translation_ko FROM metadata_translations "
                    "WHERE source_text_hash=? AND source_lang=? AND target_lang=? "
                    "AND model=? AND model_version=? AND status='translated' "
                    "AND translation_ko IS NOT NULL LIMIT 1",
                    cache_key,
                ).fetchone()
                cached = row["translation_ko"] if row is not None else None
                if cached is not None:
                    translation_cache[cache_key] = cached
                looked_up.add(cache_key)
            if cached is not None:
                state["translation"] = cached
            else:
                key_states = inference.setdefault(source_lang, {})
                key_states.setdefault(cache_key, {"text": candidate.original_text, "states": []})
                key_states[cache_key]["states"].append(state)

    for source_lang, pending in inference.items():
        items = list(pending.items())
        for offset in range(0, len(items), INFERENCE_BATCH_SIZE):
            group = items[offset:offset + INFERENCE_BATCH_SIZE]
            outputs = _backend_translate_many(
                backend, [item[1]["text"] for item in group], source_lang
            )
            for (_, item), output in zip(group, outputs):
                for state in item["states"]:
                    state["translation"] = output

    outcomes = []
    for state in states:
        if state.get("outcome") == "unchanged":
            outcomes.append("unchanged")
            continue
        candidate = state["candidate"]
        decision = state["decision"]
        status = state["status"]
        reason = state["reason"]
        translation = state["translation"]
        if status is None:
            try:
                if isinstance(translation, Exception):
                    raise translation
                if not isinstance(translation, str) or not translation.strip():
                    raise ValueError("model returned empty or non-text output")
                translation = translation.strip()
                if translation == candidate.original_text.strip():
                    raise ValueError("model returned the original text without translation")
                if not _mostly_hangul(translation, candidate.original_text):
                    raise ValueError("model output contains no substantial Korean text")
                translation_cache[state["cache_key"]] = translation
                status = "translated"
                reason = None
            except Exception as exc:
                status = "error"
                reason = "{}: {}".format(type(exc).__name__, str(exc))[:1000]
                translation = None
        elif status == "translated" and not decision.curated_translation:
            translation = translation.strip()

        changed = _save_record(
            con,
            candidate,
            state["source_hash"],
            state["source_lang"],
            decision.basis,
            _decision_detector_version(decision),
            decision.confidence,
            decision.margin,
            status,
            reason,
            translation if status == "translated" else None,
            state["model"],
            state["model_version"],
            state["needs_review"],
        )
        outcomes.append(status if changed else "unchanged")
    return outcomes


def translate_metadata(
    con: sqlite3.Connection,
    backend=None,
    batch_size: int = 100,
    unavailable_reason: Optional[str] = None,
    limit: Optional[int] = None,
    source_table: Optional[str] = None,
    progress_callback: Optional[Callable[[dict], None]] = None,
    progress_every: int = 1000,
) -> dict:
    """Translate eligible metadata in bounded batches, prioritizing new titles."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if progress_every < 1:
        raise ValueError("progress_every must be positive")
    valid_tables = {"events", "articles", "works", "reports", "report_metrics"}
    if source_table is not None and source_table not in valid_tables:
        raise ValueError("unsupported source table: {}".format(source_table))
    _source_tables_present(con)
    ensure_translation_table(con)
    decision_cache = {}

    def decision_for(text, declared):
        key = (text, declared)
        if key not in decision_cache:
            decision_cache[key] = detect_language(text, declared)
        return decision_cache[key]

    def effective_language(text, declared):
        return decision_for(text, declared).language

    def language_basis(text, declared):
        return decision_for(text, declared).basis

    def language_confidence(text, declared):
        return decision_for(text, declared).confidence

    def language_margin(text, declared):
        return decision_for(text, declared).margin

    def detector_version(text, declared):
        return _decision_detector_version(decision_for(text, declared))

    def expected_model(text, declared):
        return _decision_model_signature(backend, decision_for(text, declared))

    def stored_output_model(text, declared):
        decision = decision_for(text, declared)
        signature = _decision_model_signature(backend, decision)
        if signature is not None:
            return signature
        if decision.curated_translation is not None:
            return "curated-art-title-glossary", "1"
        planned_version = _planned_model_version(decision.language)
        if planned_version is None:
            return None
        return MODEL_NAME, planned_version

    con.create_function("translation_hash", 1, _text_hash, deterministic=True)
    con.create_function("translation_language", 2, effective_language, deterministic=True)
    con.create_function("translation_language_basis", 2, language_basis, deterministic=True)
    con.create_function(
        "translation_language_confidence", 2, language_confidence, deterministic=True
    )
    con.create_function("translation_language_margin", 2, language_margin, deterministic=True)
    con.create_function(
        "translation_detector_version", 2, detector_version, deterministic=True
    )
    con.create_function(
        "translation_expected_model", 2,
        lambda text, declared: (expected_model(text, declared) or (None, None))[0],
        deterministic=True,
    )
    con.create_function(
        "translation_expected_version", 2,
        lambda text, declared: (expected_model(text, declared) or (None, None))[1],
        deterministic=True,
    )
    con.create_function(
        "translation_stored_model", 2,
        lambda text, declared: (stored_output_model(text, declared) or (None, None))[0],
        deterministic=True,
    )
    con.create_function(
        "translation_stored_version", 2,
        lambda text, declared: (stored_output_model(text, declared) or (None, None))[1],
        deterministic=True,
    )
    query = """
    WITH candidates AS ({candidate_sql}), checked AS (
        SELECT c.*,
               CASE
                 WHEN t.source_table IS NULL THEN 0
                 WHEN t.source_text_hash != translation_hash(c.original_text) THEN 0
                 WHEN COALESCE(t.declared_lang, '') != COALESCE(c.source_lang, '') THEN 0
                 WHEN COALESCE(t.source_lang, '') !=
                      COALESCE(translation_language(c.original_text, c.source_lang), '') THEN 0
                 WHEN t.language_basis !=
                      translation_language_basis(c.original_text, c.source_lang) THEN 0
                 WHEN t.language_detector_version !=
                      translation_detector_version(c.original_text, c.source_lang) THEN 0
                 WHEN COALESCE(t.language_confidence, -1.0) !=
                      COALESCE(translation_language_confidence(c.original_text, c.source_lang), -1.0)
                      THEN 0
                 WHEN COALESCE(t.language_margin, -1.0) !=
                      COALESCE(translation_language_margin(c.original_text, c.source_lang), -1.0)
                      THEN 0
                 WHEN t.status = 'error' THEN 1
                 WHEN t.status = 'pending' AND
                      translation_expected_model(c.original_text, c.source_lang) IS NOT NULL THEN 0
                 WHEN t.status = 'translated' AND
                      translation_stored_model(c.original_text, c.source_lang) IS NOT NULL AND
                      (t.model != translation_stored_model(c.original_text, c.source_lang) OR
                       t.model_version != translation_stored_version(c.original_text, c.source_lang) OR
                       t.target_lang != 'ko') THEN 0
                 ELSE 2
               END AS work_priority
          FROM candidates c
          LEFT JOIN metadata_translations t
            ON t.source_table=c.source_table AND t.source_key=c.source_key
           AND t.source_field=c.source_field
    )
    SELECT * FROM checked
     WHERE work_priority < 2 AND (? IS NULL OR source_table = ?)
     ORDER BY work_priority,
              CASE WHEN source_field = 'title' THEN 0 ELSE 1 END,
              source_table, source_key, source_field
    """.format(candidate_sql=CANDIDATE_SQL)
    params = [source_table, source_table]
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    con.execute("DROP TABLE IF EXISTS temp._artrend_translation_worklist")
    con.execute(
        "CREATE TEMP TABLE _artrend_translation_worklist AS " + query,
        params,
    )
    cursor = con.execute(
        "SELECT * FROM temp._artrend_translation_worklist "
        "ORDER BY work_priority, CASE WHEN source_field='title' THEN 0 ELSE 1 END, "
        "source_table, source_key, source_field"
    )
    stats = {"scanned": 0, "translated": 0, "pending": 0, "skipped": 0, "error": 0, "unchanged": 0}
    translation_cache = {}
    last_progress = 0
    while True:
        batch = cursor.fetchmany(batch_size)
        if not batch:
            break
        candidates = []
        decisions = []
        for row in batch:
            candidates.append(Candidate(
                source_table=row["source_table"],
                source_key=str(row["source_key"]),
                source_field=row["source_field"],
                original_text=row["original_text"],
                source_lang=row["source_lang"],
            ))
            decisions.append(decision_for(row["original_text"], row["source_lang"]))
        outcomes = _process_candidates(
            con,
            candidates,
            backend,
            unavailable_reason,
            decisions,
            translation_cache,
        )
        for outcome in outcomes:
            stats["scanned"] += 1
            stats[outcome] += 1
        con.commit()
        if progress_callback is not None and stats["scanned"] - last_progress >= progress_every:
            progress_callback(dict(stats))
            last_progress = stats["scanned"]
    con.execute("DROP TABLE temp._artrend_translation_worklist")
    return stats


def parse_languages(value: str):
    """Parse and validate explicit source languages requested for local pivots."""
    languages = sorted({normalize_language(part) for part in value.split(",") if part.strip()})
    unsupported = sorted(set(languages) - SUPPORTED_LANGUAGES - {"ko"})
    if unsupported:
        raise ValueError(
            "no pinned local Argos pivot for: {} (supported: {})".format(
                ", ".join(unsupported), ", ".join(sorted(SUPPORTED_LANGUAGES))
            )
        )
    if not languages:
        raise ValueError("--languages must contain at least one language code")
    return languages


def install_model(languages=("en",)) -> None:
    """Download/convert OPUS and explicitly install requested Argos pivots."""
    languages = parse_languages(",".join(languages) if not isinstance(languages, str) else languages)
    try:
        install_opus_model()
    except Exception as exc:
        raise BackendUnavailable("OPUS model installation failed: {}".format(exc)) from exc
    print("Installed {}".format(OPUS_MODEL_VERSION))

    pivot_languages = [lang for lang in languages if lang not in {"en", "ko"}]
    if not pivot_languages:
        return
    configure_argos_paths()
    try:
        import argostranslate.package
    except Exception as exc:
        raise BackendUnavailable(
            "Argos runtime is unavailable; first install "
            "`python -m pip install -r requirements-translation.txt`."
        ) from exc

    with direct_network_environment():
        argostranslate.package.update_package_index()
        available = argostranslate.package.get_available_packages()
        installed = {
            (item.from_code, item.to_code): str(item.package_version)
            for item in argostranslate.package.get_installed_packages()
        }
    requirements = {(lang, "en") for lang in pivot_languages}
    for from_code, to_code in sorted(requirements):
        expected = PACKAGE_PINS[(from_code, to_code)]
        if installed.get((from_code, to_code)) == expected:
            print("Already installed {}→{} v{}".format(from_code, to_code, expected))
            continue
        package = next(
            (
                item
                for item in available
                if item.from_code == from_code
                and item.to_code == to_code
                and str(item.package_version) == expected
            ),
            None,
        )
        if package is None:
            raise BackendUnavailable(
                "Official Argos index lacks pinned package {}→{} v{}".format(
                    from_code, to_code, expected
                )
            )
        with direct_network_environment():
            model_path = package.download()
        argostranslate.package.install_from_path(model_path)
        print("Installed {}→{} v{}".format(from_code, to_code, expected))


def _connect(path: Optional[Path] = None) -> sqlite3.Connection:
    path = path or DB_PATH
    try:
        path.resolve().relative_to(WORK_ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError("Translation database must remain inside the project root") from exc
    if not path.is_file():
        raise RuntimeError(
            "ARTREND database not found at {}. Initialize the database first, or "
            "set ARTREND_SCRATCH=<task-id> to use its configured scratch database.".format(path)
        )
    con = sqlite3.connect(str(path), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=120000")
    return con


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m artrend_mag.translation",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--limit", type=int, help="maximum eligible records to process this run")
    parser.add_argument(
        "--progress-every",
        type=int,
        default=1000,
        help="emit a JSON progress line every N processed records (default: 1000)",
    )
    parser.add_argument(
        "--source-table",
        choices=("events", "articles", "works", "reports", "report_metrics"),
        help="restrict processing to one source table",
    )
    commands = parser.add_subparsers(dest="command")
    install_parser = commands.add_parser(
        "install-model", help="explicitly download/convert the pinned Korean model and pivots"
    )
    install_parser.add_argument(
        "--languages",
        default="en",
        help="comma-separated source ISO codes; non-English languages need X→English pivots (default: en)",
    )
    commands.add_parser("availability", help="report locally installed model languages (no network)")
    args = parser.parse_args(argv)
    configure_local_temporary_files()

    if args.command == "install-model":
        try:
            install_model(args.languages)
        except (BackendUnavailable, ValueError) as exc:
            parser.error(str(exc))
        return 0
    if args.command == "availability":
        print(json.dumps(model_availability(), ensure_ascii=False, sort_keys=True))
        return 0
    try:
        backend = LocalTranslationBackend()
        unavailable_reason = None
    except BackendUnavailable as exc:
        backend = None
        unavailable_reason = str(exc)
        print("Local translation unavailable: {}".format(exc), file=sys.stderr)

    con = _connect()
    try:
        stats = translate_metadata(
            con,
            backend=backend,
            batch_size=args.batch_size,
            unavailable_reason=unavailable_reason,
            limit=args.limit,
            source_table=args.source_table,
            progress_callback=lambda progress: print(
                json.dumps({"type": "translation_progress", **progress}, ensure_ascii=False),
                flush=True,
            ),
            progress_every=args.progress_every,
        )
    finally:
        con.close()
    print(
        json.dumps(
            {"type": "translation_complete", "db_path": str(DB_PATH), **stats},
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
