# Decision records

Each record: the decision, why, and what it costs. Never rewrite an old record; add a new one that supersedes it.

### D-001: Local-first: Ollama + whisper.cpp + Piper on the user's PC
**Why:** privacy, no subscriptions, works offline after setup. **Cost:** needs a capable GPU; first-run downloads.

### D-002: A browser page served by a local Python process, not a native UI
**Why:** the same interface works on the PC and a phone; three.js for the hologram; no frontend build tooling.
**Cost:** two runtimes (Python + browser); audio needs a user gesture; the mic needs HTTPS or localhost.

### D-003: Qwen 3.5 9B by default, 4B as automatic fallback and "Fast" option
**Why:** on an RTX 3070 the 9B gives noticeably better answers and still streams ~21 tok/s (≈5× speech speed).
Both choose tools correctly. **Cost:** ~1.5 GB of the 9B runs on the CPU next to Windows; slower when games use the GPU.

### D-004: Context 6,144 tokens with fixed budgets
Measured worst case at 4,096: tools ~850 + prompt with 40 facts ~1,100 + history ~1,250 + tool result ~625 = ~3,825,
leaving ~270 tokens for the reply, and overflow silently drops the **start** of the prompt. 6,144 costs ~30% speed on the
9B (30 → 21 tok/s) but removes the risk. Budgets: history 6,000 chars, tool result 2,500 chars, output 1,200 tokens.

### D-005: Stream replies as NDJSON and speak sentence by sentence
**Why:** time to first spoken word drops from "whole reply + whole audio" to "first sentence + its audio". NDJSON is
trivial to produce with `http.server` and to read with `fetch` streams; works through the tunnel.
**Cost:** sentence splitting heuristics (abbreviations, decimals); speech synthesis is serialised.

### D-006: `[[SCREEN]]` marker, with code/table fallback
**Why:** code and tables read aloud are useless. A plain-text marker is easy for small models and survives streaming.
Small models forget it, so fenced code and table rows are diverted anyway. **Cost:** prompt space for the format example.

### D-007: Tools via Ollama's native tool calling
**Why:** both Qwen sizes produce correct structured calls (tested). **Cost:** ~850 tokens of schemas per request.

### D-008: Piper (C++ release 2023.11.14-2) as one long-running `--json-input` process
**Why:** natural voices, CPU-friendly, runs as a downloaded binary (keeps the exe small), loads the voice once.
`--json-input` writes one WAV per line and prints its path, which was verified in Piper's source.
**Cost:** the path is printed just before the file is closed, so we wait for a complete WAV. No viseme output (see D-009).

### D-009: Lip sync from audio loudness for Piper
**Why:** Piper reports no mouth shapes; loudness + zero-crossing per 45 ms gives convincing movement with no extra model.
**Cost:** not phoneme-accurate. The Windows voice keeps its real viseme events.

### D-010: Validate textures after loading the 3D model and retry
**Why:** a WebP texture occasionally failed to decode on first load, and three.js silently rendered the hair as solid
geometry. Detecting the missing map and reloading (up to 3 times) fixes it without a refresh.

### D-011: SQLite for all local state
**Why:** standard library, single file, safe with a lock across server threads, survives restarts.

### D-012: Pairing cookie `SameSite=Lax` (supersedes the original `Strict`)
**Why:** the QR link is opened from a camera/scanner app, which is a navigation initiated outside the site. Browsers don't send
`SameSite=Strict` cookies on such navigations or their redirects, so the app answered "Open Cortana using the QR code".
Reproduced in Chromium; fixed with `Lax`. **Security:** POSTs remain protected by the Origin check, `HttpOnly` and `Secure`
are kept, and the token is random per launch (Cloudflare mode).

### D-013: Calendar via the private iCal address instead of Google OAuth
**Why:** OAuth for a desktop app needs a Google Cloud project, a consent screen and token refresh, which is too much for a personal tool.
The secret iCal URL is read-only and works with any calendar app. **Cost:** the URL is a bearer secret; it is stored only
locally and never returned by the API.

### D-014: Web search without an API key by default
DuckDuckGo instant answers + Wikipedia need no account; an optional Brave Search key adds real web results.
Scraping search engine HTML was rejected (fragile, against terms).

### D-015: Wake word by transcribing short speech bursts locally
**Why:** no pretrained "Hey Cortana" model exists for openWakeWord; transcribing bursts with the Whisper already installed
works now with no training. **Cost:** CPU use in noisy rooms; slower than a dedicated model (roadmap).

### D-016: Optional Tailscale for a stable phone link
**Why:** Cloudflare Quick Tunnels change on every launch. Tailscale gives a private, stable HTTPS name; the token persists
in that mode only. **Cost:** requires Tailscale on both devices; [Unverified] on hardware.

### D-017: The 3D model and Halo assets are not in the repository
**Why:** the repo is public; the model is a fan port of a Microsoft character with an unverified licence. The app degrades
gracefully without it, and repo artwork is original.

### D-019: Recommend and restrict models by detected hardware
**Why:** users shouldn't guess which model their GPU can run, or download 17 GB they can't use. Thresholds come from
measurements on an 8 GB RTX 3070 (9B ≈ 94% on the GPU → ~21 tok/s, acceptable) with 1.5 GB reserved for Windows and the
browser. Too-big models are refused server-side, not just hidden. On first run, an already-installed usable model is
preferred over forcing a large download. **Cost:** estimates, not benchmarks; VRAM used by games at that moment isn't considered.

### D-018: No voice cloning of third parties
The project supports training a Piper voice only from the owner's (or a consenting person's) recordings.
