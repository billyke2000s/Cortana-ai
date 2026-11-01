# Changelog

All notable changes. Dates are UK time.

## [1.6.0] - 2026-11-01

### Added (step 2: brain)
- Deep thinking: 🧠 toggle in Chat, or ask her to "think carefully" / "take your time". Reasoning is never spoken.
- Auto memory size: up to 16,384 tokens when the model and its cache fit on the graphics card (Systems → Brain; Standard keeps 6,144).

### Added (step 3: proactive)
- She tells you when new documents appear in your Documents folders (and reads them in), when a download finishes (opt-in), and reads a daily briefing at a time you choose. Windows pop-ups for each, titled "Cortana".

### Added (steps 4-6: ask before doing, work abilities)
- Ask before doing: anything that changes your PC shows an approval card in Chat (Approve/Cancel, or say "yes"/"cancel").
- Make files (Word, CSV, text, Markdown, web page) in Documents\\Cortana; exact table totals and arithmetic; tidy Downloads/Desktop/Documents by type (moves only, duplicates listed); PC health check; email drafts in your mail app.
- Pictures in Chat (📎, up to 2 per question, not saved). Deep thinking allows up to 6 steps.
- Work tools are only offered when the question is about them, so ordinary answers keep the same context budget.

### Fixed
- Long documents are split at line ends where possible, so table rows stay whole.
- Timers and reminders can't be faked: a plain "set a 10 minute timer…" or "remind me to … at 6pm" is set by the app first, then she confirms it; for any other action she claims without doing (remember, add to list…), the app sends the model back once to actually do it. The 9B model was caught twice in release checks saying it had done things it hadn't.
- CSV files made on Windows no longer get doubled line breaks (blank rows in Excel); caught by the Windows CI run.
- Browser check waits on requests instead of a 0.7-second "Saved." message (it was flaky).

### Step 1: speed and fixes

### Fixed
- Cortana's voice no longer re-hashes and re-unpacks its 109 MB model archive (and the 87 MB lip-sync zip) on every launch; it unpacks once (`.unpacked` marker).
- The voice warms up at startup, so the first reply no longer pays the slow first-generation cost. Measured on a 2-core cloud CPU: second launch load + warm-up 9.8 s (was 18.5–30 s before the first sentence).
- The voice uses half the logical cores (2–8 threads) instead of a fixed 4.
- While the voice is still loading the label says "Loading Cortana's voice…" instead of staying silent; `GET /api/status` adds `voiceReady`.
- The next sentence is synthesised while the current one plays again (1.5 waited for each sentence), still cancellable.
- Reminder balloons run in their own thread (the loop no longer blocks ~9 s per balloon) and a failed balloon is retried after 1 then 2 minutes and given up after 3 tries, instead of every 2 seconds.
- Older-turn recap now starts exactly where the sent history ends (it skipped one message).
- The release workflow works for any `v*` tag again (1.5 hard-coded the name, body and tag `v1.5.0`).

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
