# Jarvis — System-Wide AI Butler 🎩

A professional, open-source-stack voice assistant that runs on your machine — not in a browser
tab. Say **"Hey Jarvis"** from any app, and a floating particle orb expands into a full HUD home
screen — clock, today's agenda, a glowing orb with a live equalizer — listens, thinks, and talks
back, then shrinks back to a small standby orb. It knows your notes, sees your screen, runs
commands, downloads files, speaks Portuguese/English/French, and remembers what you teach it.

Two versions live in this repo:

| Version | What it is | Needs |
|---|---|---|
| **Desktop (recommended)** — `desktop/` | System-wide daemon: wake word, offline speech-to-text, neural voice, floating always-on-top orb, shell + screen + notes + memory tools | Python 3.10+, an Anthropic API key |
| **Web galaxy** — `viewer/` + `server.py` | 3D knowledge galaxy of your notes in Chrome with voice chat and fly-to-source camera | Python 3, Chrome |

**Collaboration / development guide:** [docs/COLLABORATION.md](docs/COLLABORATION.md) (from the shared Collaboration Plan). EVO machine notes: [MACHINE.md](MACHINE.md).

## The stack (all open source except the brain)

- [openWakeWord](https://github.com/dscripka/openWakeWord) — "Hey Jarvis" detection, fully offline
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — speech-to-text, fully offline
- [edge-tts](https://github.com/rany2/edge-tts) — natural neural voices, free
- [pywebview](https://github.com/r0x0r/pywebview) — the floating orb overlay
- **Anthropic API** — the agentic brain, with tools:
  - `run_command` — shell access: download files, open apps, manage files (destructive commands are blocked)
  - `run_claude_code` — hands off real coding/writing work to the Claude Code CLI in a specific
    project folder, with a chosen model and effort level (e.g. "open Claude Code in ~/interviews,
    sonnet, low effort, and draft a study plan"). Runs on whatever Claude Code is logged into on
    this Mac (usually your Claude subscription) - a separate cost/quota from the Anthropic API
    key powering Jarvis's own replies. Note: whatever it writes back still gets read out/replied
    to by Jarvis, which does cost a (usually small) amount of API tokens proportional to its length.
  - `screenshot` — native screen capture of whatever is on screen, any app, no sharing dialogs
  - `search_notes` — searches your markdown second brain (Obsidian vault, iCloud Drive, any markdown folder)
  - `remember` — long-term memory file that persists across sessions
  - `read_calendar` — reads today's (or the next N days') events from the Mac Calendar app
  - `read_google_calendar` — same, from Google Calendar, once you link it (see below)
  - `read_outlook_calendar` — same, from Outlook/Microsoft 365 Calendar, once you link it (see below)
  - `create_calendar_event` — actually schedules something ("Jarvis, book a client call tomorrow
    at 2pm") on the Mac Calendar and, if linked with write access, Google Calendar too
  - `read_metodo_momento` — searches the Move AI agency's lead-gen spreadsheets (pipeline status,
    outreach messages) for a company, lead ID, or status keyword
- Optional **Slack bridge** — DM or @mention Jarvis on Slack for the same brain, no voice needed
- **Conversation memory** — remembers the last ~24 turns across a restart (as long as it's within
  3 hours; older gets treated as a fresh session instead of confusing stale context)
- **Study mode** — tracks progress through markdown study plans (sessions per track live as .md
  files; progress lives in `~/.jarvis/study_progress.json`, the plans are never modified). Say
  "abra a interface de estudo de francês / de IA" (or click the Estudos card on the home screen)
  for a **light-palette study screen**: pick a timer (25/50/90/120 min or custom, with
  pause/resume and an end-of-timer chime), the session's markdown rendered as a lesson page
  (tables, checklists, links open in the real browser, YouTube links get an inline clickable
  thumbnail), and a "Concluir sessão" button that advances the track. Every day the session-of-
  the-day for each track is mirrored into a Microsoft To Do list called "Estudos" (due today),
  and completing a session checks off the matching task. Also: "o que eu estudo hoje?" and
  "concluir sessão de [IA/francês]" work by voice, and you can keep talking to Jarvis while the
  study screen is open. Track paths/structure are configured in `desktop/study.py`.

Wake it three ways: say **"Hey Jarvis"**, **clap twice**, or **click the orb**.
Speak over it ("Hey Jarvis…") to interrupt mid-sentence. After he answers, he keeps listening
for **6 seconds** without needing the wake word again, for a natural back-and-forth.

Speaks Portuguese by default and switches fluently to English or French whenever you do - both
transcription and the reply voice follow along automatically.

The first time you ask about your calendar, **macOS will show a permission popup** ("Terminal"
or "Python" wants to control Calendar) — click Allow. If you miss it or say no, Jarvis will tell
you exactly where to fix it (System Settings → Privacy & Security → Automation).

---

## 🔑 API keys you need (this is the complete list)

**One key. That's it: an Anthropic API key.**

1. Create it at <https://console.anthropic.com> → API Keys ($5 of credit goes a long way).
2. After running the installer, open `~/.jarvis/config.json` (Mac) or
   `C:\Users\YOU\.jarvis\config.json` (Windows) and paste it into `"api_key"`.
   Type it into the file yourself — never paste API keys into chat windows or websites.

Everything else (wake word, speech-to-text, voice, orb) is free and runs locally.
No OpenAI key, no ElevenLabs, no subscriptions.

---

## 🍎 Mac install

```bash
cd desktop
./install.sh          # one time: creates ~/.jarvis/venv, downloads models
```

Put your API key in `~/.jarvis/config.json`, then double-click **`Jarvis-Desktop.command`**
(first time: right-click → Open). macOS will ask for **Microphone** and **Screen Recording**
permissions — allow both (System Settings → Privacy & Security).

## 🪟 Windows install

1. Install Python 3.10+ from <https://www.python.org/downloads/windows/> —
   check **"Add python.exe to PATH"** in the installer.
2. Download this repo: green **Code → Download ZIP** button, extract to e.g. `C:\jarvis`.
3. Double-click `desktop\install.bat` (one time, downloads ~600 MB of local models).
4. Put your API key in `C:\Users\YOU\.jarvis\config.json`.
5. Double-click `desktop\start-jarvis-desktop.bat`. Allow microphone access if asked.

## Starting and stopping Jarvis

Double-clicking the start file opens a Terminal/Command Prompt window that runs Jarvis in the
background - closing that window does **not** stop it, and double-clicking start again will
refuse to launch a second copy (it detects the one already running instead of duplicating it).

To quit Jarvis, either:
- **Hold the orb down for about a second** - it dims and closes, no window-hunting needed, or
- Double-click **`Stop-Jarvis.command`** (Mac) / **`stop-jarvis.bat`** (Windows) in `desktop/`.

### Auto-start at login, and coming back from a full quit

Voice/clap wake-up only works while Jarvis is already running - it can't hear "Hey Jarvis" before
it's open. Two pieces solve this:

- Jarvis starts itself automatically every time you log in.
- A tiny **standby listener** (`wake_sentinel.py`) - just the mic + wake-word model, no Whisper,
  no orb window, cheap enough to run all the time - takes over the instant you fully quit Jarvis
  (holding the orb, Stop-Jarvis, Task Manager, however). Say "Hey Jarvis" or clap twice and it
  relaunches the full app, then gets out of the way. You never touch a launcher file again.

**Mac:**
```bash
cd desktop
./install-autostart.sh
```
Installs two LaunchAgents (`com.jarvis.assistant` for login start, `com.jarvis.sentinel` with
auto-restart for the standby listener). Safe to run while Jarvis is already open - the
duplicate-instance guard makes it a no-op instead of opening a second copy. To undo:
`./uninstall-autostart.sh`.

**Windows:**
```bat
cd desktop
install-autostart.bat
```
Registers three Task Scheduler tasks: Jarvis at logon, the sentinel at logon, and a watchdog that
checks every minute that the sentinel is still alive and restarts it if not (Task Scheduler's
equivalent of the Mac's LaunchAgent KeepAlive). This mirrors the Mac behavior but **could not be
tested on a real Windows machine** - if "Hey Jarvis" doesn't revive the app after a full quit,
open Task Scheduler and check the three "Jarvis…" tasks for errors, or just fall back to
double-clicking `start-jarvis-desktop.bat`. To undo: `uninstall-autostart.bat`.

## ⚙️ config.json reference

```json
{
  "api_key": "sk-ant-…",
  "model": "claude-sonnet-5",
  "voice": "pt-BR-AntonioNeural",
  "language": "pt",
  "notes_dir": "/path/to/your/obsidian/vault",
  "user_title": "senhora",
  "orb_x": null,
  "orb_y": null,
  "slack_bot_token": "",
  "slack_app_token": "",
  "outlook_client_id": "",
  "provider": "anthropic",
  "nvidia_api_key": "",
  "nvidia_model": "openai/gpt-oss-120b",
  "voice_en": "en-GB-RyanNeural",
  "voice_fr": "fr-FR-HenriNeural",
  "user_name": "",
  "weather_city": "",
  "shortcuts": {
    "site pricing sheet": "https://docs.google.com/spreadsheets/d/…"
  }
}
```

- `model`: `claude-sonnet-5` is the default for a snappy voice assistant. Switch to `claude-opus-4-8` for a smarter but slower brain.
- `voice` / `voice_en` / `voice_fr`: any edge-tts voice (`edge-tts --list-voices`) for each
  language. Jarvis transcribes and replies in whichever of Portuguese/English/French you're
  speaking, and picks the matching voice automatically.
- `language`: your default/primary language (`pt`, `en`, `fr`) - used for the default greeting tone
- `notes_dir`: your markdown notes folder; leave `""` to disable notes search
- `user_title`: how the butler addresses you (`sir`, `senhora`, …)
- `user_name`: your first name, used in the daily briefing ("Good morning, Thayna")
- `weather_city`: a city name (e.g. "Porto") for the weather in the daily briefing - free via
  Open-Meteo, no API key needed. Leave `""` to skip weather.
- `orb_x` / `orb_y`: remembers where you last dragged the orb to rest; leave `null` for bottom-right
- `shortcuts`: name → URL pairs. Say "open [name]" and Jarvis opens that exact link - no guessing,
  it always uses the URL you configured. Great for spreadsheets, dashboards, or sites you open
  often. Add as many as you like.

### The orb, and the daily briefing home screen

A small particle orb rests in the bottom-right corner (or wherever you last dragged it) while
idle, and glides - still small - to screen-center for ordinary questions. **Drag it anywhere**
with the mouse; its resting spot is remembered even after restarting.

The **full HUD home screen** is separate and doesn't open for every question - only when you ask
for it: say **"Hey Jarvis, give me my daily overview"** (or "resumo do dia", "abra sua home",
"visão geral"), or **triple-click the orb**. It takes over the screen fullscreen with a real,
scripted briefing - your name, the time, the weather (if `weather_city` is set), and your actual
calendar - narrated topic by topic while the matching card lights up and the rest dim, then closes
itself and shrinks back to the small standby orb when done.

## Try saying

- "Hey Jarvis — what's on my screen right now?"
- "Hey Jarvis — search my notes for the pricing strategy."
- "Hey Jarvis — download the latest n8n release to my Downloads folder."
- "Hey Jarvis — remember that my husband's laptop uses the English voice."
- "Hey Jarvis — what's on my calendar today?"
- "Hey Jarvis, can you answer me in English from now on?" / "Hey Jarvis, réponds-moi en français."
- "Hey Jarvis, give me my daily overview." / triple-click the orb — opens the full HUD briefing
- "Hey Jarvis, book a client call tomorrow at 2pm." — creates a real calendar event
- "Hey Jarvis, what's the status of the lead J. Silva Eletricista?" — reads the Método Momento sheets

The daily briefing also greets you automatically the first time Jarvis is alive on a new day - no
need to ask for it every morning; ask any time after that for an update.

---

## 🆓 Free brain option: NVIDIA NIM (optional)

Anthropic's API is what powers Jarvis by default (see the API keys section above) - it's cheap
but not free. If you want a **$0 alternative brain**, NVIDIA hosts several open-weight models for
free via an OpenAI-compatible API. After testing several candidates for personality quality,
speed, and - critically - reliable tool use, **`openai/gpt-oss-120b`** came out clearly ahead:
about 1-2 seconds per reply, correct tool calls, and Portuguese quality close to Claude Sonnet.
(Qwen's larger model technically worked too but took 30-45 seconds per turn - unusable for a
live voice assistant. Mistral Large and the older Nemotron models weren't available on the free
tier at all.)

1. Create a free key at <https://build.nvidia.com/settings/api-keys>.
2. Paste it into `config.json`'s `"nvidia_api_key"` field (leave `"provider": "anthropic"` for now).
3. Restart Jarvis once so it picks up the key.
4. **Click the ⚙ gear that appears in the corner of the orb** → pick **"Anthropic"** or
   **"Grátis (NVIDIA)"** any time - it switches instantly, no restart, no editing files.

**About screen vision on the free brain:** `gpt-oss-120b` itself can't see images, but you don't
lose the feature - ask "what's on my screen?" while on the free brain and it automatically
borrows a vision-capable Anthropic call just for that one look, then hands the description back
to the free brain to keep talking. Slightly less private and not literally free for that one
call, but the capability doesn't disappear. Everything else (notes, calendars, run_command,
run_claude_code, memory, Slack) works identically on both brains.

**Image generation:** not wired in yet - NVIDIA's image models live on a different API surface
than the chat models tested here, so this is a genuine follow-up, not something quietly faked.

## 📅 Google Calendar setup (optional)

The Mac Calendar app already works out of the box (native, no setup). To also read a Google
Calendar (e.g. a work calendar not synced to Mac Calendar):

1. Go to <https://console.cloud.google.com>, create a project (or reuse one), then
   **APIs & Services → Enable APIs → search "Google Calendar API" → Enable**.
2. **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
   Application type: **Desktop app**. Download the JSON file it gives you.
3. Save that file as `~/.jarvis/google_credentials.json` (Mac) or
   `%USERPROFILE%\.jarvis\google_credentials.json` (Windows). Rename it exactly to that.
4. Run once from a terminal, inside `desktop/`:
   ```bash
   ~/.jarvis/venv/bin/python google_calendar_setup.py       # Mac
   %USERPROFILE%\.jarvis\venv\Scripts\python google_calendar_setup.py   # Windows
   ```
   Your browser opens, you log in and click Allow. Done — the token is cached and refreshes
   itself; you won't need to repeat this unless you revoke access.

This now requests read **and create** access (needed for `create_calendar_event` to also write to
Google Calendar, not just Mac Calendar). If you linked Google Calendar before this was added,
**delete `~/.jarvis/google_token.json`** and re-run step 4 once to re-grant with the new scope -
otherwise event creation silently only reaches the Mac Calendar.

## 📆 Outlook Calendar and To Do setup (optional)

To let Jarvis read and create Microsoft 365 / Outlook.com calendar events and manage personal tasks in Microsoft To Do:

1. Go to <https://portal.azure.com> → search **"App registrations"** → **New registration**.
   - Name: "Jarvis" (or anything)
   - Supported account types: **"Accounts in any organizational directory and personal Microsoft
     accounts"** (needed for personal outlook.com/hotmail accounts too)
   - Redirect URI: leave blank
   - Click **Register**
2. On the app's overview page, copy the **Application (client) ID**.
3. **Authentication** (left sidebar) → scroll to **Advanced settings** →
   **"Allow public client flows"** → set to **Yes** → **Save**.
4. **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions** →
   add `Calendars.ReadWrite` and `Tasks.ReadWrite`. (No admin approval needed for personal use.)
5. Paste the client ID into `config.json`:
   ```json
   "outlook_client_id": "your-application-client-id"
   ```
6. Run once from a terminal, inside `desktop/`:
   ```bash
   ~/.jarvis/venv/bin/python outlook_calendar_setup.py       # Mac
   %USERPROFILE%\.jarvis\venv\Scripts\python outlook_calendar_setup.py   # Windows
   ```
   It prints a short code and a link to **microsoft.com/devicelogin** — open that link on any
   device, enter the code, sign in with your Microsoft account. Done — the token is cached and
   refreshes itself. Jarvis creates tasks in a Microsoft To Do list called **Jarvis**.

## 💬 Slack setup (optional)

Lets you DM or @mention Jarvis on Slack and get the same brain that answers your voice — a
**separate, dedicated Slack app**, independent from any other bot you already run (e.g. a
Hermes agent for a different project). It won't touch or interfere with that.

1. Go to <https://api.slack.com/apps> → **Create New App → From scratch**. Name it (e.g. "Jarvis"),
   pick your workspace.
2. **Socket Mode** (left sidebar) → toggle it **On** → it'll ask you to generate an
   app-level token: name it anything, scope `connections:write` → copy the token
   (starts with `xapp-`) → this is `slack_app_token`.
3. **OAuth & Permissions** → scroll to **Scopes → Bot Token Scopes** → add:
   `chat:write`, `im:history`, `im:read`, `im:write`, `app_mentions:read`.
4. **Event Subscriptions** → toggle **On** → under **Subscribe to bot events** add:
   `message.im` and `app_mention`.
5. Back in **OAuth & Permissions**, click **Install to Workspace** → copy the
   **Bot User OAuth Token** (starts with `xoxb-`) → this is `slack_bot_token`.
6. Paste both into `config.json`:
   ```json
   "slack_bot_token": "xoxb-…",
   "slack_app_token": "xapp-…"
   ```
7. Restart Jarvis. In Slack, DM the bot directly, or @mention it in any channel it's in.

Slack messages go through the exact same brain as voice — including `run_command`, so you can
ask it to edit, create, or update a note (Obsidian or any file) straight from Slack, e.g.
"add a line to my pricing note about the new plan." It really writes to the file, not just talks
about it.

---

## Web galaxy version (bonus)

The original 3D knowledge galaxy still works: `python3 build.py && python3 server.py`,
then open <http://localhost:4700> in Chrome. Same `config.example.json` → `config.json` setup
in the repo root. See commit history for its full feature set (wake word in browser,
clap detection, screen sharing, remember-that notes).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Orb doesn't hear you | Check OS microphone permission for the terminal/Python |
| "Screen recording" black images (Mac) | System Settings → Privacy → Screen Recording → allow Python |
| Voice sounds wrong language | Set `voice` and `language` in config.json |
| First answer is slow | Models warm up on first run; it gets faster |
| `python` not recognized (Win) | Reinstall Python with "Add to PATH" checked |

Built with Claude Code. Wake-word, STT, TTS and overlay are fully open source.
