# Status

_Last updated: 1 November 2026._

## 1.8.0: verification

**Released:** [v1.8.0](https://github.com/billyke2000s/Cortana-ai/releases/tag/v1.8.0), built from `775425c26a75145e5319b0406afd0cbd9fee99a6` in Actions run 41349884894 (UI, Windows build + offline suite + packaged voice smoke, real `qwen3.5:4b` 6/6 and `qwen3.5:9b` 6/6). `Cortana.exe` SHA-256 `55a17a623e850d42c4573cfca2c7d7815fa916ffecb30144e5ce947b27f3e79f`.

- Offline suite: 149 tests on Linux, including a fake OpenJarvis server (SSE stream, model from /v1/info, system prompt, API key header, key never returned, timers kept by Cortana, fallback when not running, phone never routed, approvals on the PC only, loopback-only URL, starter config, Windows-MCP config editing with backup, unusual formats left alone, Windows control needing Full access).
- Browser check passed with the new Brain controls.
- On the owner's PC (read-only check): `~/OpenJarvis/.venv/Scripts/jarvis.exe` exists; `~/.openjarvis` has no config.toml; version-check reports 0.1.1 with 1.0.2 available.
- **[Unverified]**: the bridge against OpenJarvis 0.1.1 (its API may lack `/v1/info` or `/v1/approvals`), OpenJarvis tool quality with qwen3.5 9B, Windows-MCP under `uvx` on the owner's PC (needs uv and Python 3.14, which uvx downloads).

## 1.7.1: verification

**Released:** [v1.7.1](https://github.com/billyke2000s/Cortana-ai/releases/tag/v1.7.1), built from `426e978f280aec1aefb10f76e4487efae3a6c314` in Actions run 41345901607 (UI, Windows build + offline suite + packaged voice smoke, real `qwen3.5:4b` 6/6 and `qwen3.5:9b` 6/6 with the full-access prompt line). `Cortana.exe` SHA-256 `220cd2d82d1f48f342a64c505e5ca1025d433cac97bd653a96b9d7b6619c7132`. Offline suite: 132 tests. **[Unverified]** on the owner's PC: the blue frame, capture exclusion, cursor swap/restore, in-process capture, and whether the 9B now calls computer_task/run_command reliably.

## 1.7.0: verification

**Released:** [v1.7.0](https://github.com/billyke2000s/Cortana-ai/releases/tag/v1.7.0), built from `dd5a0abca25f288f77038549958d8a48c5ec9e78` in Actions run 41343125633 (UI, Windows build + offline suite + packaged voice smoke, real `qwen3.5:4b` 6/6 and `qwen3.5:9b` 6/6). `Cortana.exe` SHA-256 `d2f82259daaba59ae043d998e4ead50013c06b1321f43b4c4f5344cb9ed8340b`.

- Offline suite: 124 tests passed on Linux (Python 3.13), including full access (off by default, never offered to or approvable from a phone, refused if switched off after asking, exact command preview), the computer-task loop with a scripted model (actions, done, 15-step cap, mouse-moved stop, Stop/cancel, unclear replies), input validation, the crash log and old-unpack cleanup, and Whisper deciding every wake burst.
- Browser check passed (layouts, approval card, Systems with the Full access switch).
- **[Unverified]**: real mouse/keyboard input and the DPI-aware screenshot on Windows, how accurately the 9B picks click positions, real PowerShell commands, "Hey Cortana" in the owner's room, whether the crash log captures the crash the owner saw.

## 1.6.0: verification

**Released:** [v1.6.0](https://github.com/billyke2000s/Cortana-ai/releases/tag/v1.6.0), built from `b7213f79d5095ed54a483115681782e72b51e9cd` in Actions run 41337204413 (UI, Windows build + offline suite + native checks + packaged reference-voice smoke, real `qwen3.5:4b` 6/6 and `qwen3.5:9b` 6/6 on CPU runners). `Cortana.exe` SHA-256 `647e7c12de50f26b1309af51fddcd6c10ce70493c34811bb86276e6067939c61`. Later documentation commits do not change the app.

Release checks caught and fixed before publishing: doubled line breaks in CSVs written on Windows; qwen3.5:9b claiming a timer and then a reminder it never set (D-036); the spreadsheet tool being offered for "build a table in Python" (D-034). One 4B run failed only because Ollama's registry returned 503 during the model download. The 9B passing 6/6 once is one sample of a temperature-0.45 model, not a reliability figure.

- Offline suite: 116 tests passed on Linux (Python 3.13). New tests cover the voice unpack/warm-up, reminder backoff, recap offset, context sizing, deep thinking, watchers and briefing, the approval gate end to end (nothing written until approved, one use, expiry, origin/auth), every work tool, picture validation and privacy.
- Browser check (Playwright/Chromium, fake Ollama): six layouts, approval card via tap and via typed "yes", deep thinking toggle, new Systems sections, no page errors.
- **[Unverified]** everything that needs the real models or Windows: how well qwen3.5 9B/4B choose the new tools and phrase approval requests, deep-thinking quality and time, the Auto context on a real graphics card, `pc_health`'s PowerShell output, the Word file opening in Word, mailto drafts in the user's mail app, folder tidying on a real Downloads folder, Windows pop-ups for notices. The release workflow's real-model job runs only on a tag.
- Real ZipVoice on a 2-core cloud CPU (step 1): first launch load + one-time unpack + warm-up 64.9 s; second launch 9.8 s; first reply sentence 7.6–7.9 s after warm-up.

### Step 1 (speed and fixes)

- Offline suite: 86 tests passed on Linux (Python 3.13); the 6 new regression tests fail on the 1.5.0 code.
- Real ZipVoice on a 2-core cloud CPU: first launch load + one-time unpack + warm-up 64.9 s; second launch 9.8 s; first reply sentence 7.6–7.9 s after warm-up.
- **[Unverified]** timings on the owner's Ryzen 9 3900X, the release workflow on a real tag, and the Windows balloon thread on a desktop.

## 1.5 current verification

**Released:** [v1.5.0](https://github.com/billyke2000s/Cortana-ai/releases/tag/v1.5.0). All release jobs passed in [Actions run 41308294155](https://github.com/billyke2000s/Cortana-ai/actions/runs/41308294155). The published executable is built from `b85d9b48231b0f1cb321a06cc6f60f073bc2ee8e`; later documentation/screenshot updates do not change the app. Download SHA-256: `0735727b2f96e55f7ee1ddec0afecef9ef572378906b3bda7a83f75fb02eb841`.

Screenshots were refreshed from the actual interface using demo data and silent test speech. They are not evidence of subjective voice quality.

Repository metadata currently reports **public**. The docs previously described it as private; visibility was not changed by this release.

- Recovered source: 80 offline tests passed on Linux; JavaScript syntax checks passed.
- Recovered implementation re-tested: browser layout passed at 320×568, 360×640, 390×844, 430×932, 844×390, 1280×900; saved chat and memory edit passed, no page errors.
- Actual CPU reference speech produced 24 kHz audio and 11/30 Rhubarb mouth cues in two test sentences. One sentence skipped the name Cortana. Warm long-sentence render was 7.36 s; cold shorter render including model load was 31.21 s. These are observations, not guarantees.
- A separately generated Piper “Hey Cortana” sample triggered the small keyword detector; an unrelated reference sentence did not.
- Windows build and packaged smoke passed: real reference speech (24 kHz, 22 mouth cues), Windows fallback, cancelled speech rejection, page/scripts/GLB/model catalogue/PDF parsing. Native keyword tests: “Hey Cortana…” detected; “curtains…” and “Hey Montana…” rejected. Notification subprocess returned success; visible delivery still needs a desktop.
- Windows offline suite: 80 run, 79 passed and one expected Windows skip (the non-Windows PC-access error test). Linux: all 80 passed.
- Final browser checks passed on GitHub, including the actual expressive forearm movement and Normal reset, saved chat restoration, memory editing and no JavaScript page errors.
- Real `qwen3.5:4b`: 6/6 context regressions passed (timer, remember, code display, clock reminder, joke, old-fact recall). The cold `9b` CPU check exceeded the original 180-second transport timeout; the test harness now allows 900 seconds and refuses fallback. Final `qwen3.5:9b` result: **6/6 passed** with no fallback (same six cases as 4B). Cold first spoken response took about 242 seconds on the CPU runner; this is not a GPU performance measurement.
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
- Wake word: Whisper checks every speech burst (the 1.5 keyword gate was removed in 1.6.1 because it rejected real "Hey Cortana"s, D-037). Real-room reliability with the owner's microphone is still **[Unverified]**.
- 9B runs partly on the CPU when other GPU apps (games) are open; switch to Fast (4B) in Systems.
- Cloudflare Quick Tunnels are a development service with no uptime guarantee; a new QR appears on every launch.

## Roadmap

1. Verify all [Unverified] items on Windows; fix what breaks.
2. Train and install the owner's own Piper voice (voice trainer).
3. Check native reminder visibility with different Windows notification settings.
4. Refine the estimated mouth poses and assess them against real speech.
5. Streaming the Windows-voice fallback per sentence with lower latency.
6. Validate the small keyword detector and playback echo rejection with real microphones.
7. Optional: more abilities (music service, smart-home) behind the same allow-list rules and the approval gate.
8. Not built yet, on purpose (D-035): website automation (filling in forms), desktop app control by clicking/typing, running model-written code, whole multi-tool "missions" beyond the 6-step deep-thinking loop, a plugin system. Each needs a real sandbox or browser engine; revisit after the 1.6 abilities are proven on the real models.
