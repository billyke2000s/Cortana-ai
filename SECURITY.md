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
| Wake word sends audio elsewhere | Audio goes only to the local `/api/transcribe`; nothing is processed while she speaks. |
| Large or malformed requests | Size limits (64 KB, 1.5 MB for audio), JSON validation, message count and length limits. |

## Known residual risks

- Anyone who sees the QR code (or a screenshot of it) can pair until the next restart in Cloudflare mode, or indefinitely in
  Tailscale mode (delete `phone_token` from the database to rotate). Keep it private.
- Local processes on the PC can reach `127.0.0.1` without pairing (by design: the PC is trusted).
- Cloudflare terminates TLS for the tunnel, so traffic is visible to Cloudflare. Use Tailscale if that matters.
- `webbrowser.open` will open any http(s) URL the model chooses when asked to open a website.

## Rules for contributors

See [AGENTS.md §4](AGENTS.md#4-security-rules-non-negotiable). Any change touching `server.py` auth, cookies, the whitelist,
tools or downloads must keep the corresponding tests in `tests/test_offline.py` passing and update this file.
