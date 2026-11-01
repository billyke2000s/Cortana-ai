# Changelog

All notable changes. Dates are UK time.

## [1.1.0] - 2026-11-01

### Added
- **Model recommendation & download**: detects GPU memory (nvidia-smi or the Windows display-adapter registry) and RAM,
  rates every Qwen 3.5 model (Fast / Good / Slow / Too big), marks the recommended one, and downloads models from Systems
  with a live progress bar. Too-big models can't be selected (enforced by the server). First run picks the recommended
  model, or the best one already installed.
- `GET/POST /api/models`; `app/hardware.py`; 5 new tests (37 total).

### Fixed
- **Hair rendering** (dark helmet, strands across the face, varying per load): hair now writes depth as a cut-out material.
- Validation messages (e.g. "too big for this PC") now reach the page instead of a generic "Invalid request".

## [1.0.0] - 2026-11-01

### Added
- **Streaming replies**: `/api/chat-stream` (NDJSON). She speaks each sentence as soon as it's generated.
- **Abilities (AI tools)**: timers, reminders, to-do list, long-term memory, weather (Open-Meteo), web search (DuckDuckGo,
  Wikipedia, optional Brave), PC media/volume/app controls (allow-list), read-only calendar (private iCal address).
- **Pages**: Mission Briefing (with "Read my briefing"), Objectives (live timer countdowns), Memory, Systems (all settings).
- **Natural voice**: Piper as a persistent process; stock voices; drop-in trained voices; Windows voice fallback;
  lip sync from audio loudness.
- **Alerts**: chime + spoken timer/reminder alerts.
- **"Hey Cortana" wake word** (local transcription of speech bursts).
- **Optional Tailscale** stable phone link.
- **Local storage** (`store.py`, SQLite): settings, memory, objectives, conversation log.
- **Holographic display panel** (CORTANA // DISPLAY): code with syntax colours and Copy, tables, lists; stays above the navigation.
- Offline test suite (32 tests), live check, AGENTS.md rulebook, full documentation, original animated artwork.

### Changed
- Default model **Qwen 3.5 9B** (4B automatic fallback / Fast option); context 6,144 tokens.
- System prompt: knows the current date/time, home town and remembered facts; confident tone; screen format example.
- Repository layout: `app/`, `build/`, `tests/`, `tools/voice-trainer/`, `docs/`.

### Fixed
- **Phone QR pairing** showed "Open Cortana using the QR code" when opened from a camera/scanner app (`SameSite=Strict` → `Lax`).
  Unpaired visitors now get a helpful page.
- **Hair/textures** sometimes rendered wrong until refresh (texture validation + automatic reload; graphics-context recovery;
  Back/Forward restore).
- Long replies squeezed into a tiny box: text follows the voice; code and tables go to the display panel.
- Weather weekday off by one west of UTC.

### Security
- Settings API never returns secrets; settings input validated; regression tests for pairing, origin checks and private files.

## [0.3.0] - 2026-11-01
- Display panel for code/tables (first version); date/time in prompt; reply text follows speech.

## [0.2.0] - 2026-10-31
- Single-file Windows app (PyInstaller): Ollama + Qwen 3.5 4B, whisper.cpp, Windows voice with viseme lip sync, 3D avatar,
  Cloudflare phone link with QR pairing.

## [0.1.0] - 2026-10-31
- Original single-page interface (`cortana.html`): hologram stage, sprite-sheet avatar, browser speech recognition.
