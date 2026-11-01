# Instructions for AI assistants

**Read [`AGENTS.md`](AGENTS.md) in the repository root before doing anything.** It is the single source of truth for working on
this project: golden rules, file map, API contracts, security rules, checklists and known pitfalls.

Minimum before you finish any change:

1. `python -m unittest discover -s tests -v` passes.
2. You followed the relevant checklist in AGENTS.md §10.
3. You report what you ran, what you could not verify (Windows-only features, real GPU, phone, microphone), and label it **[Unverified]**.

This repository contains the Cortana 3D model and **must stay private**. Never commit voices, recordings, databases, logs or secrets. Never weaken the security rules in AGENTS.md §4.
