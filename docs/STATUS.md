# Status

_Last updated: 1 November 2026._

## 1.5 current verification

- Recovered source: 80 offline tests passed on Linux; JavaScript syntax checks passed.
- Earlier implementation in this session: browser layout passed at 320×568, 360×640, 390×844, 430×932, 844×390, 1280×900; saved chat and memory edit passed. Re-run required after recovery.
- Actual CPU reference speech produced 24 kHz audio and 11/30 Rhubarb mouth cues in two test sentences. One sentence skipped the name Cortana. Warm long-sentence render was 7.36 s; cold shorter render including model load was 31.21 s. These are observations, not guarantees.
- A separately generated Piper “Hey Cortana” sample triggered the small keyword detector; an unrelated reference sentence did not.
- Windows rebuilt-exe speech/alignment/cancellation, native keyword checks and real 4B/9B context regression are release gates; pending until their Actions run succeeds.
- **[Unverified]** real microphone/speaker echo rejection, subjective voice/animation quality, visible Windows balloon delivery and phone microphone. Native synthesis may finish its current chunk after Stop.

## Previously verified (through 1.4)

| Area | How it was verified |
|---|---|
| Streaming chat with tools, screen events, memory in prompt, objectives/memory/settings APIs, security rules | Offline suite (62 tests, incl. model recommendations, first-launch model choice, wake-word matching, keyless search parsing, weather card, documents, file search, screen/clipboard via stubs, events) |
| QR pairing from a scanner app | Reproduced the failure in Chromium over HTTPS with a cross-site link, fixed (`SameSite=Lax`), re-tested; regression test added |
| Tool choice and `[[SCREEN]]` format | Real `qwen3.5:9b` and `qwen3.5:4b` on an RTX 3070 with the real prompt and schemas |
| 9B speed | ~30 tok/s at 4,096 context, ~21 tok/s at 6,144 (≈5 GB of 6.3 GB on the GPU alongside Windows) |
| UI pages, panel placement, alerts, wake-word pipeline (stand-in recogniser), lip sync from audio | Playwright/Chromium at phone sizes against the real server + fake Ollama |
| Hair/texture recovery | Deliberately corrupted texture on first load → detected, reloaded, rendered correctly |
| Weather and search endpoints | Called from the PC's browser; response shapes match the code |
| Model tags and image input | ollama.com/library/qwen3.5 (1 Nov 2026): tags 0.8b, 2b, 4b, 9b, 27b, 35b, 122b; **every size takes text and image input** |
| **Built `Cortana.exe` starts and works** (v1.4.0) | Release workflow launches the real exe on Windows (`tests/exe_smoke.py`): page, scripts, 3D model, hardware detection (no-GPU path), PDF reading via bundled pypdf |
| Screenshot, clipboard, file search on Windows | GitHub Windows runner: screenshot captured (261 KB PNG), clipboard text round trip incl. "✓", `find_files` found a file in the real Documents folder |
| New abilities chosen by the real model | `qwen3.5:4b` on a CPU runner with the real prompt and 18 schemas: 11/11 asks picked the right tool with correct arguments (summarise, search documents, screen, clipboard read, find PDF from last week, book Thursday 15:00, timer, reminder 18:00, weather, joke, code on screen) |
| Reading a screenshot | `qwen3.5:4b` read "NameError: name 'totl' is not defined" exactly from a 1280×720 image |
| Chat attach, files/event cards, Memory → Documents, Copy, links | Playwright/Chromium with fake Ollama; `javascript:` links are not made clickable |
| Keyless web search | GitHub Windows runner, real requests: Bing and DuckDuckGo both returned results; top page read for 3 of 4 queries (BBC Sport scores page gave no readable text) |
| Wake word with real Whisper | Windows text-to-speech → whisper.cpp v1.8.2 base.en with the hint → `wake_match`: 4/4 wake phrases detected, 3/3 look-alikes ignored (synthetic voice, not a real mic) |
| Chat page, weather card every time | Playwright/Chromium (phone + desktop) with fake Ollama: weather asked 4 times → card every time, in Chat and outside it |
| Calendar parsing | Unit tests (repeats, all-day, time zones, exceptions) |

## Not yet verified [Unverified]

- The rebuilt `Cortana.exe` (build with the new modules, tzdata/dateutil bundling).
- Piper on Windows: download, `--json-input` process, real speech quality and latency.
- PC controls (Windows key events, `os.startfile`).
- Tailscale mode (`tailscale serve --bg PORT`, Host header behaviour).
- Wake word with a real microphone and your voice, in a real room (only synthetic speech tested); phone microphone over the tunnel.
- Whether the real Qwen models follow the new "don't write a screen for weather" line (the card shows regardless).
- New abilities on **`qwen3.5:9b`** (only 4B was run, on a CPU) and on your real GPU; screen reading of a real screen through the full app.
- Tool choice varies between runs. Repeated check on 4B (each ask twice): the 6 new abilities 12/12; a code question once missed the `[[SCREEN]]` marker (the app's code fallback still moves fenced code to the display); weather was invented in 1 of 2 runs, so weather is now fetched before the model answers (D-027), after which 4/4 answers used the real data. The model can still embellish slightly ("tomorrow looks the same").
- Adding a whole folder on a real PC with many large PDFs (time taken); scanned PDFs have no text to read.
- Opening a found file with its default app (`os.startfile`) through the full app.
- Google Calendar with a real secret address.
- GPU detection on real hardware (`nvidia-smi` / registry), real model downloads from the picker.

## Known issues / limitations

- Native reminders now attempt Windows balloons while the launcher runs; visible delivery depends on Windows settings and still requires desktop verification.
- Keyless search uses unofficial endpoints (Bing RSS, DuckDuckGo HTML): they may change or rate-limit. JavaScript-only pages (e.g. live scores) can't be read, so she answers from snippets there.
- Neural lip sync uses estimated Rhubarb poses when ready; envelope fallback remains. It is not perfect phoneme alignment.
- The small keyword detector gates Whisper once ready. Before installation/failure, idle wake requests retain Whisper fallback.
- 9B runs partly on the CPU when other GPU apps (games) are open; switch to Fast (4B) in Systems.
- Cloudflare Quick Tunnels are a development service with no uptime guarantee; a new QR appears on every launch.

## Roadmap

1. Verify all [Unverified] items on Windows; fix what breaks.
2. Train and install the owner's own Piper voice (voice trainer).
3. Windows toast notifications for alerts when no page is open.
4. Phoneme-accurate lip sync for Piper (alignment output).
5. Streaming the Windows-voice fallback per sentence with lower latency.
6. Custom "Hey Cortana" model (openWakeWord) to replace transcribe-every-burst.
7. Optional: more abilities (music service, smart-home) behind the same allow-list rules.
