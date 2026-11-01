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

Actions → **Live check (search + wake word)** → Run workflow. Runs `tests/ci_live_check.py`: real keyless searches, and
"Hey Cortana" phrases spoken by Windows text-to-speech into the real whisper.cpp. Fails if an engine returns nothing or a phrase is misjudged.

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
