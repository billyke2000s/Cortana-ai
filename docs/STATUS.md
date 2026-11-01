# Status

_Last updated: 1 November 2026._

## Verified

| Area | How it was verified |
|---|---|
| Streaming chat with tools, screen events, memory in prompt, objectives/memory/settings APIs, security rules | Offline suite (46 tests, incl. model recommendations, first-launch model choice, wake-word matching, keyless search parsing, weather card) |
| QR pairing from a scanner app | Reproduced the failure in Chromium over HTTPS with a cross-site link, fixed (`SameSite=Lax`), re-tested; regression test added |
| Tool choice and `[[SCREEN]]` format | Real `qwen3.5:9b` and `qwen3.5:4b` on an RTX 3070 with the real prompt and schemas |
| 9B speed | ~30 tok/s at 4,096 context, ~21 tok/s at 6,144 (≈5 GB of 6.3 GB on the GPU alongside Windows) |
| UI pages, panel placement, alerts, wake-word pipeline (stand-in recogniser), lip sync from audio | Playwright/Chromium at phone sizes against the real server + fake Ollama |
| Hair/texture recovery | Deliberately corrupted texture on first load → detected, reloaded, rendered correctly |
| Weather and search endpoints | Called from the PC's browser; response shapes match the code |
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
- Google Calendar with a real secret address.
- GPU detection on real hardware (`nvidia-smi` / registry), the `qwen3.5:35b-a3b` tag name, real model downloads from the picker.

## Known issues / limitations

- Alerts only fire while a Cortana page is open (PC or phone). No Windows toast notifications yet.
- Keyless search uses unofficial endpoints (Bing RSS, DuckDuckGo HTML): they may change or rate-limit. JavaScript-only pages (e.g. live scores) can't be read, so she answers from snippets there.
- Piper lip sync is loudness-based, not phoneme-accurate.
- The wake word transcribes every speech burst with Whisper on the CPU, so expect CPU use in noisy rooms.
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
