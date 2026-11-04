import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from artrend_mag import opus_korean as model


class OpusKoreanTests(unittest.TestCase):
    def test_vocabulary_order_is_preserved_instead_of_sorted(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.vocab'
            output = Path(directory) / 'source.yml'
            source.write_text('<unk>\n<s>\n</s>\n▁zebra\n▁apple\n', encoding='utf-8')
            model._vocabulary_yaml(source, output)
            self.assertIn('"▁zebra": 3', output.read_text())
            self.assertIn('"▁apple": 4', output.read_text())

    def test_duplicate_vocabulary_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.vocab'
            source.write_text('same\nsame\n')
            with self.assertRaises(RuntimeError):
                model._vocabulary_yaml(source, Path(directory) / 'out.yml')

    @patch('artrend_mag.opus_korean.is_installed', return_value=True)
    def test_source_and_target_tokenizers_remain_distinct(self, installed):
        source, target, translator = Mock(), Mock(), Mock()
        source.encode.return_value = ['▁Hello']
        target.decode.return_value = ' 안녕하세요 '
        translator.translate_batch.return_value = [SimpleNamespace(hypotheses=[['▁안녕하세요']])]
        backend = model.OpusKoreanBackend(translator, source, target)
        self.assertEqual(backend.translate('Hello'), '안녕하세요')
        source.encode.assert_called_once_with('Hello', out_type=str)
        target.decode.assert_called_once_with(['▁안녕하세요'])
        translator.translate_batch.assert_called_once_with([['▁Hello']], beam_size=4, max_decoding_length=512)

    @patch('artrend_mag.opus_korean.is_installed', return_value=True)
    def test_multiple_texts_share_one_ctranslate2_batch(self, installed):
        source, target, translator = Mock(), Mock(), Mock()
        source.encode.side_effect = [['▁One'], ['▁Two']]
        target.decode.side_effect = ['하나', '둘']
        translator.translate_batch.return_value = [
            SimpleNamespace(hypotheses=[['▁하나']]),
            SimpleNamespace(hypotheses=[['▁둘']]),
        ]
        backend = model.OpusKoreanBackend(translator, source, target)

        outputs = backend.translate_many(['One', 'Two'])

        self.assertEqual(outputs, ['하나', '둘'])
        translator.translate_batch.assert_called_once_with(
            [['▁One'], ['▁Two']], beam_size=4, max_decoding_length=512
        )

    @patch('artrend_mag.opus_korean.is_installed', return_value=True)
    def test_batch_engine_failure_falls_back_per_item_and_isolates_error(self, installed):
        source, target, translator = Mock(), Mock(), Mock()
        source.encode.side_effect = [['▁Good'], ['▁Bad'], ['▁AlsoGood']]

        def translate_batch(tokens, **kwargs):
            if len(tokens) > 1:
                raise RuntimeError('batch failure')
            if tokens[0] == ['▁Bad']:
                raise ValueError('bad item')
            return [SimpleNamespace(hypotheses=[tokens[0]])]

        translator.translate_batch.side_effect = translate_batch
        target.decode.side_effect = ['좋음', '정상']
        backend = model.OpusKoreanBackend(translator, source, target)

        outputs = backend.translate_many(['Good', 'Bad', 'AlsoGood'])

        self.assertEqual(outputs[0], '좋음')
        self.assertIsInstance(outputs[1], ValueError)
        self.assertEqual(outputs[2], '정상')
        self.assertEqual(translator.translate_batch.call_count, 4)

    @patch('artrend_mag.opus_korean.is_installed', return_value=True)
    def test_tokenization_failure_does_not_block_other_batch_members(self, installed):
        source, target, translator = Mock(), Mock(), Mock()
        source.encode.side_effect = [ValueError('bad input'), ['▁Good']]
        translator.translate_batch.return_value = [SimpleNamespace(hypotheses=[['▁Good']])]
        target.decode.return_value = '정상'
        backend = model.OpusKoreanBackend(translator, source, target)

        outputs = backend.translate_many(['Bad', 'Good'])

        self.assertIsInstance(outputs[0], ValueError)
        self.assertEqual(outputs[1], '정상')
        translator.translate_batch.assert_called_once_with(
            [['▁Good']], beam_size=4, max_decoding_length=512
        )

    @patch('artrend_mag.opus_korean.is_installed', return_value=False)
    @patch('artrend_mag.opus_korean._download_archive')
    def test_missing_model_never_downloads_during_inference(self, download, installed):
        with self.assertRaisesRegex(RuntimeError, 'install-model'):
            model.OpusKoreanBackend()
        download.assert_not_called()

    def test_model_signature_rejects_other_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(model, 'MODEL_DIR', Path(directory)):
            for name in ('model.bin', 'source.spm', 'target.spm'):
                (Path(directory) / name).write_bytes(b'test')
            data = model._manifest()
            data['source_sha256'] = 'wrong'
            (Path(directory) / model.MANIFEST_NAME).write_text(json.dumps(data))
            self.assertFalse(model.is_installed())
            data['source_sha256'] = model.ARCHIVE_SHA256
            (Path(directory) / model.MANIFEST_NAME).write_text(json.dumps(data))
            self.assertTrue(model.is_installed())


if __name__ == '__main__':
    unittest.main()
