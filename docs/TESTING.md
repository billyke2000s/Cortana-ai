# Testing

## 1. Offline suite (required for every change)

```bash
python -m unittest discover -s tests -v
```

- Runs on any OS in ~1 second. No GPU, Ollama, internet or Windows needed (`python-dateutil` is needed for the calendar test, which skips otherwise).
- `tests/fake_ollama.py` imitates Ollama's streaming `/api/chat` (including tool calls), `/api/tags` and `/api/generate`.
- The voice is stubbed with silent audio; the data folder is a fresh temporary directory.

| Group | What it proves |
|---|---|
| `SpokenStreamTests` | sentence splitting, abbreviations/decimals, `[[SCREEN]]` split (even across chunk boundaries), code and tables never spoken, Markdown stripped |
| `StoreTests` | settings, fact de-duplication/forgetting, due alerts and acknowledgement rules |
| `ToolTests` | every tool's success and failure paths, `HH:MM` reminders, past times refused, unknown tools never raise, PC control switch |
| `CalendarTests` | iCal parsing: escaped text, all-day, weekly RRULE, EXDATE, cancelled events, ordering |
| `HardwareTests` | model recommendation per card size, too-big models unselectable, low RAM blocks spilling, unknown tags hidden |
| `DocumentTests` | PDF/Word/PowerPoint/text extraction (real generated PDF), search finds the right page, summaries per part + cache, replace/remove, document names in the prompt |
| `PcAccessTests` | file search (age/kind filters, skipped folders), programs never opened, open only by number, read into documents, screen/clipboard via the model (stubbed capture), the off switch |
| `EventTests` | weekday/time resolution, event + 10-minute reminder + Google link + card, Google events reminded once |
| `WakeWordTests` | Whisper's spellings of the name trigger; ordinary speech and look-alikes ("Montana", "contain") don't |
| `WebSearchTests` | Bing RSS + DuckDuckGo HTML parsing (ads skipped, links decoded), fallback order, page text extraction, size budget, private addresses refused |
| `WeatherDisplayTests` | every weather answer yields the forecast card; spoken part has no table symbols |
| `ApiTests` | status, streaming with and without tools, screen events, memory reaching the prompt, objectives API, settings validation, **secrets never returned**, **cross-origin POST blocked**, **private files not served**, **phone pairing (SameSite=Lax regression)**, model download/use guards and progress |

## 2. Live check (Windows, real services)

```powershell
dist\Cortana.exe --port 8777        # or: python app/launcher.py --port 8777
python tests/live_check.py          # CORTANA_URL=http://127.0.0.1:8777 by default
```
Checks the real Ollama, Whisper, voice, tunnel pairing and the new endpoints. Writes `live-check-report.json`.
Needs the phone tunnel to be up (don't use `--no-tunnel`). The transcription round-trip is skipped when Piper is the voice (22 kHz ≠ 16 kHz).

## 2b. Live check on GitHub (Windows, internet, no GPU)

Actions → **Live check (search + wake word)** → Run workflow. Two jobs:
- **live** (Windows): `tests/ci_live_check.py`, real keyless searches; "Hey Cortana" phrases spoken by Windows text-to-speech into the
  real whisper.cpp; screenshot capture, clipboard round trip, and file search in the real Documents folder.
- **model** (Linux, CPU): installs Ollama + `qwen3.5:4b` and runs `tests/ci_model_check.py`: tool choice for 11 asks with the
  real prompt and schemas, and reading an error from an image. (9B is too slow on a CPU runner; check it on the PC.)

## 2c. Release smoke test (automatic)

`release.yml` starts the built `dist\Cortana.exe --headless --no-open --no-tunnel --port 8777` on Windows and runs
`tests/exe_smoke.py`: page, scripts, 3D model, `/api/models` hardware detection and reading a PDF. The release is only
published if it passes.

## 3. Real-model prompt check (whenever the prompt or tool schemas change)

Against Ollama with the real `SYSTEM_PROMPT` and `TOOLS`, for **both** `qwen3.5:9b` and `qwen3.5:4b`:

| Ask | Expected |
|---|---|
| "Set a timer for 10 minutes for the pasta" | `set_timer {minutes: 10, label: pasta}` |
| "Remember that my dog is called Max" | `remember` with a third-person fact, no invented names |
| "How do I build a table in Python?" | short spoken line, `[[SCREEN]]`, fenced code; no code in the spoken part |
| "Remind me to call mum at 6pm" | `set_reminder {at: "18:00"}` |
| "What's the weather in London?" | `get_weather {place: London}` |
| "Pause the music" | `pc_control {action: play_pause}` |
| "Tell me a joke" | a joke, no refusal |

## 4. UI check (Playwright/Chromium)

Viewports: 320×568, 360×640, 390×844, 430×932, 844×390. Verify: panel above nav and face visible; pages open from tiles
and nav; add/complete/delete objectives; memory add/forget; settings save; display panel Copy; no console errors.

## 5. Manual checklist (Windows release)

- [ ] First launch on a clean data folder: Ollama/model, Whisper, Piper and voice download; window shows QR.
- [ ] Mic: question → spoken streamed reply; mouth moves with Piper audio.
- [ ] "Set a 1 minute timer" → chime + spoken alert; Objectives updates live.
- [ ] "How do I build a table in Python?" → display panel with Copy.
- [ ] "Pause the music" / "volume down" act on the PC; unticking PC controls stops them.
- [ ] Systems: switch 9B ↔ 4B; switch voices; Windows voice; save home town → Briefing weather.
- [ ] Calendar: paste the secret iCal address → today's events; Disconnect works.
- [ ] Phone: scan QR from the camera app → app loads (not the pairing page); mic works over HTTPS.
- [ ] Wake word: "Hey Cortana, what time is it?" answers; no self-trigger while she speaks.
- [ ] Reload several times: hair and textures always correct.
- [ ] Close the window: Piper, cloudflared and an Ollama the app started all exit.

## Companion release checks (1.5)

- Offline: `tests/test_companion.py` covers old-schema migration, fact retrieval/edit/conflicts, recap budget, history-clear race, snooze delivery state, cancellation isolation, tar traversal/links, mouth cues, and all new endpoint guards.
- Browser: `python tests/browser_check.py` checks six sizes, setup/Systems preferences, restored chat and memory edits with the real HTTP service and fake Ollama/silent voice.
- Real models: `python tests/ci_context_check.py qwen3.5:4b`, then `qwen3.5:9b` (already pulled into Ollama). Exercises timer, memory, code screen, clock reminder, joke and old-fact recall with recap enabled.
- Windows: `python tests/ci_native_check.py`; synthetic SAPI wake/no-wake examples plus notification subprocess success. This cannot prove visual balloon delivery.
- Built exe: `tests/exe_smoke.py URL`, then `tests/release_voice_check.py URL`; reference voice must generate real audio and aligned poses, cancelled IDs must be rejected, Windows fallback must still speak. Publication waits for all CI jobs.
- Manual: compare Normal/Expressive, try voice previews and arbitrary paragraphs, interrupt with speakers and with headphones, close the browser before a reminder, reopen/snooze, restart while a reminder is overdue. Voice identity and real-room echo cannot be established by silent/browser or synthetic tests.
