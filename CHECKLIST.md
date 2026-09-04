# Jarvis second-brain — EVO install checklist

Project: `/home/thomas-pashoulas/jarvis-second-brain`  
Host: EVO (Linux). Not Angelica (`~/jarvis-os`).

## Desktop vs web on Linux

| | **Web galaxy** (`viewer/` + `server.py`) | **Desktop daemon** (`desktop/`) |
|---|---|---|
| Role | 3D notes galaxy in Chrome + `/chat` | System-wide voice orb, wake word, STT/TTS |
| Install | Almost none (stdlib Python) | `~/.jarvis/venv` + ~600 MB models + audio/GUI deps |
| Official installers | N/A | Mac `install.sh` / Windows `install.bat` only |
| Brain | **Local** OpenAI-compatible `:11434` (default); Anthropic / `claude -p` still available if `provider` ≠ `local` | Local / Anthropic / NVIDIA NIM |
| Linux fit | **Works now** (needs llama-server up) | Possible but manual; Mac Calendar/Spaces hooks are Darwin-only |

**First successful run = web galaxy with local brain.** Desktop is optional later.

---

## Done on EVO

- [x] Repo cloned to `/home/thomas-pashoulas/jarvis-second-brain`
- [x] `config.json` created (gitignored) with `provider: "local"` + `local_*` keys
- [x] `notes/` directory created (sample `.md` notes present)
- [x] `python3 build.py` → `viewer/graph-data.js`
- [x] Key file path wired: `local_api_key_file` → `~/.cursor/deepseek-cursor-api.key` (code reads it; never commit contents)
- [x] Web + desktop code routes `provider: "local"` → `http://127.0.0.1:11434/v1`
- [x] User systemd: `jarvis-galaxy.service` + `llama-server.service` (enabled, loopback bind)
- [x] Brain running via `bin/start-brain.sh` (drop-in overrides base unit; `bin/start-llama-server.sh` → symlink)
- [x] `/health` reports `brain_up` + configured `local_model`

## Local brain (required for chat without cloud LLMs)

- [x] **llama-server on `:11434`** — active (`LLM_HOST=127.0.0.1`)
- [x] `/v1/models` returns model id; `"local_model"` set in repo `config.json`
- [x] Key file present at `local_api_key_file` (exists on EVO; do not paste into chat)
- [ ] Point `"notes_dir"` at a real markdown vault if you want more than `notes/`, **or** keep adding `.md` under `notes/`
- [ ] Re-run `python3 build.py` after adding notes
- [ ] After `server.py` / config changes: `systemctl --user restart jarvis-galaxy.service`
- [ ] Open `http://127.0.0.1:4700` and try a chat turn (local 27B can take ~30–90s+ per turn)

When `provider` is `local`: no Anthropic calls, no `claude -p` fallback, screen/images are blind (text-only).

## Optional — desktop voice daemon (Linux, manual)

- [ ] Create venv: `python3 -m venv ~/.jarvis/venv`
- [ ] `~/.jarvis/venv/bin/pip install -r desktop/requirements.txt` (`openai` already in venv on EVO)
- [ ] Download wake/Whisper models (same one-liners as in `desktop/install.sh`)
- [ ] System packages as needed: PortAudio, WebKitGTK/pywebview deps, mic access
- [ ] Config at `~/.jarvis/config.json` with `provider: "local"` + same `local_*` keys
- [ ] Run: `~/.jarvis/venv/bin/python desktop/jarvis.py`
- [ ] Expect gaps vs Mac: Calendar Automation, all-Spaces window hacks, `.command` launchers

## Non-LLM cloud remnants (OK for “local brain”)

These still touch the network even when the LLM is local:

- **edge-tts** — desktop spoken replies (Microsoft neural voices)
- **Calendars / To Do** — Google / Outlook Graph when configured
- **Viewer CDN** — unpkg (Three.js etc.) in the galaxy page
- Weather / sheets helpers in desktop home screen (if used)

## Out of scope / do not do

- [ ] Do **not** put `127.0.0.1:11434` into Cursor cloud Models settings
- [ ] Do **not** put project files in `$HOME` root or inside `~/jarvis-os`
- [ ] Do **not** commit `config.json` (gitignored) or API keys
- [ ] Do **not** print API keys or public tunnel hostnames

## Quick commands (web)

```bash
cd /home/thomas-pashoulas/jarvis-second-brain
python3 build.py
systemctl --user restart jarvis-galaxy.service   # preferred on EVO
# or: python3 server.py
# then open http://127.0.0.1:4700
```

Smoke local LLM (after `:11434` is up):

```bash
# fill local_model from GET http://127.0.0.1:11434/v1/models first
curl -sS http://127.0.0.1:11434/v1/models -H "Authorization: Bearer $(tr -d '\n' < ~/.cursor/deepseek-cursor-api.key)" | head -c 200
curl -sS http://127.0.0.1:4700/health
```

Stop server: `systemctl --user stop jarvis-galaxy.service` (or find PID on `:4700` and `kill`).
