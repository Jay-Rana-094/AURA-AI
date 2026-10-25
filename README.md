# AURA AI — Phase 4

Voice-controlled desktop assistant for Windows. Phase 1 = the core loop:
a Dynamic Island-style pill at the top-centre of your screen, offline +
Google voice engines, and the basic brain. Phase 2 adds command packs:
apps, websites, web search, media keys, and system controls. Phase 3
adds memory: notes, todos, and reminders, stored locally in SQLite.
Phase 4 adds custom commands you teach by voice, a help command, and
startup polish.

## Phase 2 commands (try these)

Apps (allow-list only — anything not listed gets an honest "not found"):
"open notepad", "open calculator", "open chrome", "open vs code",
"open paint", "open terminal", "open word", "open spotify".

Websites & search: "open youtube", "open github", "open gmail",
"search for best laptops", "search youtube for python tutorials",
"play arijit singh on youtube" (opens the YouTube results page —
picking a video is one click, since autoplaying needs the YouTube API).

Media keys: "volume up", "volume down", "mute", "pause the music",
"next song", "previous song".

System: "lock my pc". Destructive actions always ask first:
say "shutdown" and AURA asks "Are you sure?" — say "yes" to do it or
"no" to cancel. Same for "restart" and "sleep". Nothing destructive
ever runs from a single utterance.

Unknown commands get an honest "I don't know how to do that yet."
instead of a fake success.

## Phase 3 memory (notes, todos, reminders)

Everything is stored in `aura_memory.db` next to `main.py`, on your PC
only. Delete that file to wipe everything AURA remembers.

Notes: "remember that my keys are on the desk", "note that the wifi
password is in the drawer", "what are my notes", "delete note 1".

Todos: "add buy milk to my todo list", "what are my todos",
"complete todo 1". ("remind me to call mom" with no time also lands
here, since there's nothing to remind you *at*.)

Reminders: "remind me to stretch in 30 minutes", "remind me to call
mom at 5 pm", "remind me to submit the form tomorrow at 9 am",
"what are my reminders", "cancel reminder 1". Spoken numbers work
too ("in one minute", "at five pm"). If no time is heard at all,
AURA says so and files it as a todo instead of pretending it set
a reminder. When a reminder comes
due, AURA speaks it aloud — even in wake-word mode — unless you're
mid-command, in which case it waits for the next check. A bare hour
("at 5") is read as pm, and a time that already passed today rolls
to tomorrow.

## Phase 4 custom commands (teach AURA your own phrases)

Say: "teach aura study time means open vs code". From then on,
saying "study time" runs that command. The mapped command can be
anything AURA already knows — apps, search, reminders, notes.

- "list my custom commands" — hear everything you taught it.
- "forget custom command study time" — remove one.
- Mappings live in `custom_commands.json` next to `main.py`, plain
  JSON you can also edit by hand. Extracting a new version over the
  folder keeps this file, so your custom commands survive updates.
- Phrases match exactly: "study time" triggers it, "study" alone
  doesn't. A mapped command never triggers another custom phrase,
  so no loops.
- Say "what can you do" any time for a spoken summary of everything
  AURA knows.

## Start AURA with Windows (optional, manual)

AURA doesn't add itself to startup on its own. If you want it
launched at login: press Win+R, type `shell:startup`, and drop a
shortcut to `run.bat` in that folder. Remove the shortcut to undo.

## Wake word (no more tapping for every command)

Tap the 👂 button on the pill — it turns green and the dot turns
purple. Now just say **"Aura"**, then your command. After it answers,
AURA goes back to waiting for "Aura". Tap 👂 again to switch it off,
or tap the mic button any time to take manual control for one command.

- Wake-word listening always uses the offline Vosk engine, even if
  the command engine is set to Google — your audio never leaves the
  PC while waiting. (So the Vosk model must be installed for 👂 to
  work; if it isn't, the pill will say so and switch wake mode off.)
- Say "Aura" clearly, at normal volume. If it doesn't catch it, tap
  the mic button — that always works.
- Saying "goodbye" still closes AURA completely, wake mode included.

## What it looks like

A small black pill at the top middle of your screen: a status dot, a
status line, the last thing heard, a mic button, and an engine switch
(offline / google). Drag the pill to move it. It stays on top.

## Setup (Windows PC)

1. Install Python 3.10+ from python.org. Tick **"Add Python to PATH"**
   during install.
2. Open a terminal in this folder and install dependencies:

```
pip install -r requirements.txt
```

3. For the offline engine, download a small Vosk model from
   https://alphacephei.com/vosk/models and extract it into the
   `models` folder. **For Indian accents, get an Indian English
   model** (under "Indian English" on that page) — they understand
   Indian speech far better than the US model. AURA picks the best
   one present, in this order:

```
aura-ai/
  models/
    vosk-model-en-in-0.5/             <- most accurate (1 GB, needs
                                         a few GB free RAM, slower)
    vosk-model-small-en-in-0.4/       <- light + fast (~36 MB)
    vosk-model-small-en-us-0.15/      <- fallback (~40 MB)
```

   If accent accuracy is your main problem, the big `en-in-0.5`
   model is worth the 1 GB download. If your PC is low on RAM or
   you want instant responses, stick with the small Indian model.

   If no model is present, the offline engine will say so in the
   pill — switch the engine dropdown to "google" and it will work
   over the internet instead (Google is set to Indian English,
   `en-IN`, and is usually the most accurate option overall).
4. Allow microphone access when Windows asks.
5. Start it:

```
run.bat
```

   (or `python main.py`)

## Try it (Phase 1 test checklist)

- [ ] Pill appears at the top-centre of the screen.
- [ ] Tap the mic, say "hello" — AURA greets you aloud.
- [ ] Tap the mic, say "what is the time" — AURA speaks the time.
- [ ] Tap the mic, say "what is the date" — AURA speaks the date.
- [ ] Switch the engine dropdown to "google" and repeat one command.
- [ ] Say "goodbye" — AURA says goodbye and closes.
- [ ] Tap the mic, say "open notepad" — Notepad opens.
- [ ] Tap the mic, say "search youtube for python tutorials" — the
      results page opens in your browser.
- [ ] Tap the mic, say "volume up" — the volume rises.
- [ ] Tap the mic, say "shutdown" — AURA asks "Are you sure?".
      Say "no" to cancel (do not say "yes" unless you really want
      to shut down).

## Troubleshooting

- **"No microphone found"** — check Windows Settings > Privacy >
  Microphone, and that a mic is set as the default input device.
- **Speaks once, then goes silent (log says OK)** — pyttsx3 on
  Windows can return success while producing no sound after the
  first utterance. Fixed in v0.1.3: Windows speech now uses the
  built-in System.Speech engine, one fresh process per utterance.
  Run `python test_speak.py` to prove it: you should hear both
  lines. If you hear only one even there, check Windows Settings >
  System > Sound (output device + volume) — the app side is fine.
- **PyAudio install fails** — on Windows, `pip install pipwin` then
  `pipwin install pyaudio` usually fixes it.
- **Vosk model not found** — re-check the folder layout above, or use
  the Google engine for now.
- **AURA often misunderstands you (Indian accent)** — the US offline
  model is the usual cause. Either switch the engine dropdown to
  "google" (set to Indian English) or install the Indian English
  offline model `vosk-model-small-en-in-0.4` into the `models`
  folder. Also check Windows Settings > System > Sound > Input:
  mic volume 80–100%, speak from normal distance in a quiet room.
- **Pill doesn't appear** — make sure no other window is forced
  always-on-top above it, and that Python's tkinter installed
  (it ships with standard Windows Python).

## Project layout

```
main.py                 Entry point: GUI + voice loop wiring
run.bat                 One-click start on Windows
aura/
  listener.py           Mic input: Vosk offline + Google fallback
  speaker.py            Offline speech (System.Speech on Windows)
  brain.py              Command router + confirmation flow
  gui.py                Dynamic Island-style pill (tkinter)
  memory.py             SQLite notes, todos, reminders
  wakeword.py           Wake-word matching (no heavy imports)
  commands/             Apps, web, media, system, memory, custom
    __init__.py         Parse (no side effects) + execute
    apps.py             Allow-listed app launcher
    web.py              Sites, Google + YouTube search
    system.py           Volume/media keys, lock, power
    memory_cmds.py      Note/todo/reminder parsing + time language
    custom.py           Teachable phrase -> command mappings
```

## Privacy note

The offline engine keeps your voice entirely on your PC. The Google
engine sends audio to Google's servers — the pill always shows which
engine is active, so you always know.
