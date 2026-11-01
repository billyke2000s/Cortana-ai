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

### D-010: Hair as depth-writing cut-out, and texture validation with retry
**Why:** the hair sometimes rendered as a dark helmet with strands across the face until a refresh. The GLB marks the hair
material as blended, which also disables depth writes; the app renders it as an alpha-tested cut-out but had left
`depthWrite` off, so the draw order (which depends on GPU shader compile timing) decided which hair card won. Fix:
`depthWrite = true`, normal blending, `alphaToCoverage` for smooth edges. Separately, a WebP texture can occasionally fail to
decode and three.js silently renders without it, so textures are validated after load and the model is reloaded (up to 3 times).

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

### D-014: Web search without an API key by default (superseded by D-020)
DuckDuckGo instant answers + Wikipedia need no account; an optional Brave Search key adds real web results.
Scraping search engine HTML was rejected (fragile, against terms).

### D-015: Wake word by transcribing short speech bursts locally
**Why:** no pretrained "Hey Cortana" model exists for openWakeWord; transcribing bursts with the Whisper already installed
works now with no training. **Cost:** CPU use in noisy rooms; slower than a dedicated model (roadmap).

### D-016: Optional Tailscale for a stable phone link
**Why:** Cloudflare Quick Tunnels change on every launch. Tailscale gives a private, stable HTTPS name; the token persists
in that mode only. **Cost:** requires Tailscale on both devices; [Unverified] on hardware.

### D-017: The 3D model lives in the repository; the repository is private
**Why:** the app is built around the rigged Cortana model, so the repo should build and run complete. The model is a
fan-made Microsoft character, so the repository stays private and the model isn't published anywhere else.

### D-019: Recommend and restrict models by detected hardware
**Why:** users shouldn't guess which model their GPU can run, or download 17 GB they can't use. Thresholds come from
measurements on an 8 GB RTX 3070 (9B ≈ 94% on the GPU → ~21 tok/s, acceptable) with 1.5 GB reserved for Windows and the
browser. Too-big models are refused server-side, not just hidden. On first run, an already-installed usable model is
preferred over forcing a large download. **Cost:** estimates, not benchmarks; VRAM used by games at that moment isn't considered.

### D-020: Keyless web search from Bing RSS / DuckDuckGo HTML, plus reading the top page (supersedes D-014)
**Why:** the owner wants real web answers (news, scores, prices) without an API key; D-014's instant answers + Wikipedia
couldn't do that. Bing's RSS feed is structured XML (robust to parse); DuckDuckGo's HTML results page is the fallback.
Snippets often lack the answer, so the first readable result page is fetched and trimmed to the most relevant text.
Verified from a Windows machine with real requests (GitHub live-check workflow). **Cost:** neither endpoint is an official,
documented API; they can change, rate-limit or block, which would degrade search to Wikipedia (the live check shows it).
Page text is untrusted (prompt injection) and marked so; only public addresses are fetched.

### D-021: Weather card built in code, not by the model
**Why:** whether the model wrote a `[[SCREEN]]` for weather was random, so the forecast sometimes appeared and sometimes didn't.
`get_weather` now produces the card itself from the data every time; the prompt tells the model to just speak a summary.

### D-022: Chat in the holo panel, wake-word decision on the PC
Chat moved from a browser `<dialog>` into the shared panel so every page looks the same; displays become cards in the chat.
The wake-word match moved from a page regex to `runtime.wake_match` so it can be unit-tested and fuzzy (Whisper's spellings vary).

### D-023: Documents searched with BM25 in Python; summaries from sampled parts
**Why:** a 6,144-token context can't hold a whole document. Keyword ranking (BM25) over ~900-character pieces needs no
embedding model download and works well for "what does the brief say about X". Summaries ask the local model for 2-3
sentences from up to 8 evenly spaced parts and cache the result. **Cost:** search is by words, not meaning (synonyms can
miss); summaries of very long documents are sampled, and the tool says so. pypdf (BSD-3) added with the owner's approval.

### D-024: Screen and clipboard via fixed PowerShell/ctypes, read by Qwen's vision
**Why:** Qwen 3.5 accepts images at every size (ollama.com/library/qwen3.5), so the model already installed can read a
screenshot, with no extra download. The screenshot is taken by a fixed script (no model text in the command), scaled to 1280 px wide
(~1,200 image tokens), and sent in a separate request so it never sits in the chat history. **Cost:** primary screen only.

### D-025: Cortana keeps her own events; one-tap "Add to Google Calendar"
**Why:** writing to Google needs OAuth and a Google Cloud project (D-013). The owner chose local events with 10-minute
reminders plus a Google "add event" link per event. Google iCal events also get 10-minute reminders (checked every 5 minutes).
**Cost:** an event isn't in Google until the user taps the link once.

### D-026: Tool results above 2,500 characters for reading tools
`RESULT_LIMIT`: web search 3,500, documents 3,200, clipboard 3,500. Estimated worst case at 6,144 with 18 tool schemas
(characters/4): prompt with 40 facts and the document list ~1,150 + schemas ~1,660 + full history ~1,500 + one 3,500-char
result ~950 ≈ 5,260, leaving ~880 tokens for the reply in that worst case (typical replies are 50-300). Shorter tool
descriptions were tried to save ~140 tokens, but the real 4B model then skipped tools twice in 11 asks (it invented a weather
report and a document summary), so the tested descriptions were kept. Re-measure before adding tools or raising limits.

### D-027: Weather questions are answered from data fetched before the model runs
**Why:** measured on `qwen3.5:4b` with the real prompt: it skipped `get_weather` and invented a London forecast in 1 of 2
runs, and still in 2 of 4 runs with an extra "call get_weather" hint. A made-up forecast looks real, so this can't be left to the model.
`runtime.weather_question()` spots weather questions and the place ("in/for/at <place>", else the home town); the app calls
`get_weather` first and gives the model the real result as if it had called the tool. Measured after: 4 of 4 answers used the
given data (7°C, sleet). **Cost:** a regex decides what is a weather question (e.g. "rainbow" is excluded); an unusual
phrasing falls back to the model's own tool choice.

### D-018: No voice cloning of third parties
The project supports training a Piper voice only from the owner's (or a consenting person's) recordings.

### D-028: Optional reference speech, fast Piper retained

The owner requested the supplied experimental Halo-style reference candidate in this existing repo/release. This scopes an exception to D-018 and AGENTS voice/recording rules for the existing `app/voice-profile/reference.wav`; it does not change the trainer consent requirement or authorise unrelated recordings. It does not assert an official licence or endorsement. No trained weights or source recording collection is committed.

ZipVoice-Distill int8 + Vocos (roughly 185 MB model files) is the closer tested candidate, CPU only, 8 steps. It can skip words, is slower than Piper and is not claimed to be 1:1. Stock Piper remains the fast default; Windows remains a fallback. A Piper training pilot was unfinished and is not shipped as a completed model. Source: https://k2-fsa.github.io/sherpa/onnx/tts/zipvoice.html . ZipVoice and sherpa-onnx are Apache-2.0; Vocos is MIT (notices bundled).

### D-029: Local audio alignment and keyword gate

Rhubarb 1.14 phonetic recognition supplies nine audio-aligned mouth poses; it is an estimate, not perfect phoneme alignment. Envelope fallback remains usable without the download. The 3.3M English sherpa keyword model gates Whisper; negative speech no longer needs a full transcription. Interruption requires the detector, plus browser echo cancellation and recognised-echo rejection. Real-room false triggers remain unverified.

### D-030: Bounded memory, cancellable turns, background reminders

Rank up to 12 facts/1,800 chars by query terms and recency. Keep fact conflicts visible for explicit editing instead of deleting facts heuristically. Recap is extractive (≤800 chars) and reduces the existing history allowance, so context does not grow. IDs group chat/speech cancellation; active native chunks may finish but output is discarded. Reminders have a native-delivery flag separate from browser acknowledgement. Clear History increments a version checked atomically when saving an exchange.

### D-031: Unpack once, warm up, never block on reminders

Voice and keyword archives are unpacked once; a `.unpacked` marker written after a successful unpack proves it finished, so an interrupted unpack is redone. Installed Rhubarb is reused without re-hashing its zip. The reference voice generates one short phrase at startup because the first generation after loading is several times slower. Threads = half the logical cores, 2–8. The client again requests each sentence's audio as soon as it arrives (the server lock still serialises synthesis; lip alignment and decoding overlap). Windows balloons run in a thread with 1- and 2-minute retries and stop after three failures; the in-app alert is independent. The recap offset is 15 because the model already sees the 15 newest earlier messages.

### D-032: Deep thinking on request, context sized to the graphics card

Thinking stays off by default because it delays the first spoken word. It turns on per message (Chat toggle, or phrases such as "think carefully" / "take your time"), with extra output budget for reasoning: at 6,144 tokens only what is left after a full prompt (~4,900), at most 2,800. Auto context uses the 9B measurement (0.3 GB of cache at 6,144 tokens) scaled linearly and only grows when the model **and** the cache fit on the graphics card; a card that already spills the model keeps 6,144 because a bigger cache would push more of the model onto the processor. Steps stop at 16,384 to stay near tested sizes. Every request for a model uses the same `num_ctx` so Ollama never reloads it between chat and helper calls.

### D-033: Proactive notices reuse the alert path

New documents, finished downloads and the daily briefing are stored as items of kind `notice`/`briefing` (due now) so the existing status-poll announcement, Windows balloon, retry/backoff and acknowledgement all apply unchanged; `items()` hides them from Objectives. Watchers only look at folders the user already shared with Cortana (Documents folders) plus, opt-in, the top level of Downloads (file names only, never contents). The first run after an upgrade records what already exists, so nobody gets a flood of notices. Downloads must be unchanged for 15 s and not use a partial-download extension. A briefing missed by more than three hours is skipped rather than read at night.
