# Changelog

All notable changes. Dates are UK time.

## [Unreleased] Agent abilities

- Qwen chooses tools semantically, including weather; removes the production weather keyword pre-router (supersedes D-027).
- Dynamic tool discovery, longer bounded missions, current file/page context, progress and exact-once reviewed external actions.
- Approved-folder file creation/edit/move/duplicates/organisation with guarded undo; real DOCX/PDF/CSV/XLSX/chart deliverables and authenticated downloads.
- Isolated offline Python in Docker; visible dedicated browser automation; observed Windows accessibility controls; actual PC diagnostics.
- Multiple local images, scanned PDF pages and optional FFmpeg video frames; configured email, CalDAV, Home Assistant/music and MCP HTTP connections.
- Local scheduled/folder-change goals; Fast/Deep reasoning and conservative hardware context limits; Abilities/Activity pages.
- Added dependencies/build collection and cross-platform, browser, Docker, Windows, real-model and packaged-feature checks. Verification is recorded in docs/STATUS.md.
- Limits: external accounts need setup; MCP supports the 2025 HTTP family, not stdio/2026-only endpoints; OAuth tokens do not auto-refresh; Windows control coverage depends on accessibility support. Jobs require the launcher open. Formula calculation remains Excel's responsibility.

## [1.5.0] - 2026-11-01

### Added
- First setup asks for Normal/Expressive movement and PC voice, with previews and saved choices in Systems.
- Normal uses the old Expressive strength; Expressive adds stronger semantic expressions, asymmetric smirks and brief hand emphasis.
- Optional experimental reference voice: CPU ZipVoice-Distill int8 + Vocos; fast Piper and Windows fallback remain available.
- Rhubarb phonetic audio alignment for neural voices; SAPI retains its native visemes; envelope fallback remains available.
- Request IDs, server cancellation and queued speech abort; opt-in wake interruption while thinking/speaking with echo rejection.
- Restore saved chat on reload; bounded older-turn excerpts; relevant memory retrieval, editing and possible-conflict review.
- Windows reminder balloons with the browser closed, missed alerts on reopening, ten-minute snooze and recent timer alerts.
- Small CPU keyword spotter before Whisper; transcription, first-token, speech-preparation and playback latency measurements.
- 16 regression tests (80 total); browser, real 4B/9B, native Windows and packaged voice release checks.

### Limits
- Reference speech is experimental, can skip/mispronounce words, and is slower than Piper. No exact-match claim.
- Native synthesis may finish its current chunk after Stop; cancelled output is discarded. Already executed tools are not undone.
- Keep the launcher running for reminders. Windows notification settings and real-room microphone echo require desktop testing.

## [1.4.0] - 2026-11-01

### Added
- **Read your files**: PDF, Word (.docx), PowerPoint (.pptx) and text files, from the 📎 in Chat, by dropping them on the
  panel, from Memory → Documents, or a whole folder (PC only). "Summarise this", "what does the brief say about the deadline?",
  "quiz me on chapter 3": answers cite the document and page. Only the extracted text is kept, on the PC. Adds pypdf (BSD-3).
- **See your screen**: "what's this error on my screen?" captures the primary screen and the local Qwen model reads it
  (Qwen 3.5 takes images at every size). The screenshot is deleted straight away.
- **Clipboard**: "summarise what I copied", "fix this code I copied" (text or a copied image), "copy that to my clipboard".
  Every chat card has a **Copy** button.
- **Find files**: "where's my coursework PDF from last week?" searches Desktop, Documents, Downloads, OneDrive and more;
  "open number 1" / "read number 1". She never opens programs, scripts or shortcuts.
- **Calendar events**: "book study time Thursday at 3" saves the event, reminds you 10 minutes before, and shows an
  **Add to Google Calendar** button. Google Calendar events also get a reminder 10 minutes before.
- **Screen, clipboard and file access** switch in Systems. Cards for found files and new events, built from the data.
- `/api/documents`, `/api/events`; real-model and Windows checks in the Live check workflow; the release build now launches
  the real `Cortana.exe` and checks it before publishing. 18 new tests (64 total).

### Fixed
- **Invented weather**: the 4B model sometimes answered weather questions without checking. The app now fetches the forecast
  first and the model answers from it (4/4 faithful in the real-model check).
- The windowed exe would crash in `--headless` mode on its first status line (no console).

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
