#!/usr/bin/env python3
"""
Local Piper voice trainer: upload a recording of your voice -> get an .onnx voice.

Steps it runs for you:
  1. Transcribe + cut the recording into clips (faster-whisper)       -> dataset
  2. Download a medium-quality English starting checkpoint            -> base.ckpt
  3. Fine-tune Piper on your clips (GPU)                              -> checkpoints
  4. Export the newest checkpoint to ONNX                             -> <voice>.onnx + .onnx.json
  5. Speak a test sentence with the new voice                         -> test.wav

Start it with run.sh (made by setup.sh), then open http://localhost:7860
Everything lives in ./runs/<voice name>/ next to this file.
"""
import glob
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

import gradio as gr

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
SR = 22050                      # Piper "medium" sample rate
CKPT_REPO = "rhasspy/piper-checkpoints"
PY = sys.executable             # the Piper venv's python (run.sh activates it)

_proc = None                    # running subprocess, so Stop can kill it
_stop = threading.Event()


# ---------------------------------------------------------------- helpers
def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "_", (name or "").strip().lower()).strip("_")
    return s or "myvoice"


def run_dir(name: str) -> Path:
    d = RUNS / slug(name)
    d.mkdir(parents=True, exist_ok=True)
    return d


def lang_code(espeak_voice: str) -> str:
    return "en_GB" if espeak_voice == "en-gb" else "en_US"


def run_cmd(cmd, log: deque, cwd=None):
    """Run a command, streaming its output into `log`. Yields after each line."""
    global _proc
    log.append("$ " + " ".join("<export script>" if "\n" in str(c) else str(c) for c in cmd))
    _proc = subprocess.Popen(
        [str(c) for c in cmd], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, start_new_session=True,  # own process group so Stop kills children
    )
    for line in _proc.stdout:                         # text mode also splits on \r (progress bars)
        line = line.rstrip()
        if line:
            log.append(line)
            yield
    code = _proc.wait()
    _proc = None
    if _stop.is_set():
        raise RuntimeError("Stopped.")
    if code != 0:
        raise RuntimeError(f"Command failed (exit code {code}). See the log above.")


def show(log: deque) -> str:
    return "\n".join(log)


def epoch_of(ckpt: str) -> int:
    m = re.search(r"epoch=(\d+)", os.path.basename(ckpt))
    return int(m.group(1)) if m else 0


def latest_ckpt(d: Path):
    files = glob.glob(str(d / "lightning_logs" / "version_*" / "checkpoints" / "*.ckpt"))
    return max(files, key=os.path.getmtime) if files else None


# ---------------------------------------------------------------- step 1: dataset
def build_dataset(audio_path: str, d: Path, whisper_model: str, log: deque):
    import numpy as np
    import soundfile as sf
    import librosa
    from faster_whisper import WhisperModel

    wav_dir = d / "dataset" / "wavs"
    if wav_dir.exists():
        shutil.rmtree(wav_dir)
    wav_dir.mkdir(parents=True)

    log.append(f"Loading audio: {os.path.basename(audio_path)}")
    yield
    audio, _ = librosa.load(audio_path, sr=SR, mono=True)
    log.append(f"  {len(audio)/SR/60:.1f} minutes of audio")
    yield

    try:
        model = WhisperModel(whisper_model, device="cuda", compute_type="float16")
        log.append(f"Transcribing with Whisper '{whisper_model}' on GPU...")
    except Exception as e:  # missing CUDA libs for ctranslate2 etc.
        log.append(f"  GPU transcription unavailable ({e.__class__.__name__}); using CPU (slower).")
        model = WhisperModel(whisper_model, device="cpu", compute_type="int8")
    yield
    segments, _ = model.transcribe(audio_path, language="en", vad_filter=True, beam_size=5)
    segs = []
    for s in segments:
        if _stop.is_set():
            raise RuntimeError("Stopped.")
        if s.text.strip():
            segs.append((s.start, s.end, s.text.strip()))
            if len(segs) % 20 == 0:
                log.append(f"  transcribed {len(segs)} segments ({s.end/60:.1f} min)")
                yield
    log.append(f"  {len(segs)} segments total")

    # merge short neighbours, keep 1-15 s clips
    merged = []
    for start, end, text in segs:
        if merged:
            ps, pe, pt = merged[-1]
            if (pe - ps) < 2.0 and start - pe < 0.35 and end - ps <= 15.0:
                merged[-1] = (ps, end, f"{pt} {text}")
                continue
        merged.append((start, end, text))

    rows, kept = [], 0.0
    for start, end, text in merged:
        if not 1.0 <= end - start <= 15.0:
            continue
        a, b = max(0, int((start - 0.12) * SR)), min(len(audio), int((end + 0.12) * SR))
        clip = audio[a:b]
        clip = clip / (np.max(np.abs(clip)) or 1.0) * 0.89
        name = f"clip_{len(rows)+1:04d}.wav"
        sf.write(wav_dir / name, clip, SR, subtype="PCM_16")
        rows.append(f"{name}|{text.replace('|', ' ')}")
        kept += len(clip) / SR

    (d / "dataset" / "metadata.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    log.append(f"Dataset ready: {len(rows)} clips, {kept/60:.1f} minutes")
    log.append(f"  Transcript: {d/'dataset'/'metadata.csv'} (you can fix wrong words, then press Start again with 'Rebuild dataset' unticked)")
    if kept < 600:
        log.append("  WARNING: under 10 minutes of usable audio - the voice may sound rough.")
    if not rows:
        raise RuntimeError("No usable clips were found. Is the file mostly speech?")
    yield


# ---------------------------------------------------------------- step 2: base checkpoint
def list_base_voices():
    from huggingface_hub import HfApi
    files = HfApi().list_repo_files(CKPT_REPO)
    voices = sorted(f for f in files if f.endswith(".ckpt") and f.startswith("en/") and "/medium/" in f)
    if not voices:
        raise RuntimeError("No English medium checkpoints found.")
    return voices


def get_base_ckpt(choice: str, custom: str, log: deque) -> str:
    if custom and custom.strip():
        p = custom.strip()
        if not os.path.isfile(p):
            raise RuntimeError(f"Custom checkpoint not found: {p}")
        return p
    if not choice:
        raise RuntimeError("Pick a starting voice (press 'Load starting voices') or give a checkpoint path.")
    from huggingface_hub import hf_hub_download
    log.append(f"Downloading starting checkpoint: {choice} (large, one time only)...")
    return hf_hub_download(CKPT_REPO, choice, local_dir=str(HERE / "base_checkpoints"))


# ---------------------------------------------------------------- step 4: export
EXPORT_WRAPPER = r"""
import inspect, runpy, sys, torch
_orig = torch.onnx.export
# Newer PyTorch defaults to the 'dynamo' exporter, which breaks Piper's model
# (error: 'assert (discriminant >= 0)'). Force the classic exporter.
if "dynamo" in inspect.signature(_orig).parameters:
    def _export(*a, **k):
        k.setdefault("dynamo", False)
        return _orig(*a, **k)
    torch.onnx.export = _export
sys.argv = ["export_onnx"] + sys.argv[1:]
runpy.run_module("piper.train.export_onnx", run_name="__main__")
"""


def export_and_test(name: str, espeak_voice: str, log: deque, out: dict):
    d = run_dir(name)
    ckpt = latest_ckpt(d)
    if not ckpt:
        raise RuntimeError("No trained checkpoint yet. Train first (let it run at least a few epochs).")
    base = f"{lang_code(espeak_voice)}-{slug(name)}-medium"
    onnx = d / "export" / f"{base}.onnx"
    onnx.parent.mkdir(exist_ok=True)
    log.append(f"Exporting {os.path.basename(ckpt)} (epoch {epoch_of(ckpt)}) to ONNX...")
    yield
    yield from run_cmd([PY, "-c", EXPORT_WRAPPER, "--checkpoint", ckpt, "--output-file", onnx], log)
    cfg = d / "config.json"
    if not cfg.exists():
        raise RuntimeError(f"Missing {cfg} (written during training).")
    shutil.copy(cfg, str(onnx) + ".json")
    out["onnx"], out["json"] = str(onnx), str(onnx) + ".json"
    log.append(f"Exported: {onnx}")
    log.append(f"          {onnx}.json")
    yield

    test = d / "export" / "test.wav"
    log.append("Speaking a test sentence...")
    yield
    try:
        yield from run_cmd([PY, "-m", "piper", "-m", onnx, "-f", test, "--",
                            "Hello Chief. All systems are operational, and this is my new voice."], log)
        out["test"] = str(test)
    except RuntimeError as e:
        log.append(f"  (Test sentence failed: {e} The voice files are still fine.)")
    yield


# ---------------------------------------------------------------- the full pipeline
def start(audio, name, consent, espeak_voice, base_choice, custom_ckpt, whisper_model,
          extra_epochs, batch_size, rebuild):
    log, out = deque(maxlen=400), {}
    _stop.clear()

    def ui():
        return (show(log), out.get("onnx"), out.get("json"), out.get("test"))

    try:
        if not consent:
            raise RuntimeError("Tick the box confirming this is your own voice (or you have the speaker's permission).")
        d = run_dir(name)
        meta = d / "dataset" / "metadata.csv"

        # 1. dataset
        if rebuild or not meta.exists():
            if not audio:
                raise RuntimeError("Upload a recording first.")
            for _ in build_dataset(audio, d, whisper_model, log):
                yield ui()
        else:
            log.append(f"Using existing dataset: {meta}")
            yield ui()

        # 2. starting checkpoint (or resume our own run)
        resume = latest_ckpt(d)
        if resume:
            ckpt = resume
            log.append(f"Resuming your earlier training from {os.path.basename(ckpt)}")
        else:
            ckpt = get_base_ckpt(base_choice, custom_ckpt, log)
        yield ui()

        # 3. train
        target = epoch_of(ckpt) + int(extra_epochs)
        log.append(f"Training to epoch {target} ({int(extra_epochs)} more). Press Stop any time, then Export.")
        yield ui()
        cmd = [PY, "-m", "piper.train", "fit",
               "--data.voice_name", slug(name),
               "--data.csv_path", meta,
               "--data.audio_dir", d / "dataset" / "wavs",
               "--model.sample_rate", SR,
               "--data.espeak_voice", espeak_voice,
               "--data.cache_dir", d / "cache",
               "--data.config_path", d / "config.json",
               "--data.batch_size", int(batch_size),
               "--trainer.max_epochs", target,
               "--trainer.default_root_dir", d,
               "--ckpt_path", ckpt]
        for _ in run_cmd(cmd, log, cwd=d):
            yield ui()

        # 4 + 5. export and test
        for _ in export_and_test(name, espeak_voice, log, out):
            yield ui()
        log.append("All done. Download the .onnx and .onnx.json files below.")
    except Exception as e:
        log.append(f"\n>>> {e}")
        if "out of memory" in show(log).lower():
            log.append(">>> GPU ran out of memory: lower the batch size (try 8, then 4) and press Start again.")
    yield ui()


def export_only(name, espeak_voice):
    log, out = deque(maxlen=400), {}
    _stop.clear()
    try:
        for _ in export_and_test(name, espeak_voice, log, out):
            yield show(log), out.get("onnx"), out.get("json"), out.get("test")
    except Exception as e:
        log.append(f"\n>>> {e}")
    yield show(log), out.get("onnx"), out.get("json"), out.get("test")


def stop():
    _stop.set()
    if _proc and _proc.poll() is None:
        os.killpg(os.getpgid(_proc.pid), signal.SIGTERM)
    return "Stopping... (your latest saved checkpoint is kept - press Export to use it)"


def load_voices():
    try:
        v = list_base_voices()
        pick = next((x for x in v if "/en_GB/" in x), v[0])
        return gr.Dropdown(choices=v, value=pick), f"Found {len(v)} starting voices."
    except Exception as e:
        return gr.Dropdown(choices=[]), f"Couldn't list voices ({e}). Paste a .ckpt path instead."


# ---------------------------------------------------------------- UI
with gr.Blocks(title="Voice Trainer") as app:
    gr.Markdown("# Local Voice Trainer\nUpload a recording of **your** voice and get a Piper `.onnx` voice back. "
                "Runs entirely on this PC.")
    with gr.Row():
        with gr.Column():
            audio = gr.File(label="Your recording (mp3, wav, m4a...)", type="filepath",
                            file_types=["audio", ".mp3", ".wav", ".m4a", ".flac", ".ogg"])
            name = gr.Textbox(label="Voice name", value="myvoice")
            consent = gr.Checkbox(label="This recording is my own voice, or I have the speaker's permission.")
            espeak_voice = gr.Dropdown(["en-gb", "en-us"], value="en-gb", label="Accent")
            with gr.Row():
                base = gr.Dropdown([], label="Starting voice (pick one close to yours)", scale=3)
                load_btn = gr.Button("Load starting voices", scale=1)
            base_msg = gr.Markdown()
            custom = gr.Textbox(label="...or path to a .ckpt you already have (optional)")
            with gr.Accordion("Settings", open=False):
                whisper_model = gr.Dropdown(["small.en", "medium.en", "large-v3"], value="medium.en",
                                            label="Transcription model (bigger = more accurate, slower)")
                extra_epochs = gr.Number(value=1000, precision=0, label="Epochs to train (more = closer to you, longer)")
                batch = gr.Number(value=12, precision=0, label="Batch size (lower if GPU runs out of memory)")
                rebuild = gr.Checkbox(value=True, label="Rebuild dataset from the upload (untick to reuse an edited transcript)")
            with gr.Row():
                go = gr.Button("Start", variant="primary")
                stop_btn = gr.Button("Stop")
                exp = gr.Button("Export latest checkpoint")
        with gr.Column():
            log = gr.Textbox(label="Progress", lines=26, max_lines=26, autoscroll=True)
            onnx_out = gr.File(label="Voice model (.onnx)")
            json_out = gr.File(label="Voice config (.onnx.json)")
            test_out = gr.Audio(label="Test sentence", type="filepath")

    load_btn.click(load_voices, outputs=[base, base_msg])
    go.click(start, [audio, name, consent, espeak_voice, base, custom, whisper_model, extra_epochs, batch, rebuild],
             [log, onnx_out, json_out, test_out])
    stop_btn.click(stop, outputs=log)
    exp.click(export_only, [name, espeak_voice], [log, onnx_out, json_out, test_out])

if __name__ == "__main__":
    RUNS.mkdir(exist_ok=True)
    app.queue().launch(server_name="127.0.0.1", server_port=7860, allowed_paths=[str(RUNS)])
