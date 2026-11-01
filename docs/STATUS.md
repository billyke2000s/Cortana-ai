# Status

_Last updated: 1 November 2026._

## Agent abilities development verification

Implemented on feature/agent-abilities; not yet a released executable. Local checks: **95 offline tests passed** with office/media dependencies, real browser form control/review/stale-reference checks passed, and six UI sizes passed Abilities/Activity preferences plus existing history/rig/memory checks. Local protocol fixtures exercised actual MCP initialization/session/catalog/call and CalDAV REPORT/reviewed PUT. External production accounts/devices are **[Unverified]**.

Cross-platform CI is in progress. The first pass exposed tmpfs output collection and a Windows fixture accessibility issue; neither is counted as passed. Updated checks also launch the real packaged app and exercise office/PDF vision/browser dependencies. Record final CI outcomes here before claiming a release. Existing voice limitations remain unchanged.

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
- The small keyword detector gates Whisper once ready. Before installation/failure, idle wake requests retain Whisper fallback.
- 9B runs partly on the CPU when other GPU apps (games) are open; switch to Fast (4B) in Systems.
- Cloudflare Quick Tunnels are a development service with no uptime guarantee; a new QR appears on every launch.

## Roadmap

1. Verify all [Unverified] items on Windows; fix what breaks.
2. Train and install the owner's own Piper voice (voice trainer).
3. Check native reminder visibility with different Windows notification settings.
4. Refine the estimated mouth poses and assess them against real speech.
5. Streaming the Windows-voice fallback per sentence with lower latency.
6. Validate the small keyword detector and playback echo rejection with real microphones.
7. Optional: more abilities (music service, smart-home) behind the same allow-list rules.
