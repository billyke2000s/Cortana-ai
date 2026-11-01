# HTTP API

Base URL: `http://127.0.0.1:<port>` on the PC, or the paired tunnel URL on a phone. All responses are JSON unless noted.

## Access rules (apply to every endpoint)

- **Local** (Host `localhost`/`127.0.0.1`, no proxy headers): always allowed.
- **Remote** (phone): Host must equal the tunnel host **and** the `cortana_session` cookie must match. Otherwise: `403` HTML pairing page (GET) or `403 {"error"}` (POST).
- **POST**: `Content-Type: application/json` required (`415`); `Origin`, if present, must equal this host (`403`); body size 1–64,000 bytes (1,500,000 for `/api/transcribe`) (`400`).
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
 "alerts": [{"id": 3, "kind": "timer", "text": "pasta"}]}
```
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

### `POST /api/speech`
`{"text": str (1–3000 chars), "rate": -1|0|1}` → `{"audio": "<base64 WAV>", "voice": str, "visemes": [{"time": s, "duration": s, "id": 0-21}]}`.
`visemes` is `[]` for Piper (the client derives mouth movement from the audio).

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
Any subset of: `model` (`[\w.:/-]{1,80}`), `voice_engine` (`piper`|`windows`), `voice` (must be in the catalog),
`home_location` (≤80 chars), `calendar_url` (`https://…` or `""` to disconnect), `brave_key`, `pc_controls` (bool),
`tools_enabled` (bool), `phone_access` (`cloudflare`|`tailscale`, applies next launch). → `{"ok": true}`.

## Briefing

### `GET /api/briefing`
`{"items": [...open objectives], "weather": {place, now:{summary,temp_c,feels_like_c,wind_kmh}, days:[{date,summary,high_c,low_c,rain_chance_pct}]} | {"error"} | null, "events": {"day", "events":[{title,time,location}]} | {"error"} | null}`
Weather is cached for 10 minutes; the calendar for 5.

## Static files

Only: `/`, `/index.html`, `/app.js`, `/pages.js`, `/avatar.js`, `/mic-worklet.js`, `/responsive.css`, `/manifest.webmanifest`,
`/app-icon.svg`, `/assets/*`, `/vendor/*`. Anything else, and any path containing `..`, returns `404`.
