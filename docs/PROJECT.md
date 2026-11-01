# Project

## Goal

A personal, Jarvis-style voice assistant with a holographic interface that runs **entirely on the user's own PC**,
can be used from a phone, and feels fast, natural and genuinely useful.

## Principles (in priority order)

1. **Private by default.** AI, speech, voice and memory stay on the PC. Network use only for abilities the user invokes.
2. **Never break trust.** No silent actions on the PC beyond a fixed allow-list; no secrets exposed; honest about uncertainty.
3. **Feels alive.** Streaming speech, lip sync, a responsive hologram, a fast first spoken word on the target PC (the experimental reference voice prioritises similarity and does not meet a one-second target).
4. **Works for a non-programmer.** One `.exe`, automatic downloads, plain-English errors, sensible defaults.
5. **Hard to break.** Small modules, contracts, tests, and AGENTS.md rules so humans and AI agents can extend it safely.

## Target setup

Windows 10/11 · NVIDIA RTX 3070 (8 GB) class GPU · 16 GB RAM · Chrome/Edge · optional Android/iPhone over HTTPS.

## Non-goals

- Cloud AI or accounts. (A user may point `CORTANA_OLLAMA_URL` elsewhere, but it isn't supported.)
- Running arbitrary commands, reading files, or controlling apps beyond the allow-list.
- General-purpose voice cloning or adding unrelated recordings. The owner-requested 1.5 reference profile exception is scoped in AGENTS.md §16 and D-028.
- macOS/Linux builds (the test suite runs there; the app's Windows features don't).
- Multi-user accounts. One PC, one owner; the phone is a paired screen.

## Roadmap

See [STATUS.md](STATUS.md#roadmap).
