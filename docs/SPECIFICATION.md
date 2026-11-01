# Specification: how Cortana behaves

This describes intended behaviour. Code that disagrees with this document is a bug in one of them; fix both together.

## 1. States

The page is always in exactly one state, shown in the label under the hologram:

| State | Label | Entered when | Left when |
|---|---|---|---|
| `idle` | `TAP THE MIC TO SPEAK` (or `SAY "HEY CORTANA"` with the wake word on) | startup, after speaking, after errors, on Stop | user acts, alert fires |
| `listening` | `CORTANA IS LISTENING...` | mic tapped | ~1.2 s of silence after speech, 8 s with no speech, 29 s max, or mic tapped again |
| `thinking` | `CORTANA IS THINKING…` / tool label (e.g. `SETTING TIMER…`) / `PREPARING VOICE…` | message sent | first audio starts |
| `speaking` | `CORTANA IS SPEAKING…` | first sentence's audio starts | last queued audio ends |

Escape or the stop button returns to `idle` from any state and cancels requests and audio.

## 2. Conversation

- History restores the last 60 saved entries on reload. Last 18 are sent, last 16 fit within 6,000 characters, including up to 800 characters of older-turn excerpts (extractive recap, not a semantic summary).
- Every exchange is also saved to the local conversation log (Memory page; ≤2,000 messages kept).
- System prompt = personality and rules + current local date/time + home town + up to 12 query-ranked facts within 1,800 characters.
- Replies stream: each complete sentence (≥18 characters, or ending a line) is spoken while later ones are still being generated.
- **Speech vs screen:** the spoken part is a short summary; code, tables, steps, commands, search results and long lists go to
  the display panel. Trigger: the `[[SCREEN]]` marker, or (fallback) the first fenced code block or Markdown table row.
- Spoken text never contains Markdown symbols (`* ` # _ > |`), and Markdown links are reduced to their text.
- If the model returns only screen content, she says "I've put it on screen for you."
- Model: on first launch with the window open (no model chosen yet), Cortana starts Ollama, then **waits**: the PC page opens a
  "Choose your AI" panel listing every Qwen 3.5 model rated for this PC (recommended one starred and scrolled to, too-big ones
  disabled). The user presses Use (installed) or Download; the choice is saved and nothing loads until then. Headless runs
  (`--headless`) and `CORTANA_MODEL` skip the question and pick automatically: the **recommended** model if it's installed;
  otherwise the best installed model that isn't too big (and says which one is recommended); if none is usable, she downloads
  the recommended one. `num_ctx` 6,144 by default; **Auto** memory size uses the largest of 8,192/12,288/16,384 whose cache still fits on the graphics card next to the model (6,144 on the processor, mixture-of-experts or tight cards), and gives about half the extra room to older messages. `temperature` 0.45, up to 1,200 output tokens. **Deep thinking** (🧠 in Chat, or "think carefully about…" / "take your time") turns reasoning on and adds up to 2,800 tokens for it; the reasoning is never spoken. If the model fails to load
  or fails before producing text, she switches to `qwen3.5:4b` and retries once.
- Recommendation (`hardware.py`): usable graphics memory = total − 1.5 GB; need = download size + 0.3 GB. Fast = fits;
  Good = ≥80% fits; Slow = ≥60%; Too big = less, or the overflow doesn't fit in RAM − 6 GB (mixture-of-experts models: Good
  from 35%). Recommended = the most capable Fast/Good dense model (no GPU: 2B). Typical picks: 4 GB → 2B, 6 GB → 4B,
  8–16 GB → 9B, 20 GB+ → 27B.

## 3. Abilities (tools)

Up to 4 model rounds per message; up to 4 tool calls per round. Tool results are truncated to 2,500 characters (3,500 for `web_search`, which carries page text).

| Tool | Behaviour |
|---|---|
| `set_timer(minutes, label?)` | 0 < minutes ≤ 1,440. Creates a timer item. **A plain request with a length ("set a 10 minute timer for the pasta") is set by the app before the model answers** (`runtime.timer_request`, D-036); the model only confirms it. |
| `set_reminder(text, at? \| in_minutes?)` | **A plain request with a clear time ("remind me to call mum at 6pm", "in 20 minutes", "at 18:30 tomorrow") is set by the app first** (D-036). Otherwise: | `in_minutes` relative; `at` as `HH:MM` → next occurrence (today or tomorrow), or `YYYY-MM-DD HH:MM`. Refuses times more than 60 s in the past. |
| `add_task(text)` | To-do item, no due time. |
| `list_objectives()` | Open items with times. |
| `complete_objective(match)` | Completes up to 3 open items whose text contains all words (>2 letters) of `match`. |
| `remember(fact)` | Saves a fact (≤300 chars, case-insensitive de-duplication, ≤200 kept). |
| `forget(match)` | Deletes facts containing all words of `match`. |
| `get_weather(place?)` | **Weather questions are fetched by the app before the model answers** (`runtime.weather_question`: place after in/for/at/near, else the home town; D-027). Open-Meteo geocoding + forecast (now + 3 days). Empty place → home town; neither → asks the user. **Always** shows a forecast card (`tools.weather_screen`: now, then Today/Tomorrow/weekday with sky, high/low, rain chance), built from the data, not by the model; it replaces any model-written screen for that reply. |
| `web_search(query)` | **No key needed.** Brave (if a key is saved), else Bing's RSS results feed, else DuckDuckGo's HTML results page (ads skipped) → ≤5 results (title, snippet, source site). Then the first of the top 3 result pages that yields ≥200 characters of text is read: scripts/nav/header/footer dropped, the blocks most related to the query kept (≤1,400 chars), marked untrusted. Wikipedia fills in if fewer than 2 results. Only public http(s) addresses are fetched (redirects checked too). |
| `pc_control(action, target?, steps?)` | `play_pause`, `next_track`, `previous_track`, `volume_up/down` (1–25 × 2%), `mute`, `open_app` (allow-list: notepad, calculator, file explorer, settings, browser, spotify, task manager, paint, snipping tool), `open_website` (http/https only). Off when **PC controls** is unticked. Windows only. |
| `get_calendar(day?)` | `today`, `tomorrow` or `YYYY-MM-DD`. Cortana's own events plus the private iCal URL (if connected); expands repeats (RRULE), honours EXDATE, skips cancelled, converts time zones; all-day events first. |

| `add_event(title, day, time, minutes?)` | `day` = today/tomorrow/weekday/`YYYY-MM-DD`, `time` = `HH:MM`, resolved in code (a weekday already past today = next week). Saves a Cortana event (5 min–24 h), a reminder 10 minutes before, and returns a Google Calendar "add event" link. Card: **Event added** with **Add to Google Calendar**. |
| `search_documents(query, document?)` | BM25 over the added documents' ~900-character pieces (page/slide labelled); up to 4 pieces (≤2,600 chars). `document` narrows by name. |
| `summarise_document(document?)` | Empty = newest. ≤3,000 chars: the text itself. Longer: the model writes 2-3 sentences for each of up to 8 evenly spaced 3,000-char parts (separate requests), cached per document. |
| `look_at_screen(question)` | Primary screen captured by a fixed PowerShell script, scaled to ≤1280 px wide, sent with the question to the current model in a separate request; the image is deleted. Windows only. |
| `clipboard(action, text?)` | `read`: clipboard text (≤3,200 chars, with a note if cut); if it holds an image, the model describes it. `write`: puts text (≤20,000 chars) on the clipboard. |
| `find_files(query, kind?, days?)` | Searches file names under Desktop, Documents, Downloads, Pictures, Videos, Music and OneDrive (≤7 levels, ≤80,000 entries, ≤5 s; skips AppData, node_modules, .git…). ≥60% of the query words must match; newest first; up to 8. Card: **Files found** with folders. |
| `open_file(number, read?)` | Only a number from the last `find_files` list. Opens it with its default app, or (`read`) adds it to Documents. Programs, scripts and shortcuts are refused. |

**Work abilities (1.6)**, offered when the question is about them (or always with a large context):

| Tool | Behaviour |
|---|---|
| `create_file(name, kind, content)` | **Asks first.** Word document (.docx from Markdown: headings, bullets, bold), CSV spreadsheet (UTF-8 with BOM for Excel), text, Markdown or web page (everything escaped). Saved in Documents\\Cortana; never overwrites ("Plan (2).docx"); ≤20,000 characters. "Open it" then opens it. |
| `analyse_table(document, column?)` | Exact row count and per-column total/average/min/max for a CSV in Documents (£/$/€, thousands separators and (negatives) understood). |
| `calculate(expression)` | Exact arithmetic (+ − × ÷ ^ %, "15% of 80", round/sqrt/min/max…); never runs code. |
| `organise_files(folder)` | **Asks first.** Downloads, Desktop or Documents only: moves loose top-level files into Images/Documents/Archives/Installers/Video/Audio/Code/Other; skips shortcuts and partial downloads; never overwrites or deletes; lists identical copies. Obeys *Screen, clipboard and file access*. |
| `pc_health()` | Read-only: free space per drive, RAM, processor load, the six biggest programs, app crashes in the last 2 days, uptime; flags drives ≥90% full and >7 days without restart. |
| `draft_email(to?, subject, body)` | **Asks first.** Opens a draft in the default mail app (mailto); she never sends it. |

**Ask before doing:** the card in Chat shows exactly what will happen (file name and content, the move plan, the draft). **Approve** / **Cancel**, or say "yes" / "cancel". Requests expire after 10 minutes and run once.
**Pictures:** 📎 in Chat also takes PNG/JPEG/WebP (up to 2 per question, shrunk to 1280 px); they go only to the local model with that question and are not saved.
**Deep thinking** allows up to 6 model rounds, so she can chain steps (search, then write a file).

Tool results go back to the model truncated to 2,500 characters (3,500 for `web_search` and `clipboard`, 3,200 for the document tools, 3,000 for `pc_health`).
`look_at_screen`, `clipboard`, `find_files` and `open_file` obey **Screen, clipboard and file access** in Systems.
All tools are disabled when **Abilities** is unticked in Systems.

## 4. Voice

- Engine **Natural (Piper)** by default: one persistent Piper process, `sentence_silence` 0.15 s, speed via `length_scale`
  (Relaxed 1.15, Normal 1.0, Brisk 0.88). Default voice `en_US-hfc_female-medium`; 8 stock voices offered; any
  `*.onnx` + `*.onnx.json` in the voices folder appears as a selectable voice.
- If Piper isn't ready or fails, that sentence uses the Windows voice (first installed female voice) and the status explains why.
- Reference voice (`zipvoice`): CPU-only ZipVoice-Distill int8 + Vocos, 8 steps, using the private supplied reference profile; downloads roughly 185 MB of model files. No pitch shifting. Experimental: can skip words and is slower than Piper. Unpacked once and warmed up at startup; while loading, the label shows "Loading Cortana's voice…".
- Lip sync: Windows voice → native visemes; Piper/reference → local Rhubarb phonetic audio alignment. It estimates nine mouth poses, not an exact phoneme transcript. Alignment unavailable/timeout → envelope fallback.
- Stop cancels the request ID on the server, stops playback and aborts queued speech HTTP calls. Native synthesis may finish its current chunk, but its output is discarded; completed tool effects are not undone.

## 5. Display panel (CORTANA // DISPLAY)

- Slides up above the bottom navigation, leaving the top ~40% of the screen (her face) visible; scrolls internally.
- Renders: `# title` (panel title), `##`–`####` headings, paragraphs, `**bold**`, `*italic*`, `` `code` ``, fenced code blocks
  (language label, keyword/string/comment/number/function colours, **Copy** button), tables, bulleted and numbered lists.
- All text is HTML-escaped before formatting; raw HTML from the model is shown as text.
- Close: ✕, Escape, or the Home tab. **◆ SHOW DISPLAY** reopens the last answer's screen until the next question.
- Pages (Chat, Briefing, Objectives, Memory, Systems) use the same panel. While Chat is open, displays appear as cards inside the conversation instead of replacing it (**Expand** opens one full-size).

## 6. Pages

**Chat** (Chat tab, or the keyboard button): the conversation as bubbles (You right, Cortana left) in the same holo panel;
typing indicator with the current ability (e.g. "SEARCHING…"); code, tables and weather as cards in her bubble with **Expand**;
errors shown in the bubble. Composer pinned at the bottom: 📎 adds files (PDF, Word, PowerPoint, text; ≤12 MB each, also by
dropping them on the panel; a note bubble confirms "added (N pages)"), Enter sends, Shift+Enter new line, grows to ~5 lines.
Cards have **Copy** (plain text, links as "text: url") and **Expand**. Links in cards open in a new tab and only https links are made clickable.
The last 60 conversation entries restore from the PC after a page reload. The caption under her face shows the latest spoken reply in a matching holo card.

**Mission Briefing:** date; **Read my briefing** (spoken summary of weather, today's events and open objectives, composed on
the page, no AI call); weather card + 3 days (needs home town); today's events (Cortana's own, with ✕ to remove, and Google's if connected); up to 6 open objectives.

**Objectives:** add To-do / Timer (minutes) / Reminder (date-time); grouped Timers, Reminders, To-do; live countdown for
running timers; ✓ completes, ✕ deletes; reminders that have fired are highlighted until completed. Re-renders when the AI changes items.

**Memory:** remembered facts (edit in place, Save, ✕ forget, add your own; possible same-subject conflicts flagged for review); **Documents I can read** (name, pages/slides, size, ✕ remove;
**Add files…**; on the PC only, **Add folder** by path: up to 80 readable files, 4 levels deep); last 30 conversation lines; **Clear conversation history** needs two
taps within 4 s. Facts are not cleared by clearing history.

**Systems:** AI model picker (detected GPU/RAM/disk; every Qwen 3.5 model with its size, rating badge, ★ Recommended, Download with live progress bar, or Use; too-big models greyed out and refused by the server); Abilities on/off; PC controls on/off; Screen, clipboard and file access on/off; voice engine
and voice; wake word (per device, stored in the browser); home town; calendar address (write-only, Disconnect button);
optional Brave Search key (write-only; search works without it); phone connection (Cloudflare/Tailscale, next launch); link to hologram view, movement, speech
pace and the phone QR (original Settings dialog). **Save** applies changes.

## 7. Alerts

Checked on every status poll (4 s). The first due, unannounced item is acknowledged, a three-note chime plays, and after
0.7 s she says "Chief, your <label> timer is done." or "Reminder, Chief: <text>." Only while she's idle; one at a time.
The launcher also checks every two seconds and attempts native Windows reminder balloons while the browser is closed (each in its own thread; a failed balloon is retried after 1 then 2 minutes and given up after 3 tries). Notification delivery has its own `notified` flag and does not consume a browser alert. Overdue alerts survive restarts. Systems can disable native reminders. Keep the launcher running; Windows notification settings control visibility. Objectives offers +10m snooze; recent acknowledged timers remain snoozable for 24 hours.

## 8. Wake word

Off by default; turned on per device in Systems (needs microphone permission and a tap after page load).
Energy-based detection that adapts to the room: a background-noise level is tracked while nobody speaks; speech starts above
max(0.012, 3 × noise) RMS (with pre-roll), ends after 0.7 s below max(0.009, 2 × noise) or 7 s total; bursts under 0.4 s are
ignored. Every burst is transcribed by the local Whisper with the hint "Cortana is my assistant." (a transcript
equal to the hint is ignored), and `runtime.wake_match` decides. The name may come after "hey/hi/ok/…" and fillers ("um"), within
the first 4 words, nothing else before it. Spellings ≥78% similar to "cortana" count (Courtana, Cortona, Gortana, "cor tana");
weaker sound-alikes (Katana, Quartana, Kortina…) only right after a greeting. 2+ following words → sent as the question;
otherwise a chime and normal listening. If speech arrives while a burst is being transcribed, the latest burst is kept and checked
next (not dropped). With wake enabled, echo-cancelled keyword audio remains active while thinking/speaking so the user can interrupt. Recognised playback echo is rejected (a transcript contained in what she is saying is ignored). Since 1.6.1 there is no keyword-spotter gate (D-037). Manual listening owns the mic. Real-room echo rejection is unverified.

## 9. Phone

The PC window shows a QR for the phone link. Scanning pairs the phone for that launch (Cloudflare) or persistently
(Tailscale). Unpaired visitors see a page explaining how to pair. The phone can use every feature except showing the pairing QR.

## 10. Avatar

The model loads from `assets/cortana.glb` + `rig.json`; textures are validated and the model reloaded (up to 3 attempts) if any
are missing; graphics-context loss is recovered; Back/Forward restores keep the animation running. Without a model, a message
explains how to add one and everything else works.

## 11. Character and voice setup

After model choice, first setup asks Normal (the former Expressive, strength 1.3) or Expressive (1.8), plus Piper/reference/Windows voice. Both have previews, persist on the PC, and remain changeable in Systems. Expression previews temporarily override status syncing. Reactions are deterministic from sentence wording (focused/curious/playful/concerned), with eye contact, smirks and brief gestures; no claim of original Halo animation data. Reduced motion suppresses head/hand movement.

Systems displays measured transcription, first-token, speech preparation, whole reply and send-to-playback times. These are last observed timings, not a performance guarantee; they contain no conversation text.

## 12. Proactive (1.6)

Every minute the launcher checks, without the page open:
- **New documents** in the folders added to Memory → Documents (same depth/type/count limits as adding a folder): each new or changed file is read in, and she says "New document ready: … Ask me to summarise it." Files present before the upgrade, or added together with a folder, are not announced. At most three notices per check; the rest become one "N more" notice. Switch: Systems → Briefing.
- **Finished downloads** (opt-in): new files at the top level of the user's Downloads folder, ignoring partial downloads (`.crdownload`, `.part`, …) and files changed in the last 15 seconds.
- **Daily briefing** (opt-in, Systems → Briefing time): once a day at that local time (or within three hours after, if the PC was off), the page opens Mission Briefing and reads it aloud.
Notices use the alert path: spoken in the open page and shown as a Windows pop-up titled "Cortana".

## 13. Full access (1.7, opt-in)

Systems → **Full access** (PC only, off by default). When on, requests made on the PC also get:
- `run_command(command, why?)`: one PowerShell command, shown exactly on the approval card; runs hidden in the user's home folder with a 120-second limit; exit code, the last 2,500 characters of output and any errors come back.
- `computer_task(goal)`: the goal is approved once; then up to 15 rounds of: screenshot (whole primary screen, scaled to 1280 px) → the model returns one JSON action (click, double_click, right_click, type, press keys, scroll, wait, done, fail) → it is performed with Windows SendInput. Pushing the mouse into the top-left corner stops it before the next action; **Stop** on the card stops it between steps. The model is told never to type passwords or payment details.
Every command and step is appended to `full-access.log` in the data folder. A paired phone never gets these tools and cannot approve them or switch the mode.
