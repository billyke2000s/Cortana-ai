# Changelog

All notable changes. Dates are UK time.

## [1.3.0] - 2026-11-01

### Added
- **Web search without a key**: real web results from Bing's RSS feed (DuckDuckGo results page as fallback), and she reads the
  top result page for the actual answer. Private/home-network addresses are never fetched.
- **Chat page**: the Chat tab is now the same holo panel as Tasks/Memory/Systems, with message bubbles, a typing indicator and
  code/table/weather cards inside the conversation. The reply caption under her matches.
- **Weather card every time**: built from the forecast data instead of depending on the model.
- **"Hey Cortana" more reliable**: fuzzy name matching on the PC (Whisper writes it as Katana, Courtana, Cortona…), a name hint
  for Whisper, thresholds that adapt to the mic and room, and bursts no longer dropped while one is being checked.
- **Fixed:** the 35B model's tag is `qwen3.5:35b` (was `qwen3.5:35b-a3b`, which doesn't exist, so the model picker hid it).
- Manual **Live check** workflow (real searches and wake phrases through real Whisper on Windows). 9 new tests (46 total).

## [1.2.0] - 2026-11-01

### Added
- **First-launch model choice**: the app no longer picks a model silently. On first launch the PC page opens
  "Choose your AI", lists the Qwen 3.5 models rated for this PC's graphics card (recommended starred, too-big disabled)
  and waits for Use/Download before loading anything. `chooseModel` in `/api/status`. 1 new test (38 total).

## [1.1.0] - 2026-11-01

### Added
- **Model recommendation & download**: detects GPU memory (nvidia-smi or the Windows display-adapter registry) and RAM,
  rates every Qwen 3.5 model (Fast / Good / Slow / Too big), marks the recommended one, and downloads models from Systems
  with a live progress bar. Too-big models can't be selected (enforced by the server). First run picks the recommended
  model, or the best one already installed.
- `GET/POST /api/models`; `app/hardware.py`; 5 new tests (37 total).
- **Downloadable `Cortana.exe`**: `.github/workflows/release.yml` runs the tests and builds the exe on a Windows runner,
  then attaches it to a GitHub release.

### Fixed
- **Calendar repeats across a clock change**: weekly events were expanded in the PC's local time, so after a
  BST/GMT change they moved by an hour and cancelled dates (EXDATE) still showed. Repeats are now expanded in the event's
  own time zone. Found by the Windows release build (UTC runner).
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
