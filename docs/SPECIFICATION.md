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

- History: the page keeps the last 18 messages; the server uses the last 16 within ~6,000 characters (newest kept).
- Every exchange is also saved to the local conversation log (Memory page; ≤2,000 messages kept).
- System prompt = personality and rules + current local date/time + home town + up to 40 remembered facts.
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
  the recommended one. `num_ctx` 6,144, `temperature` 0.45, up to 1,200 output tokens, thinking off. If the model fails to load
  or fails before producing text, she switches to `qwen3.5:4b` and retries once.
- Recommendation (`hardware.py`): usable graphics memory = total − 1.5 GB; need = download size + 0.3 GB. Fast = fits;
  Good = ≥80% fits; Slow = ≥60%; Too big = less, or the overflow doesn't fit in RAM − 6 GB (mixture-of-experts models: Good
  from 35%). Recommended = the most capable Fast/Good dense model (no GPU: 2B). Typical picks: 4 GB → 2B, 6 GB → 4B,
  8–16 GB → 9B, 20 GB+ → 27B.

## 3. Abilities (tools)

Up to 4 model rounds per message; up to 4 tool calls per round. Tool results are truncated to 2,500 characters (3,500 for `web_search`, which carries page text).

| Tool | Behaviour |
|---|---|
| `set_timer(minutes, label?)` | 0 < minutes ≤ 1,440. Creates a timer item. |
| `set_reminder(text, at? \| in_minutes?)` | `in_minutes` relative; `at` as `HH:MM` → next occurrence (today or tomorrow), or `YYYY-MM-DD HH:MM`. Refuses times more than 60 s in the past. |
| `add_task(text)` | To-do item, no due time. |
| `list_objectives()` | Open items with times. |
| `complete_objective(match)` | Completes up to 3 open items whose text contains all words (>2 letters) of `match`. |
| `remember(fact)` | Saves a fact (≤300 chars, case-insensitive de-duplication, ≤200 kept). |
| `forget(match)` | Deletes facts containing all words of `match`. |
| `get_weather(place?)` | Open-Meteo geocoding + forecast (now + 3 days). Empty place → home town; neither → asks the user. **Always** shows a forecast card (`tools.weather_screen`: now, then Today/Tomorrow/weekday with sky, high/low, rain chance), built from the data, not by the model; it replaces any model-written screen for that reply. |
| `web_search(query)` | **No key needed.** Brave (if a key is saved), else Bing's RSS results feed, else DuckDuckGo's HTML results page (ads skipped) → ≤5 results (title, snippet, source site). Then the first of the top 3 result pages that yields ≥200 characters of text is read: scripts/nav/header/footer dropped, the blocks most related to the query kept (≤1,400 chars), marked untrusted. Wikipedia fills in if fewer than 2 results. Only public http(s) addresses are fetched (redirects checked too). |
| `pc_control(action, target?, steps?)` | `play_pause`, `next_track`, `previous_track`, `volume_up/down` (1–25 × 2%), `mute`, `open_app` (allow-list: notepad, calculator, file explorer, settings, browser, spotify, task manager, paint, snipping tool), `open_website` (http/https only). Off when **PC controls** is unticked. Windows only. |
| `get_calendar(day?)` | `today`, `tomorrow` or `YYYY-MM-DD`. Reads the private iCal URL; expands repeats (RRULE), honours EXDATE, skips cancelled, converts time zones; all-day events first. |

All tools are disabled when **Abilities** is unticked in Systems.

## 4. Voice

- Engine **Natural (Piper)** by default: one persistent Piper process, `sentence_silence` 0.15 s, speed via `length_scale`
  (Relaxed 1.15, Normal 1.0, Brisk 0.88). Default voice `en_US-hfc_female-medium`; 8 stock voices offered; any
  `*.onnx` + `*.onnx.json` in the voices folder appears as a selectable voice.
- If Piper isn't ready or fails, that sentence uses the Windows voice (first installed female voice) and the status explains why.
- Lip sync: Windows voice → its viseme events; Piper → 45 ms loudness/zero-crossing windows mapped to mouth shapes.

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
errors shown in the bubble. Composer pinned at the bottom: Enter sends, Shift+Enter new line, grows to ~5 lines.
The conversation is kept for this browser tab (last 60 entries). The caption under her face shows the latest spoken reply in a matching holo card.

**Mission Briefing:** date; **Read my briefing** (spoken summary of weather, today's events and open objectives, composed on
the page, no AI call); weather card + 3 days (needs home town); today's events (needs calendar); up to 6 open objectives.

**Objectives:** add To-do / Timer (minutes) / Reminder (date-time); grouped Timers, Reminders, To-do; live countdown for
running timers; ✓ completes, ✕ deletes; reminders that have fired are highlighted until completed. Re-renders when the AI changes items.

**Memory:** remembered facts (✕ forget, add your own); last 30 conversation lines; **Clear conversation history** needs two
taps within 4 s. Facts are not cleared by clearing history.

**Systems:** AI model picker (detected GPU/RAM/disk; every Qwen 3.5 model with its size, rating badge, ★ Recommended, Download with live progress bar, or Use; too-big models greyed out and refused by the server); Abilities on/off; PC controls on/off; voice engine
and voice; wake word (per device, stored in the browser); home town; calendar address (write-only, Disconnect button);
optional Brave Search key (write-only; search works without it); phone connection (Cloudflare/Tailscale, next launch); link to hologram view, movement, speech
pace and the phone QR (original Settings dialog). **Save** applies changes.

## 7. Alerts

Checked on every status poll (4 s). The first due, unannounced item is acknowledged, a three-note chime plays, and after
0.7 s she says "Chief, your <label> timer is done." or "Reminder, Chief: <text>." Only while she's idle; one at a time.
Alerts need a Cortana page open (PC or phone).

## 8. Wake word

Off by default; turned on per device in Systems (needs microphone permission and a tap after page load).
Energy-based detection that adapts to the room: a background-noise level is tracked while nobody speaks; speech starts above
max(0.012, 3 × noise) RMS (with pre-roll), ends after 0.7 s below max(0.009, 2 × noise) or 7 s total; bursts under 0.4 s are
ignored. Each burst is sent to `/api/transcribe` with `wake: true`: Whisper gets the hint "Cortana is my assistant." (a transcript
equal to the hint is ignored), and `runtime.wake_match` decides. The name may come after "hey/hi/ok/…" and fillers ("um"), within
the first 4 words, nothing else before it. Spellings ≥78% similar to "cortana" count (Courtana, Cortona, Gortana, "cor tana");
weaker sound-alikes (Katana, Quartana, Kortina…) only right after a greeting. 2+ following words → sent as the question;
otherwise a chime and normal listening. If speech arrives while a burst is being transcribed, the latest burst is kept and checked
next (not dropped). Audio is ignored while she's thinking/speaking/listening.

## 9. Phone

The PC window shows a QR for the phone link. Scanning pairs the phone for that launch (Cloudflare) or persistently
(Tailscale). Unpaired visitors see a page explaining how to pair. The phone can use every feature except showing the pairing QR.

## 10. Avatar

The model loads from `assets/cortana.glb` + `rig.json`; textures are validated and the model reloaded (up to 3 attempts) if any
are missing; graphics-context loss is recovered; Back/Forward restores keep the animation running. Without a model, a message
explains how to add one and everything else works.
