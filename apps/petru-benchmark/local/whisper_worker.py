"""Persistent Whisper worker. stdin/stdout carry one JSON message per line."""

import argparse
import copy
import json
import os
from pathlib import Path
import sys
import time
import wave
from contextlib import redirect_stdout

# Loading and inference use the downloaded files even when the computer is online.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"


def emit(message):
    print(json.dumps(message, ensure_ascii=False, allow_nan=False), flush=True)


def read_audio(path):
    import numpy as np

    with wave.open(path, "rb") as audio:
        if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) != (1, 16000, 2):
            raise ValueError("Local Whisper requires mono 16 kHz PCM16 WAV audio.")
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
    if samples.size == 0:
        raise ValueError("Audio contains no samples.")
    return samples.astype(np.float32) / 32768.0


class WhisperRunner:
    def __init__(self, model_path, requested_device):
        import torch
        import transformers
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

        started = time.perf_counter()
        if requested_device == "auto":
            requested_device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
        self.device = requested_device
        self.versions = {"torch": torch.__version__, "transformers": transformers.__version__}
        # Float32 keeps the initial comparison close to the downloaded checkpoint.
        self.model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_path, local_files_only=True, use_safetensors=True,
            dtype=torch.float32, attn_implementation="eager",
        )
        self.model.eval()
        self.processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
        self.processor.tokenizer.clean_up_tokenization_spaces = False
        self.asr = pipeline(
            "automatic-speech-recognition", model=self.model,
            tokenizer=self.processor.tokenizer,
            feature_extractor=self.processor.feature_extractor, device=self.device,
        )
        self.load_ms = round((time.perf_counter() - started) * 1000)
        metadata = Path(model_path) / ".cache/huggingface/download/model.safetensors.metadata"
        self.revision = metadata.read_text().splitlines()[0] if metadata.is_file() else None

    def transcribe(self, path, options):
        import torch

        samples = read_audio(path)
        settings = copy.deepcopy(self.model.generation_config)
        # Passing language=None alone does not clear the checkpoint's saved 'ro'.
        settings.language = None if options["language"] == "auto" else options["language"]
        settings.task = "transcribe"
        settings.forced_decoder_ids = None
        settings.use_cache = True
        settings.return_timestamps = False
        temperature = options["temperature"]
        settings.do_sample = temperature > 0
        settings.num_beams = 1
        generate = {"generation_config": settings, "temperature": temperature}
        prompt_tokens = 0
        if options["prompt"]:
            prompt_ids = self.processor.get_prompt_ids(options["prompt"], return_tensors="pt")
            prompt_tokens = prompt_ids.numel() - 1  # Exclude the start-of-context token.
            limit = self.model.config.max_target_positions // 2 - 1
            if prompt_tokens > limit:
                raise ValueError(f"Context and vocabulary use {prompt_tokens} Whisper tokens; the limit is {limit}. Shorten the context prompt or vocabulary.")
            generate["prompt_ids"] = prompt_ids.to(self.device)

        # The pipeline keeps all frames and uses native sequential long-form decoding.
        # Whisper needs timestamp tokens internally for audio longer than 30 seconds.
        timestamps = "word" if options["timestamps"] else samples.size > 30 * 16000
        started = time.perf_counter()
        with torch.inference_mode():
            output = self.asr(
                {"raw": samples, "sampling_rate": 16000},
                return_timestamps=timestamps, generate_kwargs=generate,
            )
        result = {
            **output,
            "runtime": {
                "engine": "transformers", "device": self.device, "dtype": "float32",
                "versions": self.versions,
                "modelRevision": self.revision, "modelLoadMs": self.load_ms,
                "inferenceMs": round((time.perf_counter() - started) * 1000),
                "audioSeconds": samples.size / 16000,
                "language": options["language"], "task": "transcribe",
                "timestampMode": timestamps,
                "promptTokens": prompt_tokens,
            },
        }
        if options["timestamps"]:
            # Keep missing word boundaries in raw chunks; do not invent their times.
            spans = [
                {"start": chunk["timestamp"][0], "end": chunk["timestamp"][1], "text": chunk["text"]}
                for chunk in output.get("chunks", [])
                if None not in chunk["timestamp"]
            ]
            result["segments"] = spans
            result["words"] = [{"start": span["start"], "end": span["end"], "word": span["text"]} for span in spans]
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--device", choices=["auto", "mps", "cpu", "cuda"], default="auto")
    args = parser.parse_args()
    # Library progress and diagnostics must never mix with the JSON protocol.
    with redirect_stdout(sys.stderr):
        runner = WhisperRunner(args.model_path, args.device)
    emit({"type": "ready", "device": runner.device})
    for line in sys.stdin:
        request = json.loads(line)
        try:
            with redirect_stdout(sys.stderr):
                result = runner.transcribe(request["audioPath"], request["options"])
            emit({"type": "result", "id": request["id"], "response": result})
        except Exception as error:
            emit({"type": "error", "id": request["id"], "message": str(error)})


if __name__ == "__main__":
    main()
