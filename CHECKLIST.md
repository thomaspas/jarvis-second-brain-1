# Jarvis second-brain — EVO install checklist

Project: `/home/thomas-pashoulas/jarvis-second-brain`  
Host: EVO (Linux). Not Angelica (`~/jarvis-os`).

## Desktop vs web on Linux

| | **Web galaxy** (`viewer/` + `server.py`) | **Desktop daemon** (`desktop/`) |
|---|---|---|
| Role | 3D notes galaxy in Chrome + `/chat` | System-wide voice orb, wake word, STT/TTS |
| Install | Almost none (stdlib Python) | `~/.jarvis/venv` + ~600 MB models + audio/GUI deps |
| Official installers | N/A | Mac `install.sh` / Windows `install.bat` only |
| Brain | Anthropic API (or `claude -p` fallback) | Anthropic or NVIDIA NIM |
| Linux fit | **Works now** | Possible but manual; Mac Calendar/Spaces hooks are Darwin-only |

**First successful run = web galaxy.** Desktop is optional later.

---

## Done on EVO

- [x] Repo cloned to `/home/thomas-pashoulas/jarvis-second-brain`
- [x] `config.json` created from `config.example.json` (placeholder API key)
- [x] `notes/` directory created (empty)
- [x] `python3 build.py` → `viewer/graph-data.js` (`0 notas`)
- [x] `python3 server.py` listening on `http://127.0.0.1:4700`
- [x] Viewer loads (HTTP 200, title *Galáxia do Conhecimento*)

## Next — web galaxy (useful chat)

- [ ] Put a real Anthropic API key in `config.json` → `"api_key"` (edit locally; never paste into chat)
- [ ] Or install Claude Code CLI (`claude`) so placeholder key can fall back to `claude -p`
- [ ] Point `"notes_dir"` at a markdown vault, **or** drop `.md` files into `notes/`
- [ ] Re-run `python3 build.py` after adding notes
- [ ] Restart server if config/notes changed: stop old PID, then `python3 server.py`
- [ ] Open `http://127.0.0.1:4700` in Chrome and try a chat turn

## Optional — desktop voice daemon (Linux, manual)

- [ ] Create venv: `python3 -m venv ~/.jarvis/venv`
- [ ] `~/.jarvis/venv/bin/pip install -r desktop/requirements.txt`
- [ ] Download wake/Whisper models (same one-liners as in `desktop/install.sh`)
- [ ] System packages as needed: PortAudio, WebKitGTK/pywebview deps, mic access
- [ ] Config at `~/.jarvis/config.json` (desktop uses this path, not repo `config.json`)
- [ ] Anthropic key (or NVIDIA NIM free brain) in that file
- [ ] Run: `~/.jarvis/venv/bin/python desktop/jarvis.py`
- [ ] Expect gaps vs Mac: Calendar Automation, all-Spaces window hacks, `.command` launchers

## Out of scope / do not do

- [ ] Do **not** wire brain to llama.cpp `:11434` (this repo is Anthropic/NVIDIA NIM)
- [ ] Do **not** put project files in `$HOME` root or inside `~/jarvis-os`
- [ ] Do **not** commit `config.json` (gitignored) or API keys

## Quick commands (web)

```bash
cd /home/thomas-pashoulas/jarvis-second-brain
python3 build.py
python3 server.py   # then open http://127.0.0.1:4700
```

Stop server: find PID on `:4700` (`ss -ltnp | rg 4700`) and `kill <pid>`.
