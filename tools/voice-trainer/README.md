# Voice Trainer

Train a [Piper](https://github.com/OHF-Voice/piper1-gpl) voice from **a recording of your own voice**, locally on your
NVIDIA GPU, and get the `.onnx` + `.onnx.json` files Cortana can speak with.

> ⚠️ **Consent required.** Only use recordings of yourself, or of someone who has given you explicit permission.
> The trainer asks you to confirm this. Do not use game, film or TV audio of other people's voices.

## Requirements

- Windows 10/11 with WSL2 (the launcher installs Ubuntu if needed) or Ubuntu Linux
- NVIDIA GPU (8 GB works; lower the batch size if you run out of memory)
- A clean recording: 10–60 minutes of you reading varied sentences, quiet room, no music

## Use

1. Put `Voice Trainer.bat`, `setup.sh` and `voice_trainer.py` in one folder.
2. Double-click **Voice Trainer.bat**. The first run installs WSL/Ubuntu (admin prompt, maybe a restart) and then Piper's
   training environment (10–30 minutes).
3. Your browser opens **http://localhost:7860**: upload your recording, tick the consent box, pick a starting voice close to
   yours, press **Start**.
4. When it finishes (or after **Stop → Export latest checkpoint**), download `en_GB-<name>-medium.onnx` and `.onnx.json`.
5. Copy both into `%LOCALAPPDATA%\CortanaAI\voices\`, restart Cortana, and choose the voice in **Systems**.

## What it does

1. Transcribes and cuts the recording into 1–15 s clips (faster-whisper) → `metadata.csv` (edit it to fix wrong words).
2. Downloads a medium-quality starting checkpoint (`rhasspy/piper-checkpoints`).
3. Fine-tunes with `python -m piper.train fit` (resumes if you press Start again).
4. Exports ONNX with the classic exporter (works around the PyTorch `discriminant >= 0` export error).
5. Speaks a test sentence.

## Status

[Unverified] The pipeline was tested in a Linux environment with stand-ins for Whisper, Piper and PyTorch; real training
runs on Windows/WSL have not been confirmed. If something fails, the **Progress** box shows the error.
