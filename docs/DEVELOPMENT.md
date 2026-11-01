# Development

> Working with an AI agent? It must follow [AGENTS.md](../AGENTS.md). Humans should too.

## Prerequisites (Windows)

- Python 3.11+ (64-bit) from python.org, with "Add to PATH".
- [Ollama](https://ollama.com), or let Cortana download it on first run. Models: `ollama pull qwen3.5:9b` and `ollama pull qwen3.5:4b`.
- Chrome or Edge.

## Run from source

```powershell
pip install -r requirements.txt
python app/launcher.py                 # window + browser, Cloudflare phone link
python app/launcher.py --no-tunnel     # PC only
python app/launcher.py --headless --no-open --port 8777   # no window; prints status lines (used by tests/live_check.py)
```

Environment variables: `CORTANA_DATA_DIR` (data folder), `CORTANA_OLLAMA_URL` (default `http://127.0.0.1:11434`),
`CORTANA_MODEL` (overrides the Systems setting).

Changes to `app/*.html|js|css` need only a browser refresh (files are served from `app/` when running from source).
Python changes need a restart.

## Build the .exe

```powershell
python build/build_cortana.py      # → dist\Cortana.exe ; log in build\work\cortana-build.log
```

The script installs PyInstaller, qrcode, python-dateutil and tzdata if missing, warns if the 3D model is absent, and exits
non-zero on failure (last 2,500 log characters printed).

## Tests

```bash
python -m unittest discover -s tests -v   # offline, any OS, ~1 s
```
See [TESTING.md](TESTING.md).

## Conventions

- **Python:** standard library first; match the surrounding style (the original files are compact; new modules use
  normal PEP 8 layout). Plain-English user errors. Never block or hold locks across `yield`.
- **JavaScript:** ES modules, no build step, no frameworks. `const`/`let`, optional chaining for cross-module calls, escape all untrusted text.
- **CSS:** phone-first; new rules for the main screen go in `responsive.css`.
- **Comments:** explain *why*, especially workarounds (link the DECISIONS number).
- **Line endings:** LF in the repo; `.bat/.cmd/.ps1` CRLF (see `.gitattributes`).

## How-tos

The step-by-step checklists live in [AGENTS.md §10](../AGENTS.md#10-checklists-follow-every-step):
adding a web file, a Python module, a tool, a setting, an endpoint; changing the prompt; releasing.

### Try the API by hand
```bash
curl -N -X POST http://127.0.0.1:PORT/api/chat-stream -H "Content-Type: application/json" \
     -d "{\"messages\":[{\"role\":\"user\",\"content\":\"Set a 1 minute timer\"}]}"
```

### Reset local data
Close Cortana and delete `%LOCALAPPDATA%\CortanaAI\cortana.db*` (settings, memory and objectives) or the whole folder
(also re-downloads Whisper, Piper and voices).

### Logs
`%LOCALAPPDATA%\CortanaAI\startup-error.log`, `ollama.log`, `piper.log`. The browser console shows `[Cortana avatar]` messages for model loading.

## Voice trainer

`tools/voice-trainer/` trains a Piper voice from **your own** recordings (WSL2 Ubuntu + NVIDIA GPU). See its [README](../tools/voice-trainer/README.md).

## Companion runtime

Requirements now include sherpa-onnx 2.0.1 and NumPy (CPU ONNX, no PyTorch), in addition to the existing packages. PyInstaller collects sherpa-onnx and its core shared libraries and bundles `voice-profile`; downloaded model weights stay outside Git. `neural.py`, `lips.py`, and `companion.py` are hidden imports.

`tests/browser_check.py` requires Playwright 1.51 + Chromium. `tests/ci_context_check.py qwen3.5:4b` (and `:9b`) needs local Ollama with the named model. `tests/ci_native_check.py` exercises Windows SAPI → keyword detection and the notification process. `tests/release_voice_check.py URL` tests real speech and cues from the built exe, not just Python imports. See the release workflow.
