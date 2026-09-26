"""Check real Transformers preprocessing without loading model weights."""

from types import SimpleNamespace
import unittest

import numpy as np
import torch
from transformers import AutomaticSpeechRecognitionPipeline, WhisperFeatureExtractor


class WhisperPreprocessingTests(unittest.TestCase):
    def test_short_boundary_and_long_chunks_preserve_audio_frames(self):
        # Preprocessing needs the extractor and dtype, but does not use the model.
        pipeline = SimpleNamespace(
            type="seq2seq_whisper",
            feature_extractor=WhisperFeatureExtractor(feature_size=128),
            dtype=torch.float32,
        )
        for seconds in (20, 30, 38):
            with self.subTest(seconds=seconds):
                outputs = list(AutomaticSpeechRecognitionPipeline.preprocess(
                    pipeline,
                    {"raw": np.zeros(seconds * 16000, dtype=np.float32), "sampling_rate": 16000},
                ))
                self.assertEqual(len(outputs), 1)
                output = outputs[0]
                self.assertTrue(output["is_last"])
                self.assertEqual(tuple(output["input_features"].shape), (1, 128, max(30, seconds) * 100))
                self.assertEqual(output["attention_mask"].sum().item(), seconds * 100)


if __name__ == "__main__":
    unittest.main()
