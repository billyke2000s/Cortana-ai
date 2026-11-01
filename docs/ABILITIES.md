# Agent abilities

Open **Systems → Abilities, connections and Activity**. Chat also has **Activity and files**. Speak normally: Qwen chooses tools from meaning and conversation context. Examples illustrate possibilities; they are not activation phrases. Small models can still choose incorrectly, ask for clarification or fail; tool results determine what actually happened.

| Area | Available work | Setup or limit |
|---|---|---|
| Browser | Navigate, read pages, inspect controls, fill/select, click, tabs, download | Dedicated persistent Microsoft Edge profile on Windows; sign in manually in that browser. Password fields stay manual. Review external submissions. Public HTTP(S) pages only; no arbitrary JavaScript tool. |
| Files | List/read, create/append, copy/move, recoverable removal, duplicates, organisation proposals | Default workspace; add/revoke other folders on the PC. Individual changes ≤12 MB. Undo refuses to overwrite newer edits. Folder organisation proposes moves; the AI applies chosen individual moves. |
| Documents | Real DOCX/PDF with title, headings, paragraphs, bullets, tables | Downloads in Chat/Activity; generated output is reopened before success. This does not preserve an arbitrary existing document's full layout. |
| Spreadsheets | CSV/XLSX read/write, numeric analysis, compare rows, embedded bar/line charts | Up to 10,000 rows/100 columns. Column indices start at zero. Excel must recalculate formulas; this is not a full Excel calculation engine. External/DDE formulas are refused. |
| Python | Run, inspect exit status/stdout/stderr and return generated files | Docker Desktop, Linux containers, `docker pull python:3.12-slim`. Standard library only; no network or host shell fallback. Missing Docker is an error, not simulated execution. |
| Missions | Plan, work across categories, record progress/evidence and blockers | At most 18 model rounds, 4 calls/round, 15-minute mission deadline checked between calls. Existing per-call timeouts remain. Stop prevents subsequent calls; completed actions remain. |
| Windows apps | Observe windows/accessibility controls, focus, invoke or set a control's value | Fresh observed references; review actual actions. Elevated and custom-drawn apps may not expose controls. Inspect again to verify an invoked button's effect. |
| Diagnostics | Actual hardware, free disk, top processes and recent Application/System errors | Read only. Windows-only process/log probes use fixed PowerShell. |
| Vision | Compare up to three images, read scanned PDF pages/diagrams, sample video frames | Upload in Abilities or use approved folders. Local Qwen vision. PDF page numbers start at one; video frames need FFmpeg on PATH. No native audio, image or video generation is implied. |
| Email | List inbox, read, create local drafts, reviewed send | IMAP TLS plus SMTP TLS. Provider app password or existing OAuth access token; automatic OAuth refresh is not included. SMTP acceptance does not prove delivery. |
| External calendar | Read next seven days; reviewed CalDAV event creation, with reminder | Configure a CalDAV collection; provider app password/token may be required. Google/Outlook can alternatively be exposed through an authenticated MCP provider. Existing local events/iCal/link flow remains. |
| Home/music | States, lights/switches/scenes, media play/pause/next/volume/play media | Home Assistant URL/token and entities, or an MCP service. No automatic lock/alarm actions. No Spotify account is connected by default. |
| Plugins | Discover and call real tools on a configured MCP server | Streamable HTTP 2025-11-25 family, JSON/SSE, initialization/session support. No arbitrary plugin-process installer or stdio execution. A 2026-only server needs a compatible provider endpoint. |
| Scheduled work | One-off/repeating natural-language goals, stable folder-change goals | Launcher must stay open. One background mission at a time, defer while foreground work runs. Folder polling ≈10 s, then a stability interval. Offline changes are not replayed as file events. Sends still need review. |
| Reasoning/context | Fast or Deep; hardware-rated 6,144/8,192/16,384/32,768 context | Conservative estimates, not a live VRAM benchmark. Default 6,144 on an 8 GB card. Deep is slower and keeps hidden reasoning out of speech. |

## Connect a service

On the **PC**, choose a short connection name, then paste settings into the connection JSON field. The API never returns saved credentials. Disconnect/reconnect to replace them. Credentials and browser login sessions are stored locally; protect your Windows account and backups.

```json
{"type":"mcp","url":"http://localhost:8000/mcp","token":"YOUR_TOKEN"}
```

By default, MCP calls require review. To trust specific read-only calls, add an explicit `read_tools` array of exact tool names after checking that server. Server annotations alone do not grant that trust. Run/install the MCP provider separately, using its own authentication instructions. Its catalog supplies the actual supported calendar/music/other actions.

```json
{"type":"caldav","url":"https://calendar.example.com/calendars/user/main","username":"user","password":"APP_PASSWORD"}
```

```json
{"type":"email","imap":"imap.example.com","smtp":"smtp.example.com","smtp_port":465,"username":"user@example.com","password":"APP_PASSWORD"}
```

For a provider supporting IMAP/SMTP OAuth, replace `password` with `oauth_token`. Microsoft accounts require modern authentication; an ordinary password is not a substitute. Tokens can expire. Use an OAuth-managing MCP provider if you need managed sign-in/refresh.

```json
{"type":"home_assistant","url":"http://192.168.1.20:8123","token":"LONG_LIVED_ACCESS_TOKEN"}
```

## Review, files and recovery

Activity shows the exact recipient/body or action/fields awaiting approval. Approve runs that stored action once; Deny leaves it unrun. Reviews expire after ten minutes, and changed browser fields or connection settings invalidate approval. Review is independent of whatever wording the model uses. Ask Cortana to continue if the larger task has more steps.

Download a result in Chat or Activity. **Use this** makes an Activity file the current target for follow-up requests. Multiple plausible targets should prompt clarification. Undo is per file action and requires the file still to match the action's recorded hash; it does not undo emails, external events or arbitrary application actions.

Tool results, files, pages, mail and plugins are untrusted data. Review reduces risk but does not make a language model immune to prompt injection. Connecting a service can send selected request data to that service. AI/voice inference remains local.
