# HTTP API

Base URL: `http://127.0.0.1:<port>` on the PC, or the paired tunnel URL on a phone. All responses are JSON unless noted.

## Access rules (apply to every endpoint)

- **Local** (Host `localhost`/`127.0.0.1`, no proxy headers): always allowed.
- **Remote** (phone): Host must equal the tunnel host **and** the `cortana_session` cookie must match. Otherwise: `403` HTML pairing page (GET) or `403 {"error"}` (POST).
- **POST**: `Content-Type: application/json` required (`415`); `Origin`, if present, must equal this host (`403`); body size 1–64,000 bytes (1,500,000 for `/api/transcribe`, 16,000,000 for `/api/documents`) (`400`).
- Errors: `400` invalid input, `403` not allowed, `404` unknown, `503` service problem. Body `{"error": "plain English message"}`.

## Pairing

### `GET /?pair=<token>` (tunnel host only)
Valid token → `303` to `/` with `Set-Cookie: cortana_session=<token>; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000`.
Invalid → `403` pairing page.

### `GET /api/phone-qr` (local only)
`image/svg+xml` QR code of the phone URL. `503` while the tunnel is starting.

### `GET /api/phone` (local only)
`{"ready": bool, "url": str|null}`

## Status

### `GET /api/status`
```json
{"timedSpeech": true, "ai": true, "transcription": true, "model": "qwen3.5:9b", "status": "Ready...",
 "canPair": true, "phoneReady": true, "error": null, "voice": "Natural voice ready.",
 "alerts": [{"id": 3, "kind": "timer", "text": "pasta"}], "chooseModel": false}
```
`chooseModel`: true on first launch while the server waits for the user to pick a model (`POST /api/models`); the PC page
opens the "Choose your AI" panel while it's true.
`alerts`: due, unannounced timers/reminders. Acknowledge each with `POST /api/objectives {"action":"ack","id":3}`.

## Conversation

### `POST /api/chat-stream`
Request: `{"messages": [{"role": "user"|"assistant", "content": str}, ...]}` (≤20 messages; the last must be `user`).
Response: `application/x-ndjson`, one event per line, flushed as generated:

```text
{"type":"tool","name":"set_timer","label":"SETTING TIMER"}
{"type":"refresh","what":"objectives"}
{"type":"sentence","text":"Done, Chief. Your pasta timer is running."}
{"type":"screen","markdown":"# Python table\n```python\n...\n```"}
{"type":"done","reply":"<all spoken text>","raw":"<model output incl. [[SCREEN]] part>"}
{"type":"error","error":"..."}            (only on failure, replaces done)
```

### `POST /api/chat` (legacy, non-streaming)
Same request. Response `{"reply": str, "screen": str, "raw": str}`.

### `POST /api/transcribe`
`{"audio": "<base64 WAV, mono, 16-bit, 16 kHz, ≤30 s>"}` → `{"text": str}`.
With `"wake": true` (wake-word bursts): Whisper gets a hint for the name and the server decides →
`{"text": str, "wake": bool, "rest": "words after the name"}`; no speech gives `wake: false` instead of an error.

### `POST /api/speech`
`{"text": str (1–3000 chars), "rate": -1|0|1}` → `{"audio": "<base64 WAV>", "voice": str, "visemes": [{"time": s, "duration": s, "id": 0-21}]}`.
`visemes` contains Rhubarb audio-aligned mouth poses for Piper/reference when alignment is ready, or `[]` for the envelope fallback; Windows uses SAPI events.

## Objectives (timers, reminders, tasks)

### `GET /api/objectives`
`{"items": [{"id", "kind": "timer"|"reminder"|"task", "text", "due": unix|null, "done": 0, "announced": 0|1, "created"}]}` (open items only).

### `POST /api/objectives`
| `action` | Fields | Effect |
|---|---|---|
| `add` | `kind`, `text`, `minutes` (timer, 0.05–1440), `at` (reminder, `YYYY-MM-DD HH:MM` or `HH:MM`) | create |
| `complete` | `id` | mark done |
| `delete` | `id` | remove |
| `ack` | `id` | mark announced (timers also complete) |

Returns the open items list.

## Memory

### `GET /api/memory`
`{"facts": [{"id", "text", "created"}], "messages": [{"id", "role", "content", "created"}]}` (last 60 messages).

### `POST /api/memory`
`{"action": "add", "text"}` · `{"action": "forget", "id"}` · `{"action": "clear_history"}` → same shape as GET.

## Settings

### `GET /api/settings`
```json
{"model": "qwen3.5:9b", "models": ["qwen3.5:4b", "qwen3.5:9b"], "voice_engine": "piper", "voice": "en_US-hfc_female-medium",
 "voices": [{"name": "...", "installed": true, "stock": true}], "voice_status": "...", "home_location": "London",
 "pc_controls": true, "tools_enabled": true, "phone_access": "cloudflare",
 "calendar_connected": true, "brave_connected": false}
```
Secrets (`calendar_url`, `brave_key`, tokens) are **never** returned.

### `POST /api/settings`
Any subset of: `model` (`[\w.:/-]{1,80}`), `voice_engine` (`piper`|`windows`|`zipvoice`), `voice` (must be in the catalog),
`home_location` (≤80 chars), `calendar_url` (`https://…` or `""` to disconnect), `brave_key`, `pc_controls` (bool),
`tools_enabled` (bool), `pc_access` (bool: screen, clipboard, file search/open), `phone_access` (`cloudflare`|`tailscale`, applies next launch). → `{"ok": true}`.

## Models

### `GET /api/models`
```json
{"hardware": {"gpu": "NVIDIA GeForce RTX 3070", "vram_gb": 8.0, "ram_gb": 32.0, "source": "nvidia-smi"},
 "models": [{"tag": "qwen3.5:9b", "label": "Qwen 3.5 9B", "size_gb": 6.6, "rating": "good", "gpu_pct": 94,
             "note": "...", "blurb": "...", "selectable": true, "installed": true, "recommended": true, "moe": false, "quality": 4}],
 "current": "qwen3.5:9b", "recommended": "qwen3.5:9b",
 "pull": {"active": false, "tag": null, "status": "", "pct": 0, "error": null},
 "disk_free_gb": 210.4, "other_installed": ["llama3:8b"]}
```
`rating`: `fast` (fits on the GPU) · `good` (≥80% on the GPU) · `slow` (≥60%) · `too_big` (not selectable).
Catalog tags that don't exist in the Ollama library are omitted.

### `POST /api/models`
`{"action": "download", "tag"}` starts a background download (refused if too big, already installed, another download is
running, or the disk is too full), then switches to it. `{"action": "use", "tag"}` switches to an installed, selectable model.
Poll `GET /api/models` for `pull` progress. `POST /api/settings {"model"}` applies the same rules.

## Briefing

### `GET /api/briefing`
`{"items": [...open objectives], "weather": {place, now:{summary,temp_c,feels_like_c,wind_kmh}, days:[{date,summary,high_c,low_c,rain_chance_pct}]} | {"error"} | null, "events": {"day", "events":[{title,time,location,source:"Cortana"|"Google",id?}]} | {"error"} | null}`
Weather is cached for 10 minutes; the calendar for 5. `events` merges Cortana's own events (with `id`) and the Google iCal calendar.

## Documents

### `GET /api/documents`
`{"documents": [{id, name, path|null, pages|null, chars, added, summarised}], "folders": [str], "canAddFolder": bool}`; `canAddFolder` is true only on the PC.

### `POST /api/documents`
- `{"action":"add","name":"brief.pdf","data":"<base64>"}` → `{"added":{id,name,pages,chars},"documents":[...]}`. Folders in `name` are dropped. PDF, .docx, .pptx and text types only; same name replaces the old copy.
- `{"action":"add_folder","path":"C:\\…"}` (**PC only**, `400` from a phone) → `{"added_count", "skipped":[names], "documents"}`. Up to 80 files, 4 levels deep, ≤40 MB each.
- `{"action":"remove","id":3}` → `{"documents":[...]}`.

## Events

### `GET /api/events`
`{"events": [{id, title, start, end, created}]}`: Cortana's upcoming events (UNIX times).

### `POST /api/events`
`{"action":"remove","id":3}` → `{"events":[...]}`.

## Static files

Only: `/`, `/index.html`, `/app.js`, `/pages.js`, `/avatar.js`, `/mic-worklet.js`, `/responsive.css`, `/manifest.webmanifest`,
`/app-icon.svg`, `/assets/*`, `/vendor/*`. Anything else, and any path containing `..`, returns `404`.

## Companion additions (1.5.0)

- `GET /api/conversation` → `{messages:[{id,role,content,created}],summary:str}`; last 60 messages and an extractive older-turn recap (≤800 characters).
- `POST /api/chat-stream` and `/api/speech` accept optional `request_id` (1–100 ASCII letters/digits/underscore/hyphen). Existing payloads remain supported.
- `POST /api/cancel {request_id}` → `{ok:true}`. A cancelled ID stays cancelled for one hour, including queued speech. Streaming ends with an error; cancelled speech returns 503. Completed tools are not rolled back.
- `POST /api/metrics {playback_ms:number}` (0–600000) → `{ok:true}`. Status adds `latency` (milliseconds), `wakeDetector`, `lipSync`, `voiceReady` (false while the chosen voice loads), `expressionMode`, `choosePersonality`; alerts add `due`.
- `POST /api/transcribe` with `wake:true` runs the small keyword detector first. A negative burst avoids Whisper. `interrupt:true` additionally requires the detector (no Whisper-only interruption fallback).
- Settings GET/POST add `expression_mode` (`normal` default / `expressive`), `setup_complete` (boolean, false default), `native_notifications` (boolean, true default); `voice_engine` adds `zipvoice`. Unknown values are rejected.
- `GET /api/memory` adds `conflicts`, an array of potentially conflicting fact-ID groups. `POST /api/memory {action:"edit",id,text}` replaces one existing fact (1–300 chars).
- `POST /api/objectives {action:"snooze",id,minutes:10}` re-arms a timer/reminder for 1–1440 minutes. GET adds `recent_alerts`: at most 20 acknowledged timers from the last day. Items have additive `notified` state.
- `voice-profile/*`, Python modules, downloaded weights and temporary audio are never static web files. All additions keep the existing auth/origin/JSON/size guards.

## 1.6 additions

- `POST /api/chat-stream` accepts optional `think` (boolean, default false). Thinking also turns on when the question asks for it ("think carefully about…", "take your time"). The stream then starts with `{type:"tool",name:"think",label:"THINKING IT THROUGH"}`; the model's reasoning is never streamed or spoken.
- Settings GET/POST add `context_mode` (`auto` default / `standard`); GET also returns `context`, the token window in use.
- Settings GET/POST add `briefing_time` (`"HH:MM"` or `""`, default empty), `watch_folders` (boolean, default true) and `watch_downloads` (boolean, default false).
- `alerts` in `GET /api/status` can now include `kind:"notice"` (spoken as-is: new document, finished download) and `kind:"briefing"` (the page opens Mission Briefing and reads it). Both are acknowledged like other alerts and never appear in `GET /api/objectives`.
- Stream event `{type:"confirm",id,label,summary,detail}`: an action is waiting for approval (create a file, tidy a folder, open an email draft). Nothing has happened yet.
- `POST /api/confirm {id:str, approve:bool}` → `{ok, say, result?, refresh?}`. Runs (or drops) the held action once; ids expire after 10 minutes; unknown/expired ids → 400.
- `POST /api/chat-stream` accepts optional `images`: up to 2 base64 PNG/JPEG/WebP pictures (≤1.8 MB each) for the current question only; the request limit is 4 MB only when pictures are attached (64 KB otherwise). Pictures are never stored.
- Stream `confirm` events add `name` (the tool). `computer_task` cards can be stopped with `POST /api/cancel {request_id:"task_<id>"}` (between steps).
- Settings GET/POST add `full_access` (boolean, default false). POST is refused from a paired phone; `run_command`/`computer_task` approvals via `POST /api/confirm` are refused unless they come from the PC.
