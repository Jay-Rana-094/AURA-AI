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

## Phase 8A — Control Center window

Double-click the pill (or say "open control center") to open a
separate window with a title bar — close it with the mouse or say
"close control center". The pill itself is unchanged: borderless,
no close button, still draggable.

What the window shows (all read from the modules AURA already has):
- **Animated core** — a pulsing orb in the header, like the pill's.
- **Today** — the daily briefing, overdue + today's reminders,
  high-priority todos, unread notification count.
- **Notes · Todos · Reminders** — live lists with add / delete /
  complete / cancel controls.
- **History** — the recent conversation, with search and clear.
- **Settings** — theme picker (recolors the pill too), wake word,
  language (English / Hinglish), speech engine, always-on-top.
- **Diagnostics** — engine, Vosk model, language, wake word, theme,
  psutil status, Python and platform, plus live CPU / RAM / disk /
  battery telemetry, refreshed every 2 seconds.
- **Typed-command box** (bottom of every tab) — type a command and
  press Enter; it runs through the same brain as a voice turn and
  the reply is spoken aloud, like a voice turn.

New dependency: `psutil` (already in `requirements.txt` — run
`pip install -r requirements.txt` again after updating). Without it
the Diagnostics tab says so and everything else still works.

Changing the theme — by voice, by typed command, or from the
Settings tab — recolors the open Control Center immediately,
no reopen needed (fixed in the 8A v2 build, 2026-11-15).

## Phase 8B — Faster-Whisper engine (third speech engine)

AURA now has three listening engines, switchable from the pill's
engine menu, the Control Center's Settings tab, or by voice
("switch engine to whisper" / "switch engine to offline" /
"switch engine to google"):

- **offline** — Vosk, fully on-device (as before).
- **google** — Google's web speech API (as before).
- **whisper** — Faster-Whisper: OpenAI's Whisper model running
  locally. The "small" multilingual model hears both English and
  Hindi and fits the RTX 3050's 6 GB at float16; on a PC without
  a usable GPU it runs on CPU at int8 instead.

First Whisper listen loads the model — the first time, it also
downloads it (~500 MB) from HuggingFace, so the pill says
"Loading Whisper model..." while that happens. Later listens reuse
the loaded model. The wake word still always uses Vosk (light,
and it never sends audio anywhere).

GPU needs the CUDA 12 libraries: `pip install -r requirements.txt`
already includes `nvidia-cublas-cu12` and `nvidia-cudnn-cu12`.
If they are missing, Whisper still works — it falls back to CPU.
Check the Diagnostics tab in the Control Center to see the
Whisper status: installed, model, device, and whether it is loaded.

Whisper records the whole utterance, then transcribes it at once,
so it waits for ~1.2 seconds of silence after you finish speaking
(Vosk streams instead). Speak, pause, and the reply follows.

Drag still works exactly as before: a double-click only opens the
window when the pill never moved between the two clicks, so a drag
can never open it by accident. A taught custom phrase with the
same words as "open control center" still wins over the built-in,
like every other built-in command.

**Fixed in the 8B v2 build (2026-11-15)** — first test on Jay's PC
looked like Whisper was not listening at all:
- The pill now really stays on "Loading Whisper model..." until
  the model has finished loading (first run: ~500 MB download).
  Before, it flipped to "Listening..." at once, so speech during
  the download was never recorded and the turn timed out.
- A listen error now stays on the pill (and in the transcript)
  instead of flashing and being reset to idle.
- A failed model load is no longer cached forever: it retries on
  the next attempt, and a GPU failure falls back to CPU inside
  the same load instead of failing the turn.
- Typed commands now surface a brain failure as a reply instead
  of vanishing silently.

**Fixed in the 8B v3 build (2026-11-15)** — the v2 fix worked
(the error finally stayed visible), and the error was
`Library cublas64_12.dll is not found or cannot be loaded`:
- Windows does not find the CUDA runtime DLLs on its own, even
  after `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`.
  AURA now prepends the pip packages' `nvidia\cublas\bin` and
  `nvidia\cudnn\bin` folders to PATH before loading
  Faster-Whisper — ctranslate2 resolves cuBLAS with a plain
  LoadLibrary, which consults PATH and ignores
  `os.add_dll_directory`, so PATH is the fix.
- Safety net: the model can load on GPU yet fail at inference
  time, because cuBLAS is resolved lazily. If transcription
  fails with a CUDA-library error, AURA rebuilds the model on
  CPU and retries the same clip once instead of failing the
  turn. Diagnostics then shows the CPU device.

**Fixed in the 8B v4 build (2026-11-15)** — Whisper itself
works (Jay's "what is the time" was answered through it), but
switching by voice left the Control Center's Settings radio on
Offline: only the pill menu synced, never the open window.
Now every engine switch — voice, typed, pill menu, or radio —
refreshes the open Control Center too (radio, header, and
Diagnostics), on the GUI thread, so there is one engine state
everywhere and nothing to change twice.

## Phase 8C — Conversational fallback (Groq)

When AURA has no command for something, it asks Groq
automatically — no "turn on" step. Commands always win: the
fallback runs last, after every command pack and built-in reply,
and a taught custom phrase still beats it.

It uses Groq's free tier, model `openai/gpt-oss-120b` (Groq's
recommended replacement for the retired 70B Llama). Answers are
kept short (max 300 tokens) because they are spoken aloud, and
the last few turns are sent along for context. In Hinglish mode
it answers in Hinglish.

**Setup — one step:** AURA needs your Groq API key. Either set
the `GROQ_API_KEY` environment variable in the terminal you
launch AURA from, or save the key (one line, the key only) in a
file called `groq_api_key.txt` next to `main.py`. That file is
never zipped and never pushed to GitHub (see `.gitignore`) —
and never type the key into this chat.

**If the key is missing**, an unmatched question just gets the
old "I don't know how to do that yet." — no nagging. The
Control Center's Settings tab says "Groq key: missing" until
the key is in place, and saying "turn on chat mode" tells you
what to add.

**To stop it:** say "turn off chat mode", or uncheck the chat
checkbox in the Control Center's Settings tab. "is chat mode
on" reports the state. The Diagnostics tab shows the chat
status (on/off, key set/missing, model). A chat failure (no
internet, bad key, service error) is spoken as an honest
message — it never crashes the turn.

**Fixed in the 8C v2 build (2026-11-15)** — first test on Jay's
PC answered "tell me a joke" with "The chat service answered
with an error (HTTP 404)":
- The cause was not the key and not the setup. Groq retired
  `llama-3.3-70b-versatile` for free and developer tiers on
  2026-08-16 — it now 404s with `model_not_found`, which reads
  exactly like a broken key. The model is now
  `openai/gpt-oss-120b`, Groq's own recommended replacement
  for the 70B Llama (free tier, ~500 tokens/s).
- Failures now carry Groq's own error text with them, so the
  next retirement diagnoses itself instead of a bare "HTTP
  404" — a 404 now says the model no longer exists.

## Phase 9.1 — GPU in Diagnostics, weather in the briefing, Spotify control

Three small features, built 2026-11-15:

- **GPU usage in Diagnostics** — the Diagnostics tab's live
  telemetry (CPU / RAM / disk / battery) now has GPU lines
  underneath: name, load %, VRAM used / total, and temperature,
  refreshed every 2 seconds with the rest. It reads the card
  with GPUtil, which shells out to nvidia-smi (already on the
  PC with the NVIDIA driver). New dependency: `GPUtil==1.4.0`
  — run `pip install -r requirements.txt` again after
  updating. Without GPUtil, or on a PC with no NVIDIA GPU,
  the tab says so honestly and everything else still works.
  Voice: "what's my gpu usage" / "gpu status" speaks the
  numbers.
- **Weather in the daily briefing** — the briefing now has one
  line like "Weather in Vadodara: 28°C, clear sky, wind
  12 km/h." It comes from Open-Meteo: free, no API key, no
  account. The fetch is cached for 10 minutes, and when it
  fails (offline, or the service is down) the line is simply
  omitted — the briefing never carries a weather error
  message. Voice: "what's the weather" / "weather today"
  speaks the same line, or says the weather is unavailable
  right now.
- **Spotify control** — two layers. (a) **No setup:** "open
  Spotify" (already allow-listed), "play Spotify" / "pause
  Spotify" / "next song on Spotify" / "previous track on
  Spotify" all use the Windows media keys, like the generic
  media controls. (b) **Web API (optional):** "play <name> on
  Spotify" searches and plays a track — or a playlist, when
  no track matches — and "what's playing" tells you the
  current track. This needs a one-time setup (see below).
  When it is NOT set up, "play X on Spotify" opens the
  Spotify web search for X in the browser and says so
  honestly, instead of pretending it played.

**Spotify setup — one time, only for the Web API layer:**
1. Create an app at https://developer.spotify.com/dashboard
   (free account is fine). Under its settings, add this
   Redirect URI exactly: `http://127.0.0.1:8888/callback`
2. Copy the app's Client ID and Client Secret into a file
   called `spotify_credentials.json` next to `main.py`:
   `{"client_id": "YOUR_ID", "client_secret": "YOUR_SECRET"}`
   (That file is a secret: never zipped, never pushed to
   GitHub — see `.gitignore` — and never typed into chat.)
3. Run `python spotify_setup.py` from the AURA folder. It
   opens Spotify's login page in your browser; log in, accept,
   and it saves the login to `spotify_token.json` (also a
   secret, same rules). Then restart AURA.
4. Say "play <song> on Spotify".

Two Spotify rules to know: playback control needs **Spotify
Premium**, and the Spotify app has to be **open on the PC**
(the API controls playback, it doesn't start the app). Both
failures are spoken plainly: "isn't open on any device" /
"needs Spotify Premium". Playback always targets the PC
specifically — if the app isn't open on the PC, AURA says
"isn't open on your PC" instead of silently playing on
another device (e.g. your phone), which is what happened
before this fix. The login token refreshes itself;
if Spotify ever rejects it, run `spotify_setup.py` again.

## Phase 9.2A — Proactive morning briefing + system tray

Two features, built 2026-11-17 (from the parked 2026-11-15
work, finished — scheduler, tray lifecycle, tests, zip):

- **Proactive morning briefing** — AURA speaks the daily
  briefing by itself once each morning at 8:00 AM by default.
  Only while AURA is running: it is not a service, so it can't
  wake the PC or speak when it is closed. The fired date is
  saved, so a restart after the briefing never speaks it twice
  in one day; and if AURA starts after the briefing time, that
  day is skipped — a "morning briefing" at noon is not a
  morning briefing. A 10-minute grace window covers a check
  landing just after the time. Voice: "turn off morning
  briefing" / "turn on morning briefing" / "set morning
  briefing to 7:30" / "when is my morning briefing". The
  Control Center's Settings tab has the same switch and a time
  box (it takes "7:30" or "7:30 AM" — a bare 1–12 hour reads
  as AM), and the Diagnostics tab shows the time and when it
  last fired.
- **System tray icon** — the pill has no close button by
  design, so now AURA can run in the background: the tray icon
  (the same aura-icon.ico) has Show pill / Hide pill / Daily
  briefing / Quit AURA, and double-clicking the icon brings the
  pill back. Voice: "minimize to tray" / "hide the pill" /
  "show the pill". It uses pystray + Pillow — new dependencies,
  run `pip install -r requirements.txt` again after updating.
  If they are missing (or the tray backend refuses), AURA runs
  exactly as before with the pill as the only UI, and
  "minimize to tray" says so honestly instead of hiding the
  pill with no way back. The tray icon runs on its own thread,
  so it can never freeze the pill, and quitting (voice
  "goodbye", the tray's Quit, or the typed command) stops the
  icon first, then closes the pill.

## Phase 9.2B — Global hotkey + Google Calendar

Two features, built 2026-11-17:

- **Global hotkey** — press Ctrl+Alt+A anywhere on the PC
  and the Control Center opens with the cursor in the
  typed-command box, so you can type a command without
  touching the mouse or the pill. It works even while AURA
  is minimized to the tray: the hook is global, not tied to
  any window. Voice: "turn off hotkey" / "turn on hotkey" /
  "set hotkey to ctrl shift h" / "what is my hotkey". The
  Control Center's Settings tab has the same switch and a
  combo box (it takes "ctrl+alt+a" or "ctrl shift h" — a
  modifier plus one key; a bare letter is refused, or it
  would hijack normal typing), and Diagnostics shows the
  combo and whether the listener is running. It uses pynput
  — new dependency, run `pip install -r requirements.txt`
  again after updating. Why pynput and not the `keyboard`
  library: both sit on the same Windows low-level keyboard
  hook and neither needs admin rights for a normal user
  session, but `keyboard` 0.13.5 is unmaintained since 2020
  and its hook is known to stop silently, while pynput is
  actively maintained and its GlobalHotKeys is purpose-built
  for exactly this job. If pynput is missing (or the hook is
  refused), AURA runs exactly as before and "turn on hotkey"
  says so honestly. One known limit, shared by both
  libraries: keys typed into a window running as
  Administrator may not reach a non-elevated hook — that is
  a Windows rule (UIPI), not a bug.
- **Google Calendar in the daily briefing** — read-only:
  today's events appear in the daily briefing (spoken in the
  morning, and in the Control Center's Today tab), and you
  can ask "what's on my calendar today" / "any meetings
  today" any time. When the calendar is not connected, the
  briefing simply omits the line — same as the weather line
  — and the voice question tells you how to connect it.
  The Control Center's Settings tab shows the connection
  status, and Diagnostics does too. It uses the official
  Google client libraries — new dependencies, run
  `pip install -r requirements.txt` again after updating.

### Google Calendar — one-time setup (free)

Do these once, in order. Everything is free; AURA only ever
reads your calendar, never writes to it.

1. Go to console.cloud.google.com and sign in with the
   Google account whose calendar you want (your work Gmail
   is the natural one). Create a project (any name, e.g.
   "AURA") and open it.
2. Left menu → APIs & Services → Library. Search for
   "Google Calendar API" and click Enable.
3. Left menu → Google Auth platform → Branding. Fill in the
   app name (e.g. "AURA"), your email as the user support
   email, and your email again as the developer contact
   email, then Save.
4. Same section → Audience. Choose External (your account
   is not a Google Workspace account), then under Test
   users click Add users and add your own Google account
   email. This is the step people miss: while the app is in
   Testing mode, only test users can sign in — without it
   the login fails with "Access blocked".
5. Left menu → Google Auth platform → Clients → Create
   Client. Application type: **Desktop app**. Name it
   "AURA" and Create. Download the JSON (the download
   button on the client row).
6. Save that downloaded JSON as `google_credentials.json`
   in the same folder as `main.py` (the inner
   `aura-ai-phase9-2b` folder). Do not rename its contents
   — the setup script needs the downloaded file as-is.
7. In that folder, run `python calendar_setup.py`. Your
   browser opens Google's login page — sign in with the
   same account you added as a test user and accept (it
   only asks for read-only calendar access). The script
   waits on http://127.0.0.1:8889 for the redirect; for a
   Desktop app client no redirect URI needs registering in
   the console — loopback addresses are allowed by
   default. Then restart AURA.

Notes: `google_credentials.json` and the `google_token.json`
the setup saves are secrets — never share them, and they are
never in the zip or on GitHub. The token refreshes itself,
so you only run the setup once (run it again only if the
login is revoked or the token file is deleted). If the
browser says "Access blocked", you skipped step 4 — add
your email as a test user and run the setup again.


## Interruption (barge-in) — what stops speech now

While AURA is speaking, any of these cuts the reply off
mid-sentence — you never have to wait for a long reply (a daily
briefing, for example) to finish:

- **Tap the mic** — cuts the speech and starts a new voice turn.
- **Type a command** (Control Center command box, or the
  Ctrl+Alt+A hotkey) — the typed command stops the speech in
  progress first, then runs. Before this fix, a typed command
  queued its reply behind the old speech, so the old reply
  played to the end.
- **Say the wake word** ("Aura", or your custom word) while it
  speaks — speech stops and AURA listens for your follow-up
  command. Voice turns only.
- **Say "stop"** (also "stop speaking", "be quiet", "quiet",
  "enough") while it speaks — speech stops. In a voice turn
  AURA then listens for what you want next; a typed reply
  just stops, it never starts a voice turn. The listener is
  the offline Vosk engine only, like wake-word listening —
  audio never leaves the PC.

Two things that do NOT stop speech: reminders and the morning
briefing keep their short bare replies (a typed command still
cuts them, since it stops whatever is speaking). And a reply
that contains the wake word or a stop phrase itself ("say
'turn off chat mode' to stop that") skips the voice listener
for that reply — otherwise AURA's own speech would trigger
it. There are no Hindi stop phrases: the Hindi pack has no
stop/interrupt vocabulary to match them to.

**Fixed 2026-11-17** — Jay reported speech "is not stopping
when interrupting by typing or saying" while testing the 9.2B
hotkey. The typed path never called stop() (unlike the mic
tap), and typed replies had no barge listener at all. The
barge logic now lives in `aura/barge.py` (shared by voice
turns and typed commands) with the stop phrases in
`aura/wakeword.py`; `test_barge.py` covers the matcher, the
cut, and the echo guard.

## Phase 10.1 — Shared State Manager + Long-Term Memory + Personality Modes + Focus Mode

Four features, built 2026-11-17 (resumed from the parked
2026-11-15 work, finished — state wiring, facts, personality,
focus, tests, zip). No new dependencies — stdlib only, so no
`pip install -r requirements.txt` is needed for this phase.
32 test files pass under Xvfb.

- **Shared State Manager** — one event bus for what AURA is
  doing right now, so the pill, the Control Center, and later
  features (avatar, gestures, meeting capture) all read the
  SAME state instead of each tracking their own. States:
  IDLE, LISTENING, THINKING, EXECUTING, SPEAKING,
  WAITING_CONFIRMATION, SUCCESS, ERROR. Subscribers get a
  `STATE_CHANGED` event carrying the canonical state, a
  human-readable status line, and the pill's own display
  state. The pill publishes every state change through its
  `on_state` callback; voice turns and typed commands publish
  EXECUTING while the brain runs, SUCCESS when a turn
  finishes, and WAITING_CONFIRMATION when a reply asked "are
  you sure?". The pill's extra display state "wake" (waiting
  for the wake word) is a rendering of IDLE on the bus. A
  failing subscriber never breaks the bus, and an unknown
  state is rejected loudly instead of silently moving it. The
  Control Center's Diagnostics tab shows the live state.
- **Long-Term Memory** — a facts table and a preferences table
  in the SQLite DB. Explicit-save only: AURA stores a fact
  when Jay says "remember that..." ("remember that Nexture's
  stack is MERN", "remember my preferred editor is VS Code")
  and never silently harvests facts from conversation. Secrets
  (passwords, API keys, tokens) are refused at both the memory
  layer and the command layer. Voice: "what stack does
  Nexture use?" / "what is Nexture's stack?" / "what do you
  remember about Nexture?" / "what is my preferred editor?" /
  "list what you remember" / "update Nexture's port to 7000" /
  "forget Nexture's port" / "forget fact number 2". Status
  questions that already have their own handler ("what is my
  gpu usage", "what is my theme", "what is my hotkey", "what
  is my morning briefing", "what is my wake word") fall through
  to those handlers instead of being answered as preferences.
  The plain note phrase ("remember that my keys are on the
  desk") matches no fact shape, so it still lands as a note.
- **Personality Modes** — five presets as DATA in
  `aura_settings.json` (not code branches): Aura (polished,
  lightly witty, medium verbosity, 175 WPM), Professional
  (formal, direct, short, 165), Minimal (terse, minimal, 180),
  Friendly (casual, warm, medium, 175 — the default, today's
  behaviour), Silent (no spoken replies, minimal, 175). A mode
  changes only tone, verbosity, voice rate and whether speech
  is on — never permissions, and never the confirmation rules.
  Questions and failure replies are never trimmed, so a
  confirmation prompt or an honest failure always reaches Jay
  whole. Voice: "switch to Aura mode" / "what mode are you
  in" / "turn on silent mode" / "turn off silent mode". The
  Control Center's Settings tab has a personality picker and
  Diagnostics shows the mode; a voice switch refreshes the
  open window's radios, like chat mode does. The "Jarvis"
  preset was renamed to "Aura" at Jay's word (2026-11-17) —
  the mode is named after AURA itself. One honest limit: the
  Windows WinRT voice path takes no rate, so the voice rate
  applies through SAPI and pyttsx3 only; Silent mode still
  shows replies in the transcript and logs reminders.
- **Focus Mode** — timed focus sessions on a monotonic clock,
  so wall-clock changes can never stretch or shrink one.
  Presets: Pomodoro (25 work / 5 break) and fifty (50/10);
  task words pick a preset (coding/study → fifty,
  reading/meeting/writing → Pomodoro). Voice: "start a focus
  session for 25 minutes" / "start a 25-minute coding
  session" / "start Pomodoro" / "pause focus" / "resume
  focus" / "how long is my focus session" / "end focus" /
  "start a break" / "focus history". Task linking: "start a
  30-minute session for report" links to the matching todo
  and says so honestly when no todo matches. When a session
  ends it moves into its break automatically; session history
  is written to SQLite only when a session finishes or is
  ended deliberately — closing AURA mid-session records
  nothing. During a session, AURA's own non-essential
  notification-log entries are held and written back when the
  session ends; reminders still speak, because they are
  alarms, not distractions. The Control Center's Today tab
  and Diagnostics show a live session.
