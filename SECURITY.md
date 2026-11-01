# Security

## Reporting

This is a personal project. Report issues privately to the repository owner via GitHub (Security → "Report a vulnerability"
if enabled) rather than in a public issue.

## What we protect

| Asset | Where |
|---|---|
| Conversations, remembered facts, objectives | `%LOCALAPPDATA%\CortanaAI\cortana.db` |
| Calendar secret address, Brave key | same database (never sent to the page) |
| Phone pairing token | memory (Cloudflare mode) or database (Tailscale mode) |
| The PC itself | PC controls, file system, processes |

## Threat model

| Threat | Mitigation |
|---|---|
| Someone on the internet finds the tunnel URL | Every request needs the pairing cookie; unpaired requests get a pairing page (403). The token is 32 random bytes (`secrets.token_urlsafe`), compared in constant time. |
| A malicious website makes the user's browser call the API (CSRF) | Every POST requires `Content-Type: application/json` and a matching `Origin`; the cookie is `SameSite=Lax` (not sent on cross-site POSTs) and `HttpOnly`. |
| A paired phone obtains pairing material | `/api/phone` and `/api/phone-qr` answer only local requests. |
| Path traversal / reading source, database or logs | Static files are an explicit whitelist; `..` is refused; Python files, `*.db` and logs are never served. |
| Prompt injection via web/calendar content makes the AI act | Tools can only do the listed things; PC controls are a fixed allow-list (no shell, no file access); websites must be http(s); everything can be switched off in Systems. |
| Model or tool output injects HTML/JS into the page | All text is escaped before Markdown formatting; `textContent` elsewhere; no raw HTML passthrough. |
| Malicious downloads | GitHub release SHA-256 digests and Piper voice MD5s are verified when available; archives are checked for path traversal before extraction. |
| Secrets leak via the API or logs | Settings API returns booleans for secrets; secrets aren't logged. |
| Search results point at the PC or home network (SSRF) | `tools.fetch` only reads public http(s) addresses; every redirect is re-checked. |
| A web page tries to instruct the model (prompt injection) | Page text is marked untrusted in the tool result; tools that change things are limited to the allow-lists. |
| Screen/clipboard contents leak | Screenshots and copied images go only to the local Ollama in memory (temp file deleted at once); never stored, logged or sent online. Off switch: *Screen, clipboard and file access*. |
| The model opens or runs something harmful | `open_file` takes a **number** from the last search results, never a path; programs, scripts and shortcuts are refused (`files.EXECUTABLE`). |
| A paired phone reads arbitrary PC folders | Adding folders to Documents is allowed only from the PC itself; phones can upload single files they already have. |
| Malicious document text (prompt injection) | Treated as data; the tools that change things are limited to the fixed allow-lists above. |
| Wake word sends audio elsewhere | Audio goes only to the local `/api/transcribe`; opt-in interruptions use echo-cancelled audio; recognised playback echo is rejected. |
| The AI changes files or sends things on its own (1.6) | Anything that changes the PC (create a file, tidy a folder, open an email draft) waits for the user's Approve or spoken "yes" (`tools.CONFIRM`; `run()` refuses without approval; ids are random, one-use, 10-minute). Files go only to Documents\\Cortana with sanitised names and are never overwritten; tidying only moves loose files inside Downloads/Desktop/Documents and never deletes; email is a draft the user sends. |
| Full access is misused (1.7, owner request) | Off by default; only the PC can switch it on; its tools are never offered to a paired phone and its actions can only be approved on the PC, and only while it is still on. Each command is shown exactly before it runs (120 s limit); each mouse/keyboard task is approved once and ends after 15 steps, when the user moves the mouse, or on Stop. Everything run is appended to `full-access.log`. The model is told never to type passwords or payment details. **Residual risk:** an approved command or task runs with the user's full rights, and a small model can misread the screen; approve carefully. |
| OpenJarvis brain (1.8) | Opt-in, switched and configured only on the PC; the address must be loopback (`openjarvis.check_url`), so conversations never leave the PC; the optional API key is stored like other secrets and never returned. Phone requests never reach it. Its approval queue can only be decided on the PC. OpenJarvis's server refuses `shell_exec` (needs interactive confirmation). Windows-MCP is added only with Full access on and with PowerShell, Registry, FileSystem and Process disabled. **Residual risk:** Windows-MCP's click/type tools run without a Cortana approval card (Windows-MCP shows its own edge glow and hands control back when the user moves the mouse); OpenJarvis's other tools follow OpenJarvis's own rules. |
| Arithmetic used to run code | `calculate` evaluates a parsed expression tree limited to numbers, arithmetic and a few maths functions; no names, attributes or calls beyond those. |
| Pictures attached to a question leak | Validated as PNG/JPEG/WebP (≤2, ≤1.8 MB), sent only to the local model for that question, never stored or logged. |
| Watchers read too much | Only folders already added to Documents, and (opt-in) file **names** at the top of Downloads. |
| Large or malformed requests | Size limits (64 KB; 4 MB for chat with pictures; 1.5 MB for audio), JSON validation, message count and length limits. |

## Known residual risks

- Anyone who sees the QR code (or a screenshot of it) can pair until the next restart in Cloudflare mode, or indefinitely in
  Tailscale mode (delete `phone_token` from the database to rotate). Keep it private.
- Local processes on the PC can reach `127.0.0.1` without pairing (by design: the PC is trusted).
- Cloudflare terminates TLS for the tunnel, so traffic is visible to Cloudflare. Use Tailscale if that matters.
- `webbrowser.open` will open any http(s) URL the model chooses when asked to open a website.

## Rules for contributors

See [AGENTS.md §4](AGENTS.md#4-security-rules-non-negotiable). Any change touching `server.py` auth, cookies, the whitelist,
tools or downloads must keep the corresponding tests in `tests/test_offline.py` passing and update this file.

## 1.5 speech and reminder additions

Downloads add only fixed GitHub release URLs for k2-fsa/sherpa-onnx TTS/vocoder/KWS and DanielSWolf/rhubarb-lip-sync, pinned by SHA-256 in `neural.py`/`lips.py`. Tar extraction rejects traversal, links and special files. No audio or reference is sent to a remote inference service. The bundled reference lives outside the static whitelist.

Cancellation IDs are random per browser and validated; authenticated clients retain the existing access model. Telemetry holds only bounded timing numbers, no text. Native notification text is passed on stdin to fixed PowerShell source, never interpolated into commands. Notification delivery can be suppressed by Windows. Wake echo rejection is best effort and needs testing with the user's speakers/microphone.
