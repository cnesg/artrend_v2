"""Pinned original OPUS Marian model; preserve its separate source/target vocabularies.

The Hugging Face conversion was rejected after both native Transformers and
CTranslate2 produced incoherent results. The official original checkpoint and
SentencePiece models produce coherent Korean in the recorded smoke checks.
Only explicit install_model() uses the network. No downloaded scripts execute.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

from .config import WORK_ROOT

MODEL_NAME = 'opus-tc-big-original-en-ko'
MODEL_ID = MODEL_NAME
MODEL_REVISION = '2022-07-28'
MODEL_URL = 'https://object.pouta.csc.fi/Tatoeba-MT-models/eng-kor/opusTCv20210807-sepvoc_transformer-big_2022-07-28.zip'
ARCHIVE_SHA256 = '41f771fa28e864428dd7589992867b2b6dfa402f1191670e818e019dddfceef7'
QUANTIZATION = 'int8'
CONVERTER_VERSION = 'ctranslate2==4.0.0;MarianConverter;separate-vocabs-v1'
MODEL_VERSION = f'{MODEL_NAME}@{ARCHIVE_SHA256};{CONVERTER_VERSION};{QUANTIZATION}'
MODEL_STORE = WORK_ROOT / 'work' / 'translation' / 'original_opus'
MODEL_DIR = MODEL_STORE / 'ct2-int8'
MANIFEST_NAME = 'artrend_model.json'
BASE = 'opusTCv20210807-sepvoc.spm32k-spm32k'
MODEL_FILE = BASE + '.transformer-big.model1.npz.best-perplexity.npz'
MEMBERS = (MODEL_FILE, BASE + '.src.vocab', BASE + '.trg.vocab', 'source.spm', 'target.spm', 'LICENSE')

@contextmanager
def direct_network_environment():
    names = ('http_proxy', 'https_proxy', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')
    saved = {name: os.environ.pop(name) for name in names if name in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def _sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def _manifest():
    return dict(model_id=MODEL_ID, revision=MODEL_REVISION, source_url=MODEL_URL,
                source_sha256=ARCHIVE_SHA256, converter=CONVERTER_VERSION,
                quantization=QUANTIZATION, license='CC-BY-4.0')


def is_installed():
    try:
        data = json.loads((MODEL_DIR / MANIFEST_NAME).read_text(encoding='utf-8'))
        if any(data.get(key) != value for key, value in _manifest().items()):
            return False
        return all((MODEL_DIR / name).is_file() for name in ('model.bin', 'source.spm', 'target.spm'))
    except (OSError, ValueError):
        return False


def _download_archive(path):
    import requests
    partial = path.with_suffix('.part')
    digest = hashlib.sha256()
    total = 0
    with requests.Session() as session:
        session.trust_env = False
        with session.get(MODEL_URL, stream=True, timeout=(20, 120)) as response:
            response.raise_for_status()
            with partial.open('wb') as stream:
                for chunk in response.iter_content(1024 * 1024):
                    total += len(chunk)
                    if total > 1_500_000_000:
                        raise RuntimeError('Original model archive exceeds the 1.5 GB limit')
                    digest.update(chunk)
                    stream.write(chunk)
    if digest.hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError('Original model archive SHA-256 does not match the pinned checkpoint')
    os.replace(str(partial), str(path))


def _vocabulary_yaml(source, destination):
    # Original vocab files are one token per line, in embedding-index order.
    # MarianConverter expects YAML token:index files. Never sort the tokens.
    tokens = source.read_text(encoding='utf-8').splitlines()
    if len(tokens) != len(set(tokens)) or not tokens:
        raise RuntimeError('Original vocabulary contains duplicate tokens or is empty')
    destination.write_text(''.join(json.dumps(token, ensure_ascii=False) + ': ' + str(index) + '\n'
                                   for index, token in enumerate(tokens)), encoding='utf-8')


def install_model():
    if is_installed():
        return
    for path in (MODEL_STORE, MODEL_DIR):
        path.resolve().relative_to(WORK_ROOT.resolve())
    MODEL_STORE.mkdir(parents=True, exist_ok=True)
    archive = MODEL_STORE / 'original.zip'
    if not archive.is_file() or _sha(archive) != ARCHIVE_SHA256:
        _download_archive(archive)
    from ctranslate2.converters import MarianConverter
    with tempfile.TemporaryDirectory(prefix='conversion-', dir=str(MODEL_STORE)) as directory:
        stage = Path(directory)
        with zipfile.ZipFile(archive) as package:
            for name in MEMBERS:
                # Only exact, pinned flat data filenames are read, never extractall/scripts.
                with package.open(name) as src, (stage / name).open('wb') as dst:
                    shutil.copyfileobj(src, dst)
        vocabs = []
        for side in ('src', 'trg'):
            output = stage / (side + '.yml')
            _vocabulary_yaml(stage / (BASE + '.' + side + '.vocab'), output)
            vocabs.append(str(output))
        output = stage / 'converted'
        MarianConverter(str(stage / MODEL_FILE), vocabs).convert(str(output), quantization=QUANTIZATION)
        for name in ('source.spm', 'target.spm', 'LICENSE'):
            shutil.copyfile(stage / name, output / name)
        manifest = _manifest()
        manifest['files'] = {path.name: _sha(path) for path in output.iterdir() if path.is_file()}
        (output / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        # Replace only this installer's managed model cache, retaining rollback until success.
        backup = stage / 'previous'
        if MODEL_DIR.exists():
            os.replace(str(MODEL_DIR), str(backup))
        try:
            os.replace(str(output), str(MODEL_DIR))
        except Exception:
            if backup.exists():
                os.replace(str(backup), str(MODEL_DIR))
            raise


class OpusKoreanBackend:
    model_name = MODEL_NAME
    model_version = MODEL_VERSION
    batch_size = 32

    def __init__(self, translator=None, source_tokenizer=None, target_tokenizer=None):
        if not is_installed():
            raise RuntimeError('Pinned original OPUS model is not installed; run python -m artrend_mag.translation install-model')
        if translator is None:
            import ctranslate2
            translator = ctranslate2.Translator(str(MODEL_DIR), device='cpu', compute_type=QUANTIZATION)
        if source_tokenizer is None or target_tokenizer is None:
            import sentencepiece
            source_tokenizer = source_tokenizer or sentencepiece.SentencePieceProcessor(model_file=str(MODEL_DIR / 'source.spm'))
            target_tokenizer = target_tokenizer or sentencepiece.SentencePieceProcessor(model_file=str(MODEL_DIR / 'target.spm'))
        self._translator = translator
        self._source = source_tokenizer
        self._target = target_tokenizer

    def translate(self, text):
        result = self.translate_many([text])[0]
        if isinstance(result, Exception):
            raise result
        return result

    def translate_many(self, texts):
        """Translate a bounded batch and isolate tokenization/decoding failures."""
        if len(texts) > self.batch_size:
            raise ValueError("translation batch exceeds {} texts".format(self.batch_size))
        outputs = [None] * len(texts)
        encoded = []
        encoded_indices = []
        for index, text in enumerate(texts):
            if not isinstance(text, str) or not text.strip():
                outputs[index] = ValueError("translation input must be non-empty text")
                continue
            try:
                encoded.append(self._source.encode(text, out_type=str))
                encoded_indices.append(index)
            except Exception as exc:
                outputs[index] = exc

        if not encoded:
            return outputs

        try:
            results = self._translator.translate_batch(
                encoded, beam_size=4, max_decoding_length=512
            )
            if len(results) != len(encoded):
                raise RuntimeError("CTranslate2 returned an unexpected batch length")
        except Exception:
            # A batch-level engine failure should not cause one record to hide
            # whether other inputs can still be translated individually.
            results = []
            for tokens in encoded:
                try:
                    single = self._translator.translate_batch(
                        [tokens], beam_size=4, max_decoding_length=512
                    )
                    if len(single) != 1:
                        raise RuntimeError("CTranslate2 returned an unexpected result length")
                    results.append(single[0])
                except Exception as exc:
                    results.append(exc)

        for index, result in zip(encoded_indices, results):
            if isinstance(result, Exception):
                outputs[index] = result
                continue
            try:
                outputs[index] = self._target.decode(result.hypotheses[0]).strip()
            except Exception as exc:
                outputs[index] = exc
        return outputs
