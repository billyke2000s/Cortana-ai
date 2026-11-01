# AGENTS.md: rules for AI agents (and humans) working on Cortana

> **Read this whole file before changing anything.** It is the single source of truth for how to work on this project.
> `CLAUDE.md`, `GEMINI.md` and `.github/copilot-instructions.md` point here. If any other instruction in the repo
> conflicts with this file, this file wins; if the **user** asks for something that conflicts with it, say so and ask.

Rules use **MUST / MUST NOT / SHOULD**. A MUST is not optional. When a rule seems to block a legitimate task, stop and
ask the user. Do not work around it.

---

## 0. The ten golden rules

1. **Read before you write.** Open and read every file you will change, and the files that call it. Never edit from memory or from a summary.
2. **Run the offline tests before and after every change:** `python -m unittest discover -s tests -v`. They MUST pass. A change that breaks a test is not done, even if the feature "works".
3. **Never claim something works unless you ran it.** Say exactly what you ran and what you could not run (Windows-only parts, real GPU, phone, microphone). Label anything unverified as **[Unverified]**.
4. **Never weaken security** (§4): pairing, origin check, file whitelist, escaping, tool allow-lists, secrets. No exceptions "for testing".
5. **Never commit voices, recordings, databases, logs, secrets or build output** (`.gitignore`), and **never make this repo public** (it contains the 3D model, §5).
6. **Keep the contracts** in §3 (stream events, `[[SCREEN]]` marker, API shapes, settings keys). If you must change one, change every producer and consumer, the tests and `docs/API.md` in the same change.
7. **Smallest change that solves the problem.** No drive-by refactors, renames, reformatting or dependency additions. Preserve working features.
8. **Every new web file, Python module or setting has a checklist** (§10). Missing one step = broken `.exe`.
9. **Update the docs that describe what you changed** (§12) and add a `CHANGELOG.md` entry.
10. **When unsure, ask.** A question costs seconds; a wrong guess can cost the user's data or trust.

---

## 1. What this project is (30-second orientation)

A Windows desktop app (`Cortana.exe`, built with PyInstaller) that runs a local web server and opens a browser page with a
3D holographic assistant. The PC does everything (Ollama LLM, whisper.cpp speech recognition, Piper voice, SQLite
storage, tools); a phone can open the same page through a paired HTTPS tunnel. See `docs/ARCHITECTURE.md`.

**Runtime facts you must not forget**

- Target OS: **Windows 10/11**. Build and Windows features (PowerShell voice, `ctypes.windll` keys, `os.startfile`, `CREATE_NO_WINDOW`) only work there. Tests run anywhere.
- Python **3.11+** (the shipped exe used 3.14). Standard library only for the app, plus `qrcode`, `python-dateutil`, `tzdata`.
- The frontend is **plain ES modules, no build step, no framework, no npm**. three.js is vendored in `app/vendor/`.
- Data folder: `%LOCALAPPDATA%\CortanaAI` (override: `CORTANA_DATA_DIR`). Ollama URL override: `CORTANA_OLLAMA_URL`. Model override: `CORTANA_MODEL`.

---

## 2. File map: who owns what

| File | Responsibility | Never put here |
|---|---|---|
| `app/launcher.py` | Entry point. Creates `Runtime` and `AppServer`, starts startup thread (voice, AI, STT, tunnel), Tk window with QR. | Business logic, HTTP handling |
| `app/server.py` | **The only HTTP surface.** Auth (`authorised`, `local`), file whitelist, all `/api/*` routes, NDJSON streaming, settings/objectives/memory actions, briefing. | Model calls, tool logic |
| `app/runtime.py` | `Runtime`: Ollama/Whisper/tunnel lifecycle, model selection & fallback, `SYSTEM_PROMPT`, `system_prompt()`, `SpokenStream`, `chat_stream()`, `transcribe()`. Also download/extract helpers and QR. | HTTP parsing, UI strings for pages |
| `app/tools.py` | `TOOLS` (schemas the model sees), `TOOL_LABELS`, `CHANGES`, `run()` dispatcher, weather/search/PC/calendar implementations. | Anything that runs arbitrary commands |
| `app/store.py` | SQLite schema and all reads/writes (settings, facts, messages, items). | Network, model calls |
| `app/hardware.py` | GPU/RAM detection (`nvidia-smi`, then the display-adapter registry), `CATALOG` of Qwen models, `rate()`/`recommend()`. | Network calls, UI |
| `app/voice.py` | Piper install, voices, the long-running `PiperProcess`, Windows voice fallback via `speech.ps1`. | Chat logic |
| `app/speech.ps1` | Windows SAPI voice with viseme (mouth) events. | n/a |
| `app/index.html` | Markup + base CSS for the main screen and dialogs. Loads `avatar.js`, `app.js`, `pages.js` as modules **in that order**. | Inline scripts with logic |
| `app/app.js` | Core client: state machine, `send()` (stream reader), `SpeechQueue`, `envelopeCues`, mic `listen()`, wake word, alerts, display panel (`showPanel`/`showScreen`, Markdown renderer), navigation, status polling. Exposes `window.Cortana`, `window.CortanaDisplay`. | Page-specific UI |
| `app/pages.js` | Chat, Mission Briefing, Objectives, Memory, Systems and first-launch model chooser pages, rendered into the display panel. Exposes `window.CortanaPages`. | Core state logic |
| `app/avatar.js` | three.js scene, model load + texture validation/retry, rig animation, visemes → mouth. Exposes `window.CortanaAvatar`. | Network calls other than the model/rig |
| `app/responsive.css` | Phone-first layout overrides, display panel, pages styling. | n/a |
| `app/mic-worklet.js` | AudioWorklet that posts 2048-sample Float32 chunks. | n/a |
| `build/build_cortana.py` | PyInstaller command (data files, hidden imports). | n/a |
| `tests/test_offline.py` | Offline suite. `tests/fake_ollama.py` simulates Ollama. `tests/live_check.py` checks a running app. | n/a |

---

## 3. Contracts: change only with every consumer updated

### 3.1 Chat stream: `POST /api/chat-stream` → NDJSON (one JSON object per line)

| `type` | Fields | Producer | Consumer behaviour (`app.js send()`) |
|---|---|---|---|
| `sentence` | `text` | `SpokenStream` | appended to transcript, queued for speech |
| `tool` | `name`, `label` | tool loop | label shown while thinking |
| `refresh` | `what`: `"objectives"` or `"memory"` | tool loop (`tools.CHANGES`) | dispatches `cortana:refresh` so open pages re-render |
| `screen` | `markdown` | after stream ends | opens display panel |
| `done` | `reply`, `raw` | last event | history stores `raw` (keeps the model's own format) |
| `error` | `error` | server on exception | client throws; shows message |

Rules: `done` is always last on success. Never send HTML in any field. Never add a type without handling it in `app.js`.

### 3.2 The `[[SCREEN]]` marker

The model speaks a short summary, then writes a line `[[SCREEN]]`, then Markdown for the display panel starting with `# Title`.
`SpokenStream` MUST also divert any fenced code block or Markdown table row into the screen even without the marker
(small models forget). The spoken part MUST be passed through `speakable()`. Changing the marker text means changing
`SCREEN_MARK`, the prompt, the prompt's example, the tests and the docs together.

### 3.3 Tools

- A tool = schema in `TOOLS` + label in `TOOL_LABELS` + branch in `run()` + (if it changes data) entry in `CHANGES` + a test.
- `run()` MUST NEVER raise; it returns `(result_dict, change_or_None)`; errors are `{'error': '...'}` in plain English.
- Results are JSON-serialisable, short (they are truncated to 2,500 chars before going back to the model), and contain no secrets.
- Schema descriptions are prompts: keep examples **neutral** (never a real person's name; see §14 #9).

### 3.4 Status: `GET /api/status`

Keys the client relies on: `ai`, `transcription`, `timedSpeech`, `model`, `status`, `canPair`, `phoneReady`, `error`, `voice`, `alerts`.
`alerts` = due, unannounced timers/reminders `{id, kind, text}`; the client acknowledges with `POST /api/objectives {action:"ack"}`.

### 3.5 Settings keys (SQLite `settings` table)

`model`, `voice_engine` (`piper`|`windows`), `voice`, `voice_engine_failed`, `home_location`, `calendar_url` (**secret**),
`brave_key` (**secret**), `pc_controls`, `tools_enabled`, `phone_access` (`cloudflare`|`tailscale`), `phone_token` (**secret**, Tailscale mode only), `port`.
`GET /api/settings` MUST NEVER return a secret; it returns booleans (`calendar_connected`, `brave_connected`).

### 3.6 Speech

`POST /api/speech` returns `{audio: base64 WAV, voice: str, visemes: [{time, duration, id}] | []}`. Empty `visemes` means
the client derives mouth shapes from loudness (`envelopeCues`). Viseme ids follow the SAPI set mapped in `avatar.js poseFor()`.

### 3.7 Client globals

`window.Cortana` (`speak, stop, send, api, state, wake, setWake`), `window.CortanaDisplay` (`show, hide, render, panel, esc, page, body`),
`window.CortanaPages` (`open(target)` → bool), `window.CortanaAvatar` (`ready, setState, setFull, setCharacter, startSpeech, extendSpeech, stopSpeech, inspect`).
Don't rename them; other modules and tests use them.

---

## 4. Security rules (non-negotiable)

1. **All requests go through `Handler.authorised()`.** Local = Host is `localhost`/`127.0.0.1` **and** no `CF-Connecting-IP`/`X-Forwarded-Host` header. Remote = Host equals `runtime.tunnel_host` **and** a valid `cortana_session` cookie (constant-time compare). MUST NOT add another way in.
2. **Every POST** MUST pass the Origin check (`Origin` absent or equal to this host) and require `Content-Type: application/json` and a size limit. Do not exempt new endpoints.
3. **The pairing cookie is `HttpOnly; Secure; SameSite=Lax`.** It MUST NOT become `Strict` (breaks QR scanners; see `docs/DECISIONS.md` D-012) or lose `HttpOnly`/`Secure`. A test enforces this.
4. **Pairing material is PC-only:** `/api/phone-qr` and `/api/phone` MUST refuse non-local requests.
5. **Static files are a whitelist** in `Handler.do_GET`. Python files, the database and logs MUST NEVER be served. New web files are added explicitly (§10.1), never by widening to "any file".
6. **Never put untrusted text into `innerHTML`.** Model output, tool results, settings and memory MUST go through `holoEsc`/`CortanaDisplay.esc` or `textContent`. The Markdown renderer escapes first, then adds tags. Don't add raw-HTML passthrough.
7. **Tools never execute arbitrary input.** No `subprocess`/`os.system`/`eval` with model-provided strings. PC controls are a fixed map (`APPS`, `VK`); websites must be `http(s)` and opened with `webbrowser.open`. Adding an app means adding a fixed entry.
8. **Secrets** (`calendar_url`, `brave_key`, `phone_token`, pairing token) MUST NEVER be logged, returned by the API, put in URLs other than their own request, committed, or shown in screenshots.
9. **Network access** only to: Ollama (local), the download sources in `runtime.py`/`voice.py` (GitHub releases, Hugging Face `rhasspy/piper-voices`, whisper.cpp model), Open-Meteo, Bing (RSS results feed), DuckDuckGo (instant answers + HTML results page), Wikipedia, the public pages of search results (read by `tools.fetch`, which refuses private/loopback addresses and redirects to them), Brave Search (only with a key), the user's calendar URL, and the tunnel. Adding a host = update `SECURITY.md` and ask the user.
10. **Downloads** MUST be verified (SHA-256 from the release digest, or the MD5 from `voices.json` for voices) when a checksum exists, and archives MUST be extracted with `extract()` (path-traversal check).
11. **The wake word only processes audio locally** and ignores audio while Cortana is speaking. Never send audio anywhere except the local `/api/transcribe`.

---

## 5. Legal & ethical rules

1. **This repository contains the Cortana 3D model (`app/assets/cortana.glb`) and MUST stay private.** Never make it public, fork it publicly, or publish the model, its textures or renders of her elsewhere.
2. **Voices:** only voices the user owns or has explicit permission to use. MUST NOT add features, scripts or docs for cloning a third party's voice (e.g. a game character's voice actor) from recordings. The voice trainer's consent checkbox stays.
3. **Screenshots** in the repo show the real interface with her on the hologram stage; regenerate them when the UI changes.
4. Keep the trademark disclaimer in `README.md`. Don't add Microsoft/Halo logos.
5. Respect licences of anything added (three.js is MIT, keep `THREE-LICENSE.txt`). Record new third-party code in README credits.

---

## 6. Python backend rules

1. Standard library first. A new third-party package needs the user's approval **and** `requirements.txt` + `build/build_cortana.py` (`needed` dict + `--hidden-import`) updates.
2. Use the existing helpers: `request_json`, `download`, `extract`, `Runtime.update`/`report`, `Runtime.spawn` (tracks children for shutdown).
3. **Every subprocess** on Windows uses `creationflags=HIDDEN` and a timeout, and is either short-lived or registered in `runtime.children`.
4. **Never hold a lock across a `yield`.** Streaming generators must not keep `ai_lock` or any lock while yielding (a disconnected client would deadlock the app). `stream_events()` closes the generator in `finally`.
5. **The context budget is real.** `CONTEXT=6144` tokens must hold: system prompt (+ up to 40 facts) + tool schemas (~850 tokens) + history (`clean_messages(budget=6000)` chars) + tool results (2,500 chars each) + the reply (`num_predict=1200`). If you grow any of these, re-measure (see `docs/DECISIONS.md` D-004). Overflow silently drops the **start** of the prompt (her personality and rules).
6. **Prompt changes MUST be tested on the real models** (`qwen3.5:9b` and `qwen3.5:4b`) with at least: a timer, "remember…", "how do I build a table in Python?", a reminder with a clock time, "tell me a joke". Report results. Small models follow **examples** better than rules.
7. Model fallback: if the preferred model is missing or fails to load or stream, use `FAST_MODEL`. Don't remove this.
7a. **Models:** never let the user switch to or download a model rated `too_big` (`Runtime.check_model` enforces this server-side; the UI only mirrors it). New models go in `hardware.CATALOG` with their real Ollama download size; keep thresholds in sync with `docs/DECISIONS.md` D-019 and `HardwareTests`. GPU detection must never crash startup (every probe is wrapped and falls back to "no GPU").
8. Errors shown to users are plain English (`RuntimeError('…')`). Don't leak tracebacks, paths or exception reprs into the UI.
9. Times: store UNIX timestamps (float, local clock); format with `when_text()`. The model gives reminders as `HH:MM` (today/tomorrow resolved by `parse_local_time`) because small models get dates wrong.
10. SQLite: all access through `Store` methods (they hold the lock). Schema changes MUST be additive (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE … ADD COLUMN` guarded), never destructive. Existing users' databases must keep working.
11. Keep `split_reply`, `chat()` (non-streaming wrapper) and `/api/chat` working; older tools and the live check use them.

---

## 7. Frontend rules

1. **No build step, no frameworks, no CDN imports at runtime** (the app works offline; fonts from Google are cosmetic and optional). New libraries go in `app/vendor/` with their licence.
2. **Module order:** `avatar.js`, then `app.js`, then `pages.js`. `pages.js` may use `window.Cortana*` from `app.js`; `app.js` must not depend on `pages.js` existing (use optional chaining: `window.CortanaPages?.open`).
3. **Temporal dead zone:** any `const`/`let` used by functions that can run early (`setState`, `idleLabel`, `stop`) MUST be declared at the top of `app.js`. (§14 #4)
4. **Escaping:** see §4.6. Use `textContent` for plain text.
5. **`hidden` attribute vs CSS:** rules like `.holo-body input{display:block}` override `hidden`. Keep `.holo-body [hidden]{display:none!important}`. (§14 #5)
6. **Forms:** hidden inputs still take part in validation. Use `step="any"` or valid defaults; a silent invalid hidden field blocks submit with no visible error. (§14 #3)
7. **Layout:** phone-first. Check 320×568, 360×640, 390×844, 430×932 and a landscape phone. The display panel MUST stay above the bottom navigation (`placeHolo()`) and leave her face visible.
8. **Audio:** create/resume `AudioContext` only after a user gesture (`unlockAudio`). Mic needs a secure context (HTTPS or localhost). Sentences play back-to-back via `SpeechQueue`; never `await` a whole reply before speaking.
9. **Never block the UI** with `alert/confirm/prompt`. Use in-panel messages and two-tap confirms (see "Clear conversation history").
10. **Line endings:** the repo stores LF (`.gitattributes`); `.bat/.cmd/.ps1` are CRLF. When editing a file on a Windows checkout, keep its existing line endings and don't rewrite the whole file. (§14 #6)
11. **Dates from the API** like `2026-11-01` MUST be parsed as local midday (`new Date(d+'T12:00')`), not `new Date(d)` (UTC shift shows the wrong weekday west of UTC).

---

## 8. Avatar / 3D rules

1. The model is optional. Missing model, failed load, missing bones or morphs MUST degrade gracefully (message in `#modelNote`, app still works).
2. Keep the texture validation + automatic retry (`missingTextures`/`loadModel`), context-loss handlers and the `pageshow`/`pagehide` handling. They fix the "hair renders wrong until refresh" bug.
3. Mouth movement comes from `speech.cues` (time-sorted, can be appended while speaking) and `speech.duration` (`extendSpeech`). Don't replace this with per-frame network calls.

---

## 9. Voice rules

1. Piper runs as **one long-lived process** in `--json-input` mode. It prints the output path **just before the file is closed**: always wait for `wav_complete()`. (§14 #7)
2. Piper voices are 22,050 Hz; Whisper transcription requires **16 kHz mono**. Never feed TTS output straight into `/api/transcribe`. (§14 #8)
3. If Piper fails, fall back to the Windows voice for that request and set a status message; retry Piper on next launch (`voice_engine_failed` is reset in `prepare()`).
4. Speech rate maps to Piper `length_scale` via `RATE_SCALE`; changing rate restarts the Piper process (expected).

---

## 10. Checklists: follow every step

### 10.1 Adding a new web file (e.g. `app/foo.js`)
1. Create the file in `app/`.
2. Add it to the whitelist tuple in `Handler.do_GET` (`server.py`).
3. Add it to `WEB_FILES` in `build/build_cortana.py`.
4. Reference it from `index.html` (module order!).
5. Add it to `test_private_files_are_not_served`'s "served" list.
6. Run tests.

### 10.2 Adding a Python module (e.g. `app/foo.py`)
1. Import it where needed (lazy import inside functions is fine and avoids cycles: `runtime` ↔ `voice`/`store`/`tools`).
2. Add `--hidden-import foo` in `build/build_cortana.py`.
3. Confirm it is **not** in the static whitelist (Python files must never be served).
4. Add tests.

### 10.3 Adding a tool
1. Schema in `TOOLS` (neutral examples, clear "when to use").
2. Label in `TOOL_LABELS`; `CHANGES` entry if it modifies objectives/memory.
3. Branch in `run()` that never raises.
4. Tests: success, bad arguments, and the off-switch if applicable.
5. If it reaches the network: §4.9. If it touches the PC: §4.7 and the `pc_controls` switch.
6. Update `README.md` ability table, `docs/SPECIFICATION.md`, `docs/API.md` (if new data appears).
7. Test the real models choose it correctly (§6.6).

### 10.4 Adding a setting
1. Read with a default via `store.get(key, default)`.
2. Validate and write in `settings_action()` (`server.py`). Reject bad input with `ValueError`.
3. Return it (or a boolean if secret) from `GET /api/settings`.
4. UI in `pages.js systems()` + `saveSystems()`.
5. Document in §3.5 here and `docs/SPECIFICATION.md`.
6. Test: round-trip and (if secret) never returned.

### 10.5 Adding an endpoint
1. GET in `do_GET` after `authorised()`; POST in `do_POST` (inherits origin/size/type checks).
2. Never return secrets. Errors via exceptions (handled centrally).
3. Document in `docs/API.md`; add a test.

### 10.6 Changing the prompt
1. Edit `SYSTEM_PROMPT` (and the example) in `runtime.py`.
2. Re-measure the context budget if it grew.
3. Run the real-model check (§6.6) on 9B **and** 4B; report the results.
4. Run offline tests.

### 10.7 Releasing
1. Offline tests pass. 2. Build on Windows (`python build/build_cortana.py`, `BUILD_EXIT 0`). 3. Launch `dist\Cortana.exe`; run `tests/live_check.py`. 4. Manual checklist in `docs/TESTING.md`. 5. `CHANGELOG.md` + `docs/STATUS.md` updated with what was and wasn't verified.

---

## 11. Testing rules

- `python -m unittest discover -s tests -v` MUST pass before you finish. Add tests for every bug you fix (a regression test that fails before the fix).
- The offline suite uses `tests/fake_ollama.py`. If you change how the backend talks to Ollama (payload fields, tool message format), update the fake **to match real Ollama behaviour**, not to make your code pass.
- Browser UI checks: Playwright/Chromium at phone sizes is the expected way to verify UI changes when available.
- "Verified" means you observed it. Unit tests passing ≠ "works on Windows". State the gap explicitly.

---

## 12. Documentation rules

| You changed… | Update |
|---|---|
| Any behaviour | `docs/SPECIFICATION.md`, `CHANGELOG.md` |
| API / stream / settings | `docs/API.md`, this file §3 |
| Structure, threads, startup, storage | `docs/ARCHITECTURE.md`, this file §2 |
| Security-relevant code | `SECURITY.md`, this file §4 |
| A significant choice or trade-off | `docs/DECISIONS.md` (new D-number, never rewrite history) |
| What's done or verified | `docs/STATUS.md` |
| Setup, build, dependencies | `docs/DEVELOPMENT.md`, `README.md` quick start |

Don't duplicate content between docs; link instead. Keep README claims true (e.g. the test count badge).

---

## 13. Git rules

- Small, focused commits with imperative messages ("Fix QR pairing cookie for scanner apps").
- Never commit: voices (`*.onnx`), recordings, `*.db`, logs, `dist/`, `build/work/`, `.env`, any secret. Check `git status` before committing.
- Don't rewrite history on `main`. Don't force-push.

---

## 14. Mistakes already made once (don't repeat them)

1. **QR pairing showed "Open Cortana using the QR code".** The cookie was `SameSite=Strict`; browsers drop Strict cookies on navigations that start in another app or site (QR scanners), so the redirect after pairing arrived without it. Fix: `SameSite=Lax`. Python HTTP clients don't enforce SameSite, so test in a real browser. → D-012
2. **Hair rendered as a dark helmet with strands across the face, varying between loads.** The GLB marks the hair as blended, which sets `depthWrite=false`; the app switched it to cut-out (`alphaTest`) but left depth writes off, so hair cards overdrew each other and the face in GPU compile order. Fix: `depthWrite=true` (+ `alphaToCoverage`). A second, rarer cause (a texture failing to decode) is handled by validating textures after load and retrying. → D-010
3. **"Add" button did nothing.** A hidden `<input type=number min=0.1 step=0.5 value=5>` was invalid (5 isn't on the step grid), so the browser blocked submit silently. Use `step="any"`.
4. **`ReferenceError` risk:** `const wake` was declared at the bottom of `app.js` but used by `idleLabel()`, called from `stop()`/`setState()`. Declare shared state at the top.
5. **Hidden inputs showed anyway:** `display:block` CSS overrode the `hidden` attribute.
6. **Whole-file diffs from line endings:** rewriting a CRLF file as LF made every line "changed". Preserve line endings.
7. **Piper race:** reading the WAV as soon as the path was printed returned a truncated file. Wait for `wav_complete()`.
8. **Sample-rate mismatch:** Piper audio (22.05 kHz) fails Whisper's 16 kHz check; the live test skips that check for Piper.
9. **Model copied a name from a tool example** ("Billy's dog…"). Tool schema examples must be neutral ("The user's dog…").
10. **Model got reminder dates wrong** (6pm today → a week later). Let it pass `HH:MM` and compute the date in code.
11. **Code read aloud:** the model put inline code in the spoken part. Fixed with a format example in the prompt + `SpokenStream` diverting code/tables + `speakable()`.
12. **Context overflow:** history + tools + results could exceed 4,096 tokens, silently cutting the system prompt. Context raised to 6,144 and budgets set. → D-004
13. **Panel covered the navigation and her face.** `placeHolo()` keeps it above the nav and below ~40% of the screen height.
14. **Weekday off by one west of UTC:** `new Date('2026-11-01')` is UTC midnight. Parse as local midday.
15. **Download race:** marking a model download `done` before switching to it let the page see "done" with the old model still active, and it stopped polling. Switch first, then mark done.
16. **Test tooling:** `pkill -f <pattern>` killed the shell running it; unquoted `*` in shell variables globbed filenames; Playwright's Chromium picked up proxy env vars. Prefer PIDs, quote arguments, unset proxies for local HTTPS tests.

---

## 15. Definition of done

- [ ] Read every touched file and its callers.
- [ ] Offline tests pass (paste the summary line).
- [ ] New/changed behaviour has tests.
- [ ] Security rules (§4) still hold; no secrets added; repo still private.
- [ ] Checklists (§10) completed for anything added.
- [ ] Docs updated (§12), `CHANGELOG.md` entry added.
- [ ] Report to the user: what changed, what you ran (results), what you could **not** verify, known issues.
