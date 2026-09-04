#!/usr/bin/env python3
"""Jarvis desktop daemon — system-wide voice assistant.

Open-source stack: openWakeWord (wake word, offline) + faster-whisper (STT,
offline) + edge-tts (neural voice) + Anthropic API (agentic brain with shell,
files, notes, screen vision and long-term memory). A floating always-on-top
orb shows state. No browser required.

Wake it with "Hey Jarvis", two claps, or a click on the orb.
"""
import base64
import io
import json
import os
import platform
import queue
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
import webrtcvad

APP_DIR = Path(__file__).resolve().parent
JARVIS_HOME = Path.home() / ".jarvis"
JARVIS_HOME.mkdir(exist_ok=True)
CONFIG_PATH = JARVIS_HOME / "config.json"
MEMORY_PATH = JARVIS_HOME / "memory.md"
TASKS_PATH = JARVIS_HOME / "tasks.json"
HOME = str(Path.home())

DEFAULT_LOCAL_KEY_FILE = "/home/thomas-pashoulas/.cursor/deepseek-cursor-api.key"

DEFAULT_CONFIG = {
    "api_key": "PUT-YOUR-KEY-HERE",
    "model": "claude-sonnet-5",
    "voice": "pt-BR-AntonioNeural",
    "language": "pt",
    "notes_dir": "",
    "user_title": "senhora",
    "orb_x": None,
    "orb_y": None,
    "slack_bot_token": "",
    "slack_app_token": "",
    "outlook_client_id": "",
    "provider": "local",
    "nvidia_api_key": "",
    "nvidia_model": "openai/gpt-oss-120b",
    "local_base_url": "http://127.0.0.1:11434/v1",
    "local_model": "",
    "local_api_key_file": DEFAULT_LOCAL_KEY_FILE,
    "shortcuts": {},
    "voice_en": "en-GB-RyanNeural",
    "voice_fr": "fr-FR-HenriNeural",
    "user_name": "",
    "weather_city": "",
}

if not CONFIG_PATH.exists():
    CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False))
CFG = {**DEFAULT_CONFIG, **json.loads(CONFIG_PATH.read_text())}
API_KEY = os.environ.get("ANTHROPIC_API_KEY") or CFG["api_key"]


def save_orb_position(x, y):
    CFG["orb_x"], CFG["orb_y"] = x, y
    try:
        on_disk = json.loads(CONFIG_PATH.read_text())
        on_disk["orb_x"], on_disk["orb_y"] = x, y
        CONFIG_PATH.write_text(json.dumps(on_disk, indent=2, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass

STATE = {"mode": "idle", "text": ""}  # idle|listening|thinking|speaking
WAKE_QUEUE = queue.Queue()
TASKS_LOCK = threading.Lock()
INTERACTION_LOCK = threading.Lock()
INTERACTION_GENERATION = 0


def set_state(mode, text=""):
    STATE["mode"] = mode
    STATE["text"] = text


def _new_interaction_generation():
    global INTERACTION_GENERATION
    with INTERACTION_LOCK:
        INTERACTION_GENERATION += 1
        return INTERACTION_GENERATION


def _interaction_is_current(generation):
    with INTERACTION_LOCK:
        return generation == INTERACTION_GENERATION


# ---------------------------------------------------------------- tools
DANGEROUS = re.compile(
    r"\b(sudo|rm\s+-rf\s+[/~]|mkfs|diskutil\s+erase|shutdown|reboot|killall\s+Finder"
    r"|format\s+[a-z]:|del\s+/s|rd\s+/s)\b", re.I)


def tool_run_command(args):
    cmd = args["command"]
    if DANGEROUS.search(cmd):
        return "BLOCKED: that command is too dangerous to run unattended."
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=120, cwd=HOME)
        out = (r.stdout + r.stderr).strip()
        return out[:6000] or "(command ran, no output)"
    except subprocess.TimeoutExpired:
        return "(timed out after 120s)"
    except Exception as e:  # noqa: BLE001
        return f"(error: {e})"


def tool_run_claude_code(args):
    """Delegates real work to the Claude Code CLI in a specific project folder -
    for actual coding/writing tasks, not simple one-liners (use run_command for those).
    Runs on whatever plan 'claude' is logged into on this Mac (usually the user's
    Claude subscription, separate from the Anthropic API key billing)."""
    if CFG.get("provider") == "local":
        return ("(run_claude_code disabled while provider=local — use run_command "
                "or switch to Anthropic)")
    folder = os.path.expanduser(args["folder"])
    if not os.path.isdir(folder):
        return f"(folder not found: {folder})"
    cmd = ["claude", "--print", "--model", args.get("model", "sonnet")]
    if args.get("effort"):
        cmd += ["--effort", args["effort"]]
    cmd.append(args["prompt"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=folder)
        out = (r.stdout + r.stderr).strip()
        return out[:6000] or "(claude code ran, no output)"
    except FileNotFoundError:
        return "(error: 'claude' CLI not found - is Claude Code installed and on PATH?)"
    except subprocess.TimeoutExpired:
        return "(claude code timed out after 600s)"
    except Exception as e:  # noqa: BLE001
        return f"(error: {e})"


def tool_screenshot(_args):
    import mss
    from PIL import Image
    with mss.mss() as s:
        shot = s.grab(s.monitors[1])
        img = Image.frombytes("RGB", shot.size, shot.rgb)
    img.thumbnail((1568, 1568))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return {"type": "image", "data": base64.b64encode(buf.getvalue()).decode()}


def tool_search_notes(args):
    root = CFG.get("notes_dir")
    if not root or not os.path.isdir(root):
        return "(notes_dir not set in config.json)"
    words = set(re.findall(r"\w{3,}", args["query"].lower()))
    scored = []
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.endswith(".md"):
                p = os.path.join(r, f)
                text = open(p, encoding="utf-8", errors="ignore").read()
                tl, title = text.lower(), os.path.splitext(f)[0].lower()
                s = sum(tl.count(w) for w in words) + sum(6 for w in words if w in title)
                if s:
                    scored.append((s, p, text))
    scored.sort(reverse=True)
    return "\n\n".join(f"=== {os.path.basename(p)} ===\n{t[:1200]}"
                       for _s, p, t in scored[:5]) or "(nothing found in the notes)"


def tool_remember(args):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(MEMORY_PATH, "a", encoding="utf-8") as f:
        f.write(f"- [{stamp}] {args['fact']}\n")
    return "remembered"


# ---------------------------------------------------------------- global tasks
def _load_tasks():
    """Read the single task list shared by all projects on this Mac."""
    try:
        data = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _save_tasks(tasks):
    TASKS_PATH.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalise_due_date(value):
    if not value:
        return ""
    value = str(value).strip()
    if value.lower() in {"hoje", "today"}:
        return datetime.now().strftime("%Y-%m-%d")
    if value.lower() in {"amanhã", "amanha", "tomorrow"}:
        return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return value


def _task_label(task):
    due = task.get("due_date") or "sem prazo"
    project = task.get("project") or "Geral"
    priority = task.get("priority") or "normal"
    return f"[{task.get('id', '?')}] {task.get('title', '')} · {project} · {due} · {priority}"


# Microsoft To Do is the cloud source of truth for personal tasks. The local
# JSON remains a cache/fallback so Jarvis still works when Outlook is offline.
OUTLOOK_TASK_LIST_NAME = "Jarvis"
OUTLOOK_TIMEZONE = "Romance Standard Time"
TASKS_REMOTE_LAST_SYNC = 0.0
TASKS_REMOTE_SYNC_TTL = 30.0


def _outlook_task_list(token, create=False, name=None):
    import requests
    name = name or OUTLOOK_TASK_LIST_NAME
    try:
        r = requests.get("https://graph.microsoft.com/v1.0/me/todo/lists",
                         headers={"Authorization": f"Bearer {token}"}, timeout=12)
        r.raise_for_status()
        lists = r.json().get("value", [])
        for item in lists:
            if item.get("displayName", "").strip().lower() == name.lower():
                return item
        if create:
            r = requests.post("https://graph.microsoft.com/v1.0/me/todo/lists",
                              headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                              json={"displayName": name}, timeout=12)
            r.raise_for_status()
            return r.json()
    except Exception as e:  # noqa: BLE001
        print("Outlook To Do list unavailable:", e)
    return None


def _create_outlook_task(task):
    try:
        token, err = _outlook_token()
    except Exception as e:  # noqa: BLE001
        print("Outlook To Do auth unavailable:", e)
        return None
    if err:
        return None
    list_info = _outlook_task_list(token, create=True)
    if not list_info:
        return None
    importance = {"high": "high", "low": "low"}.get(task.get("priority"), "normal")
    payload = {"title": task.get("title", ""), "importance": importance, "status": "notStarted"}
    due = task.get("due_date")
    if due:
        payload["dueDateTime"] = {"dateTime": f"{due}T00:00:00", "timeZone": OUTLOOK_TIMEZONE}
    notes = []
    if task.get("project"):
        notes.append(f"Projeto: {task['project']}")
    if task.get("notes"):
        notes.append(task["notes"])
    if notes:
        payload["body"] = {"content": "\n".join(notes), "contentType": "text"}
    try:
        import requests
        r = requests.post(
            f"https://graph.microsoft.com/v1.0/me/todo/lists/{list_info['id']}/tasks",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload, timeout=15)
        r.raise_for_status()
        result = r.json()
        result["list_id"] = list_info["id"]
        return result
    except Exception as e:  # noqa: BLE001
        print("Outlook To Do task creation failed:", e)
        return None


def _complete_outlook_task(task):
    try:
        token, err = _outlook_token()
        if err:
            return False
        import requests
        r = requests.patch(
            f"https://graph.microsoft.com/v1.0/me/todo/lists/{task['remote_list_id']}/tasks/{task['remote_id']}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"status": "completed"}, timeout=15)
        return r.status_code == 200
    except Exception as e:  # noqa: BLE001
        print("Outlook To Do task completion failed:", e)
        return False


def _sync_outlook_tasks(force=False):
    global TASKS_REMOTE_LAST_SYNC
    now = time.time()
    if not force and now - TASKS_REMOTE_LAST_SYNC < TASKS_REMOTE_SYNC_TTL:
        return
    TASKS_REMOTE_LAST_SYNC = now
    try:
        token, err = _outlook_token()
        if err:
            return
        list_info = _outlook_task_list(token, create=True)
        if not list_info:
            return
        import requests
        r = requests.get(
            f"https://graph.microsoft.com/v1.0/me/todo/lists/{list_info['id']}/tasks",
            headers={"Authorization": f"Bearer {token}"},
            params={"$top": 100}, timeout=15)
        r.raise_for_status()
        remote_tasks = r.json().get("value", [])
        with TASKS_LOCK:
            local_tasks = _load_tasks()
            by_remote = {t.get("remote_id"): t for t in local_tasks if t.get("remote_id")}
            for remote in remote_tasks:
                local = by_remote.get(remote.get("id"))
                if local is None:
                    created = datetime.now().isoformat(timespec="seconds")
                    local = {"id": f"T-REMOTE-{remote.get('id', '')[:8]}", "created_at": created,
                             "completed_at": "", "notes": "", "project": "Geral"}
                    local_tasks.append(local)
                local["title"] = remote.get("title", "")
                local["due_date"] = (remote.get("dueDateTime") or {}).get("dateTime", "")[:10]
                local["priority"] = remote.get("importance", "normal")
                local["status"] = "done" if remote.get("status") == "completed" else "open"
                local["source"] = "microsoft_todo"
                local["remote_id"] = remote.get("id", "")
                local["remote_list_id"] = list_info["id"]
            # Existing local-only tasks are migrated once the Outlook connection exists.
            for local in local_tasks:
                if not local.get("remote_id") and local.get("status", "open") == "open":
                    remote = _create_outlook_task(local)
                    if remote:
                        local["source"] = "microsoft_todo"
                        local["remote_id"] = remote.get("id", "")
                        local["remote_list_id"] = remote.get("list_id", list_info["id"])
            _save_tasks(local_tasks)
    except Exception as e:  # noqa: BLE001
        print("Outlook To Do sync failed:", e)


def tool_add_task(args):
    title = (args.get("title") or "").strip()
    if not title:
        return "Não consegui criar a tarefa: falta o título."
    now = datetime.now()
    task = {
        "id": f"T-{now.strftime('%Y%m%d-%H%M%S')}-{os.urandom(2).hex().upper()}",
        "title": title,
        "project": (args.get("project") or "Geral").strip(),
        "due_date": _normalise_due_date(args.get("due_date")),
        "priority": (args.get("priority") or "normal").strip().lower(),
        "status": "open",
        "notes": (args.get("notes") or "").strip(),
        "created_at": now.isoformat(timespec="seconds"),
        "completed_at": "",
        "source": "local",
        "remote_id": "",
        "remote_list_id": "",
    }
    remote = _create_outlook_task(task)
    if remote:
        task["source"] = "microsoft_todo"
        task["remote_id"] = remote.get("id", "")
        task["remote_list_id"] = remote.get("list_id", "")
    with TASKS_LOCK:
        tasks = _load_tasks()
        tasks.append(task)
        _save_tasks(tasks)
    where = " no Microsoft To Do" if task["source"] == "microsoft_todo" else " localmente (Outlook To Do ainda não conectado)"
    return f"Tarefa criada{where}: {_task_label(task)}"


def tool_list_tasks(args):
    status = (args.get("status") or "open").strip().lower()
    scope = (args.get("scope") or "today").strip().lower()
    project = (args.get("project") or "").strip().lower()
    today = datetime.now().strftime("%Y-%m-%d")
    _sync_outlook_tasks()
    with TASKS_LOCK:
        tasks = _load_tasks()

    filtered = []
    for task in tasks:
        if status != "all" and task.get("status", "open") != status:
            continue
        if project and project not in task.get("project", "").lower():
            continue
        due = task.get("due_date", "")
        if scope in {"today", "hoje"} and due and due > today:
            continue
        if scope in {"overdue", "atrasadas", "atrasada"} and (not due or due >= today):
            continue
        filtered.append(task)

    filtered.sort(key=lambda t: (t.get("due_date") or "9999-99-99", t.get("priority") != "high", t.get("created_at", "")))
    if not filtered:
        return "Nenhuma tarefa encontrada nesse filtro."
    header = f"{len(filtered)} tarefa(s):"
    return header + "\n" + "\n".join(_task_label(t) for t in filtered[:20])


def tool_complete_task(args):
    needle = (args.get("task_id") or args.get("query") or "").strip().lower()
    if not needle:
        return "Diga o ID ou uma parte do nome da tarefa que deseja concluir."
    with TASKS_LOCK:
        tasks = _load_tasks()
        matches = [t for t in tasks if needle in t.get("id", "").lower() or needle in t.get("title", "").lower()]
        if not matches:
            return "Não encontrei essa tarefa."
        if len(matches) > 1:
            return "Encontrei mais de uma: " + " | ".join(_task_label(t) for t in matches[:5])
        task = matches[0]
        task["status"] = "done"
        task["completed_at"] = datetime.now().isoformat(timespec="seconds")
        if task.get("remote_id") and task.get("remote_list_id"):
            _complete_outlook_task(task)
        _save_tasks(tasks)
    return f"Tarefa concluída: {_task_label(task)}"


def get_task_summary():
    _sync_outlook_tasks()
    today = datetime.now().strftime("%Y-%m-%d")
    with TASKS_LOCK:
        tasks = _load_tasks()
    open_tasks = [t for t in tasks if t.get("status", "open") == "open"]
    overdue = [t for t in open_tasks if t.get("due_date") and t["due_date"] < today]
    today_tasks = [t for t in open_tasks if not t.get("due_date") or t.get("due_date") <= today]
    today_tasks.sort(key=lambda t: (t.get("due_date") or "9999-99-99", t.get("priority") != "high"))
    return {
        "open": len(open_tasks),
        "overdue": len(overdue),
        "today": len(today_tasks),
        "items": [{"title": t.get("title", ""), "project": t.get("project", "Geral"),
                   "due_date": t.get("due_date", ""), "priority": t.get("priority", "normal")}
                  for t in today_tasks[:5]],
    }


# Método Momento (Move AI agency) lead-gen sheets - same spreadsheet already
# powering the HUD's outreach card. gid=leads is the pipeline (one row per
# lead), gid=messages is the outreach log (one row per message sent).
METODO_MOMENTO_SHEET_ID = "1eC2im7e5U3IvJmBm783t0X-xAXi8RSmqowY-41sfDmM"
METODO_MOMENTO_LEADS_GID = "1547340779"
METODO_MOMENTO_MSGS_GID = "325599469"


def _fetch_csv_rows(sheet_id, gid):
    import csv
    import requests
    r = requests.get(f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}",
                     timeout=10)
    r.raise_for_status()
    reader = csv.reader(r.text.splitlines())
    header = next(reader, [])
    return header, list(reader)


def tool_read_metodo_momento(args):
    """Searches the Método Momento leads pipeline and outreach message log
    for a keyword (company name, status like 'call marcada', a lead ID,
    etc.) and returns matching rows - for questions like 'what's the status
    of lead X' or 'how many leads are in negotiation', not just yesterday's
    fixed stats already shown on the home screen."""
    query = args.get("query", "").strip().lower()
    try:
        results = []
        lead_header, lead_rows = _fetch_csv_rows(METODO_MOMENTO_SHEET_ID, METODO_MOMENTO_LEADS_GID)
        for row in lead_rows:
            if not query or any(query in (cell or "").lower() for cell in row):
                results.append("LEAD: " + " | ".join(f"{h}: {c}" for h, c in zip(lead_header, row) if c))
            if len(results) >= 15:
                break
        if query:
            msg_header, msg_rows = _fetch_csv_rows(METODO_MOMENTO_SHEET_ID, METODO_MOMENTO_MSGS_GID)
            added = 0
            for row in msg_rows:
                if any(query in (cell or "").lower() for cell in row):
                    results.append("MENSAGEM: " + " | ".join(f"{h}: {c}" for h, c in zip(msg_header, row) if c))
                    added += 1
                if added >= 10:
                    break
        return "\n\n".join(results)[:6000] or "(nothing matched in the Método Momento sheets)"
    except Exception as e:  # noqa: BLE001
        return f"(error reading Método Momento sheets: {e})"


CREATE_EVENT_SCRIPT = """
on run {evTitle, y, mo, d, h, mi, durMin}
    set startD to current date
    set year of startD to (y as integer)
    set month of startD to (mo as integer)
    set day of startD to (d as integer)
    set hours of startD to (h as integer)
    set minutes of startD to (mi as integer)
    set seconds of startD to 0
    set endD to startD + ((durMin as integer) * minutes)
    tell application "Calendar"
        tell (first calendar whose writable is true)
            make new event with properties {summary:evTitle, start date:startD, end date:endD}
        end tell
    end tell
    return "ok"
end run
"""


def _create_google_event(title, start_dt, end_dt):
    if not GOOGLE_TOKEN_PATH.exists():
        return False
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        creds = Credentials.from_authorized_user_info(
            json.loads(GOOGLE_TOKEN_PATH.read_text()),
            ["https://www.googleapis.com/auth/calendar"])
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            GOOGLE_TOKEN_PATH.write_text(creds.to_json())
        service = build("calendar", "v3", credentials=creds)
        service.events().insert(calendarId="primary", body={
            "summary": title,
            "start": {"dateTime": start_dt.isoformat()},
            "end": {"dateTime": end_dt.isoformat()},
        }).execute()
        return True
    except Exception as e:  # noqa: BLE001
        print("Google event creation skipped/failed:", e)
        return False


def tool_create_calendar_event(args):
    try:
        y, mo, d = (int(x) for x in args["date"].split("-"))
        h, mi = (int(x) for x in args["time"].split(":"))
        dur = int(args.get("duration_minutes", 60))
        title = args["title"]
    except (KeyError, ValueError) as e:
        return f"(bad arguments: {e})"

    start_dt = datetime(y, mo, d, h, mi)
    end_dt = start_dt + timedelta(minutes=dur)
    target = (args.get("calendar") or "outlook").strip().lower()
    made_outlook, made_mac, made_google = False, False, False
    errors = []

    if target in {"outlook", "all"}:
        made_outlook, outlook_error = _create_outlook_event(title, start_dt, end_dt, args)
        if outlook_error:
            errors.append(outlook_error)

    if target in {"mac", "all"}:
        try:
            r = subprocess.run(["osascript", "-e", CREATE_EVENT_SCRIPT, title,
                               str(y), str(mo), str(d), str(h), str(mi), str(dur)],
                               capture_output=True, text=True, timeout=15)
            made_mac = r.returncode == 0 and "ok" in r.stdout
        except Exception as e:  # noqa: BLE001
            errors.append(f"Mac event creation failed: {e}")

    if target in {"google", "all"}:
        made_google = _create_google_event(title, start_dt, end_dt)

    if made_outlook or made_mac or made_google:
        where = " and ".join(w for w, ok in [("Outlook Calendar", made_outlook), ("Mac Calendar", made_mac), ("Google Calendar", made_google)] if ok)
        return f"Created '{title}' on {args['date']} at {args['time']} in: {where}."
    return "(não consegui criar a reunião: " + " | ".join(errors or ["calendário não configurado"]) + ")"


CALENDAR_SCRIPT = """
on run {daysAhead}
    set startD to current date
    set time of startD to 0
    set endD to startD + ((daysAhead as integer) * days)
    set out to ""
    tell application "Calendar"
        repeat with cal in calendars
            try
                set evts to (every event of cal whose start date >= startD and start date < endD)
                repeat with e in evts
                    set out to out & (name of cal) & ": " & (summary of e) & " -- " & (start date of e as string) & linefeed
                end repeat
            end try
        end repeat
    end tell
    return out
end run
"""


def tool_read_calendar(args):
    days = max(1, min(int(args.get("days_ahead", 1)), 14))
    try:
        r = subprocess.run(["osascript", "-e", CALENDAR_SCRIPT, str(days)],
                           capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            if "-1743" in r.stderr or "not allowed" in r.stderr.lower():
                return ("BLOCKED: macOS is asking for Calendar access. Open System Settings > "
                         "Privacy & Security > Automation, and allow this app to control Calendar, "
                         "then ask me again.")
            return f"(calendar error: {r.stderr.strip()[:300]})"
        return r.stdout.strip() or "(nothing on the calendar in that window)"
    except Exception as e:  # noqa: BLE001
        return f"(error: {e})"


GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]  # read + create events
GOOGLE_CREDS_PATH = JARVIS_HOME / "google_credentials.json"
GOOGLE_TOKEN_PATH = JARVIS_HOME / "google_token.json"


def tool_read_google_calendar(args):
    if not GOOGLE_TOKEN_PATH.exists():
        return ("BLOCKED: Google Calendar isn't connected yet. Run "
                 "'python google_calendar_setup.py' once from the desktop/ folder "
                 "(see the README's Google Calendar setup section) to link it.")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_info(
            json.loads(GOOGLE_TOKEN_PATH.read_text()), GOOGLE_SCOPES)
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            GOOGLE_TOKEN_PATH.write_text(creds.to_json())

        days = max(1, min(int(args.get("days_ahead", 1)), 14))
        now = datetime.now()
        time_min = now.replace(hour=0, minute=0, second=0).isoformat() + "Z"
        time_max = (now.replace(hour=0, minute=0, second=0) + timedelta(days=days)).isoformat() + "Z"

        service = build("calendar", "v3", credentials=creds)
        events = service.events().list(
            calendarId="primary", timeMin=time_min, timeMax=time_max,
            singleEvents=True, orderBy="startTime").execute().get("items", [])
        if not events:
            return "(nothing on the Google Calendar in that window)"
        lines = []
        for e in events:
            start = e["start"].get("dateTime", e["start"].get("date"))
            lines.append(f"{e.get('summary', '(no title)')} -- {start}")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"(google calendar error: {e})"


OUTLOOK_CACHE_PATH = JARVIS_HOME / "outlook_token_cache.bin"
OUTLOOK_SCOPES = ["Calendars.ReadWrite", "Tasks.ReadWrite"]


def _outlook_token(scopes=None):
    import msal
    scopes = scopes or OUTLOOK_SCOPES
    client_id = CFG.get("outlook_client_id")
    if not client_id:
        return None, ("BLOCKED: Outlook Calendar isn't set up yet - add 'outlook_client_id' "
                        "to config.json (see the README's Outlook Calendar setup section).")
    cache = msal.SerializableTokenCache()
    if OUTLOOK_CACHE_PATH.exists():
        cache.deserialize(OUTLOOK_CACHE_PATH.read_text())
    app = msal.PublicClientApplication(
        client_id, authority="https://login.microsoftonline.com/common", token_cache=cache)
    accounts = app.get_accounts()
    result = app.acquire_token_silent(scopes, account=accounts[0]) if accounts else None
    if cache.has_state_changed:
        OUTLOOK_CACHE_PATH.write_text(cache.serialize())
    if not result or "access_token" not in result:
        return None, ("BLOCKED: Outlook Calendar isn't connected yet. Run "
                       "'python outlook_calendar_setup.py' once from the desktop/ folder "
                       "to re-authorize Calendars.ReadWrite and Tasks.ReadWrite.")
    return result["access_token"], None


def tool_read_outlook_calendar(args):
    token, err = _outlook_token()
    if err:
        return err
    try:
        import requests
        days = max(1, min(int(args.get("days_ahead", 1)), 14))
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0).isoformat()
        end = (now.replace(hour=0, minute=0, second=0) + timedelta(days=days)).isoformat()
        r = requests.get(
            "https://graph.microsoft.com/v1.0/me/calendarView",
            headers={"Authorization": f"Bearer {token}", "Prefer": f'outlook.timezone="{OUTLOOK_TIMEZONE}"'},
            params={"startDateTime": start, "endDateTime": end, "$orderby": "start/dateTime"},
            timeout=15)
        r.raise_for_status()
        events = r.json().get("value", [])
        if not events:
            return "(nothing on the Outlook Calendar in that window)"
        return "\n".join(
            f"{e.get('subject', '(no title)')} -- {e.get('start', {}).get('dateTime', '')}"
            for e in events)
    except Exception as e:  # noqa: BLE001
        return f"(outlook calendar error: {e})"


def _create_outlook_event(title, start_dt, end_dt, args):
    token, err = _outlook_token()
    if err:
        return False, err
    payload = {
        "subject": title,
        "start": {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": OUTLOOK_TIMEZONE},
        "end": {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": OUTLOOK_TIMEZONE},
        "isReminderOn": True,
        "reminderMinutesBeforeStart": int(args.get("reminder_minutes", 15)),
    }
    if args.get("location"):
        payload["location"] = {"displayName": args["location"]}
    if args.get("body"):
        payload["body"] = {"contentType": "text", "content": args["body"]}
    attendees = args.get("attendees") or []
    if isinstance(attendees, str):
        attendees = [a.strip() for a in attendees.split(",") if a.strip()]
    if attendees:
        payload["attendees"] = [{"emailAddress": {"address": email}, "type": "required"}
                                 for email in attendees]
    try:
        import requests
        r = requests.post(
            "https://graph.microsoft.com/v1.0/me/calendar/events",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload, timeout=15)
        r.raise_for_status()
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, f"Outlook event creation failed: {e}"


TOOL_DEFS = [
    {"name": "run_command",
     "description": "Run a shell command on the computer (download files with curl, open apps, list/read/move files, etc.). Destructive commands are blocked.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "screenshot",
     "description": "Capture the screen NOW and return the image - use whenever asked what is on screen, in any application.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "run_claude_code",
     "description": "Open the Claude Code CLI inside a specific project folder and give it a task/message - for real coding or writing work, not quick one-liners. Runs on the user's own Claude Code login on this Mac.",
     "input_schema": {"type": "object", "properties": {
         "folder": {"type": "string", "description": "Absolute path to the project folder (can use ~)"},
         "prompt": {"type": "string", "description": "The instruction/message to give Claude Code"},
         "model": {"type": "string", "description": "Model alias, e.g. 'sonnet', 'opus', 'fable' (default: sonnet)"},
         "effort": {"type": "string", "description": "Optional effort level: low, medium, high, xhigh, max"}},
         "required": ["folder", "prompt"]}},
    {"name": "search_notes",
     "description": "Search the user's markdown second-brain notes (Obsidian vault).",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "read_google_calendar",
     "description": "Read events from the user's Google Calendar for the next N days (default 1 = today). Use this alongside read_calendar if asked generally about 'my calendar/agenda'.",
     "input_schema": {"type": "object", "properties": {
         "days_ahead": {"type": "integer", "description": "How many days ahead to look, 1-14"}}}},
    {"name": "remember",
     "description": "Store a fact in long-term memory (preferences, decisions, things to remember).",
     "input_schema": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}},
    {"name": "add_task",
     "description": "Create a task in Jarvis's single global task list shared by all projects. Use whenever the user asks to add, remember, register, or schedule a task. Never assume the task belongs to Método Momento unless the user says so.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"},
         "project": {"type": "string", "description": "Project name, or Geral if it is a general task"},
         "due_date": {"type": "string", "description": "YYYY-MM-DD, hoje, amanhã, or empty"},
         "priority": {"type": "string", "description": "low, normal, or high"},
         "notes": {"type": "string"}}, "required": ["title"]}},
    {"name": "list_tasks",
     "description": "List tasks from the global Jarvis task list. Use for questions like what do I have today, what is overdue, or what tasks belong to a project.",
     "input_schema": {"type": "object", "properties": {
         "status": {"type": "string", "description": "open, done, or all; default open"},
         "scope": {"type": "string", "description": "today, overdue, or all; default today"},
         "project": {"type": "string"}}}},
    {"name": "complete_task",
     "description": "Mark one global Jarvis task as completed using its ID or a distinctive part of its title.",
     "input_schema": {"type": "object", "properties": {
         "task_id": {"type": "string"},
         "query": {"type": "string"}}}},
    {"name": "read_calendar",
     "description": "Read events from the Mac Calendar app for the next N days (default 1 = today).",
     "input_schema": {"type": "object", "properties": {
         "days_ahead": {"type": "integer", "description": "How many days ahead to look, 1-14"}}}},
    {"name": "read_outlook_calendar",
     "description": "Read events from the user's Outlook/Microsoft 365 Calendar for the next N days (default 1 = today). Use alongside the other calendar tools if asked generally about 'my calendar/agenda'.",
     "input_schema": {"type": "object", "properties": {
         "days_ahead": {"type": "integer", "description": "How many days ahead to look, 1-14"}}}},
    {"name": "create_calendar_event",
     "description": "Creates a real event in Outlook Calendar by default. Use whenever asked to schedule, book, or mark a meeting. Do not claim it was created until the tool confirms success. Use calendar=mac, google, or all only when explicitly requested.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"},
         "date": {"type": "string", "description": "ISO date, e.g. 2026-07-09"},
         "time": {"type": "string", "description": "24h HH:MM, e.g. 14:30"},
         "duration_minutes": {"type": "integer", "description": "default 60"},
         "calendar": {"type": "string", "description": "outlook by default; mac, google, or all"},
         "location": {"type": "string"},
         "body": {"type": "string"},
         "attendees": {"type": "array", "items": {"type": "string"}},
         "reminder_minutes": {"type": "integer", "description": "default 15"}},
         "required": ["title", "date", "time"]}},
    {"name": "read_metodo_momento",
     "description": "Searches the Método Momento (Move AI agency) lead-gen spreadsheets: the leads pipeline and the outreach message log. Use for questions about a specific lead/company, campaign status, or counts beyond the fixed 'yesterday' stats already on the home screen.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Company name, lead ID, status keyword, etc. Empty returns a recent sample."}}}},
]
TOOL_FNS = {"run_command": tool_run_command, "screenshot": tool_screenshot,
            "run_claude_code": tool_run_claude_code,
            "search_notes": tool_search_notes, "remember": tool_remember,
            "add_task": tool_add_task, "list_tasks": tool_list_tasks,
            "complete_task": tool_complete_task,
            "read_calendar": tool_read_calendar,
            "read_google_calendar": tool_read_google_calendar,
            "read_outlook_calendar": tool_read_outlook_calendar,
            "create_calendar_event": tool_create_calendar_event,
            "read_metodo_momento": tool_read_metodo_momento}


# ---------------------------------------------------------------- brain
HISTORY_PATH = JARVIS_HOME / "conversation.json"
HISTORY = []
try:
    # only resume if the last conversation was recent - carrying forward a
    # 3-day-old exchange as "context" would just confuse a fresh session
    if time.time() - HISTORY_PATH.stat().st_mtime < 3 * 3600:
        HISTORY = json.loads(HISTORY_PATH.read_text())[-24:]
except (FileNotFoundError, json.JSONDecodeError, OSError):
    pass


def _save_history():
    try:
        HISTORY_PATH.write_text(json.dumps(HISTORY[-24:], ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass


_last_lang = None
LANG_TAG_RE = re.compile(r"\s*\[LANG:(pt|en|fr)\]\s*$", re.I)


def extract_lang_tag(text):
    """Strips the trailing [LANG:xx] marker the model is instructed to add,
    returning (clean_text, lang_code_or_None) - drives which TTS voice speaks
    the reply, without relying on a text-language-guesser (too unreliable on
    short sentences)."""
    m = LANG_TAG_RE.search(text)
    if not m:
        return text, None
    return LANG_TAG_RE.sub("", text), m.group(1).lower()


def system_prompt():
    memory = MEMORY_PATH.read_text(encoding="utf-8")[-4000:] if MEMORY_PATH.exists() else "(empty)"
    lang = {"pt": "Brazilian Portuguese", "en": "English", "es": "Spanish"}.get(CFG["language"], CFG["language"])
    shortcuts = CFG.get("shortcuts") or {}
    shortcuts_block = "\n".join(f'- "{name}" -> {url}' for name, url in shortcuts.items()) or "(none configured)"
    open_cmd = "open" if platform.system() == "Darwin" else "start" if platform.system() == "Windows" else "xdg-open"
    return f"""You are Jarvis: an impeccably polite, dry-witted British butler. Default language is {lang}, but switch fluently to English or French whenever the user speaks or writes in that language, or explicitly asks for it - then switch back once they do. Address the user as "{CFG['user_title']}" occasionally (not every sentence). One genuinely funny line beats three bland ones.

You run as a system assistant on {platform.system()} with real tools: shell, screen capture, notes search, the Mac Calendar, Google Calendar, Outlook Calendar, a single global task list shared by every project, the Método Momento sales system, delegating real coding/writing tasks to Claude Code in a project folder, and long-term memory. Act: when asked to download, open, find or do something on the computer, DO it with run_command instead of explaining how - create a missing folder first if needed rather than giving up. Use the task tools for personal or project tasks; always include the project when it is known, and use Geral otherwise. Use run_claude_code (not run_command) for substantial project work - writing plans, code, or documents inside a folder - since it gives Claude Code its own context window for that task. iCloud Drive files (including the Obsidian vault) are regular folders under the user's home directory - read them with run_command like any other file. If something fails, try an alternative path before giving up.

Named shortcuts (open the EXACT url below via run_command with `{open_cmd} "URL"` - never guess or alter the URL):
{shortcuts_block}

Your answers are SPOKEN aloud: keep them short (1-3 sentences), no markdown, no lists, no long URLs. Important facts you learn about the user -> use remember.

CRITICAL: end every reply with the language you just answered in, on its own final line, exactly like one of: [LANG:pt] [LANG:en] [LANG:fr] - this drives which voice speaks it, so never skip it and never explain it.

Date and time: {datetime.now().strftime('%A, %Y-%m-%d %H:%M')}
Long-term memory:
{memory}"""


def _read_local_api_key():
    path = Path(CFG.get("local_api_key_file") or DEFAULT_LOCAL_KEY_FILE).expanduser()
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def think(user_text):
    provider = CFG.get("provider")
    if provider == "local":
        return think_openai_compatible(
            user_text,
            base_url=CFG.get("local_base_url") or "http://127.0.0.1:11434/v1",
            api_key=_read_local_api_key(),
            model=CFG.get("local_model") or "",
            local_mode=True,
        )
    if provider == "nvidia":
        return think_openai_compatible(
            user_text,
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=CFG.get("nvidia_api_key") or "",
            model=CFG.get("nvidia_model") or "openai/gpt-oss-120b",
            local_mode=False,
        )
    return think_anthropic(user_text)


def think_anthropic(user_text):
    import anthropic
    client = anthropic.Anthropic(api_key=API_KEY)
    HISTORY.append({"role": "user", "content": user_text})
    del HISTORY[:-24]
    local = list(HISTORY)
    for _ in range(10):
        resp = client.messages.create(
            model=CFG["model"], max_tokens=500, system=system_prompt(),
            tools=TOOL_DEFS, messages=local)
        if resp.stop_reason != "tool_use":
            global _last_lang
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            text, _last_lang = extract_lang_tag(text or "...")
            HISTORY.append({"role": "assistant", "content": text or "..."})
            _save_history()
            return text or "..."
        local.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                out = TOOL_FNS[block.name](block.input or {})
                if isinstance(out, dict) and out.get("type") == "image":
                    content = [{"type": "image", "source": {
                        "type": "base64", "media_type": "image/jpeg", "data": out["data"]}}]
                else:
                    content = str(out)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": content})
        local.append({"role": "user", "content": results})
    return "I got lost in my own tools. Embarrassing. Could you repeat that?"


def tool_describe_screen(_args):
    """Used when the OpenAI-compatible brain can't see images. NVIDIA mode may
    borrow Anthropic vision; local mode stays blind (no cloud LLM)."""
    if CFG.get("provider") == "local":
        return ("(blind locally — provider=local has no vision; describe the "
                "screen in words or switch provider)")
    shot = tool_screenshot({})
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=API_KEY)
        resp = client.messages.create(
            model="claude-sonnet-5", max_tokens=400,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": shot["data"]}},
                {"type": "text", "text": "Describe concisely (2-4 sentences) what is visible on this screen, "
                                          "focused on whatever the user likely wants to know about."},
            ]}])
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as e:  # noqa: BLE001
        return f"(couldn't analyze the screen: {e})"


TOOL_FNS["describe_screen"] = tool_describe_screen


def _openai_tool_defs(local_mode=False):
    """OpenAI function tools. Local mode drops screenshot + Claude Code;
    NVIDIA keeps describe_screen (may call Anthropic vision)."""
    skip = {"screenshot"}
    if local_mode:
        skip.add("run_claude_code")
    defs = [
        {"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
        for t in TOOL_DEFS if t["name"] not in skip
    ]
    defs.append({"type": "function", "function": {
        "name": "describe_screen",
        "description": "Describes what's currently on screen. Use whenever asked about the screen, an open app, or 'what am I looking at' - even though this brain can't see directly, this tool can.",
        "parameters": {"type": "object", "properties": {}}}})
    return defs


def _resolve_openai_model(client, model):
    model = (model or "").strip()
    if model:
        return model
    try:
        ids = [m.id for m in client.models.list().data if getattr(m, "id", None)]
        return ids[0] if ids else ""
    except Exception:  # noqa: BLE001
        return ""


def think_openai_compatible(user_text, base_url, api_key, model, local_mode=False):
    """Agent loop against any OpenAI-compatible /v1 endpoint (local llama-server
    or NVIDIA NIM)."""
    global _last_lang
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=api_key or "local")
    resolved = _resolve_openai_model(client, model)
    if not resolved:
        return ("Local brain has no model loaded, sir — is llama-server up on "
                ":11434?" if local_mode else "No model available on that endpoint.")
    HISTORY.append({"role": "user", "content": user_text})
    del HISTORY[:-24]
    local = [{"role": "system", "content": system_prompt()}] + list(HISTORY)
    tool_defs = _openai_tool_defs(local_mode=local_mode)
    try:
        for _ in range(10):
            resp = client.chat.completions.create(
                model=resolved, max_tokens=500,
                tools=tool_defs, tool_choice="auto", messages=local)
            msg = resp.choices[0].message
            if not msg.tool_calls:
                text = (msg.content or "...").strip()
                text, _last_lang = extract_lang_tag(text)
                HISTORY.append({"role": "assistant", "content": text})
                _save_history()
                return text
            local.append({"role": "assistant", "content": msg.content, "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                out = TOOL_FNS[tc.function.name](args)
                local.append({"role": "tool", "tool_call_id": tc.id, "content": str(out)})
        return "I got lost in my own tools. Embarrassing. Could you repeat that?"
    except Exception as e:  # noqa: BLE001
        # Smaller local models often reject tools — retry once without them.
        if not local_mode:
            raise
        try:
            resp = client.chat.completions.create(
                model=resolved, max_tokens=500, messages=local)
            text = (resp.choices[0].message.content or "...").strip()
            text, _last_lang = extract_lang_tag(text)
            HISTORY.append({"role": "assistant", "content": text})
            _save_history()
            return text
        except Exception as e2:  # noqa: BLE001
            return f"Local brain hiccup: {e2 or e}"


# Back-compat alias used by older call sites / docs.
def think_nvidia(user_text):
    return think_openai_compatible(
        user_text,
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=CFG.get("nvidia_api_key") or "",
        model=CFG.get("nvidia_model") or "openai/gpt-oss-120b",
        local_mode=False,
    )

# ---------------------------------------------------------------- voice out
_play_lock = threading.Lock()


def _find_ffmpeg():
    """Apps launched at login (launchd/Task Scheduler) don't inherit the
    Terminal's PATH, so a plain 'ffmpeg' lookup silently fails there even
    though it works fine when started manually - which is exactly what
    caused TTS to quietly fall back to the crackly decoder after autostart
    was set up. Check common install locations directly instead of trusting
    PATH."""
    import shutil
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg",
                      "/usr/bin/ffmpeg", "C:\\ffmpeg\\bin\\ffmpeg.exe"):
        if os.path.exists(candidate):
            return candidate
    return None


_FFMPEG_PATH = _find_ffmpeg()


def _decode_audio(mp3_path):
    """Decode via ffmpeg when available - far more robust than libsndfile's
    mp3 support, which produces static/crackle on some clips. Falls back to
    soundfile if ffmpeg isn't installed."""
    if _FFMPEG_PATH:
        wav_path = mp3_path.with_suffix(".wav")
        try:
            subprocess.run(
                [_FFMPEG_PATH, "-y", "-loglevel", "error", "-i", str(mp3_path),
                 "-ar", "48000", "-ac", "1", str(wav_path)],
                check=True, timeout=15, capture_output=True)
            return sf.read(str(wav_path), dtype="float32")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
    return sf.read(str(mp3_path), dtype="float32")


def speak(text):
    import asyncio
    import edge_tts
    clean = re.sub(r"[*_#`\[\]]", "", text)
    path = JARVIS_HOME / "reply.mp3"
    voice = {"en": CFG.get("voice_en"), "fr": CFG.get("voice_fr")}.get(_last_lang) or CFG["voice"]

    async def gen():
        await edge_tts.Communicate(clean, voice, rate="+8%").save(str(path))
    try:
        asyncio.run(gen())
        data, sr = _decode_audio(path)
        set_state("speaking", text)
        with _play_lock:
            sd.play(data, sr, latency="high")
        sd.wait()
    except Exception as e:  # noqa: BLE001
        print("TTS failed:", e)
    finally:
        set_state("idle")


def interrupt_speech():
    sd.stop()


# ---------------------------------------------------------------- ears
SR = 16000
FRAME = 1280  # 80 ms, the step openwakeword expects
VAD_STEP = 320  # 20 ms sub-chunk, a valid webrtcvad frame size at 16 kHz
VAD = webrtcvad.Vad(3)  # 0 (lenient) - 3 (strict); 3 rejects the most background noise


def _is_speech(mono_int16):
    """Majority vote across 20 ms sub-chunks - real voice-activity detection
    instead of a raw volume threshold, so background noise doesn't fool it
    and quiet trailing syllables don't get clipped."""
    votes = total = 0
    for i in range(0, len(mono_int16) - VAD_STEP + 1, VAD_STEP):
        total += 1
        if VAD.is_speech(mono_int16[i:i + VAD_STEP].tobytes(), SR):
            votes += 1
    return total > 0 and votes * 2 > total


FOLLOWUP_WINDOW = 6.0  # seconds after Jarvis finishes speaking where he keeps listening
followup_until = 0.0


def audio_loop():
    global followup_until
    from openwakeword.model import Model
    oww = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    from faster_whisper import WhisperModel
    whisper = WhisperModel("small", device="cpu", compute_type="int8")
    print("(ears ready - say 'Hey Jarvis', clap twice, or click the orb)")

    clap_t = 0.0
    level = 0.0
    with sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME, latency="high") as stream:
        while True:
            frame, _ = stream.read(FRAME)
            mono = frame[:, 0]

            # orb click / other triggers
            try:
                WAKE_QUEUE.get_nowait()
                handle_interaction(stream, whisper, oww)
                continue
            except queue.Empty:
                pass

            # follow-up: right after Jarvis answers, no wake word needed for a quick reply
            if STATE["mode"] == "idle" and time.time() < followup_until and _is_speech(mono):
                handle_interaction(stream, whisper, oww, lead=mono)
                continue

            # claps: two sharp NON-SPEECH transients 0.1-0.8 s apart. Plain
            # loudness pairs false-fired constantly on animated conversation
            # (plosives like P/T in an interview read as "claps" and Jarvis
            # butted in uninvited). Real claps are impulses: almost all their
            # energy in one instant, so the peak-to-RMS ratio (crest factor)
            # is far higher than speech - require that, plus a higher floor.
            peak = np.abs(mono).max() / 32768.0
            rms = float(np.sqrt(np.mean((mono.astype(np.float32) / 32768.0) ** 2))) or 1e-9
            crest = peak / rms
            level = level * .97 + peak * .03
            if (peak > max(.5, level * 6) and crest > 4.5
                    and not _is_speech(mono) and STATE["mode"] == "idle"):
                now = time.time()
                if .1 < now - clap_t < .8:
                    clap_t = 0
                    handle_interaction(stream, whisper, oww)
                    continue
                clap_t = now

            # wake word - 0.4 was loosened while a (since-fixed) audio-thread
            # freeze was eating detections; with that gone it just made other
            # people's speech wake him. Back to a strict threshold.
            score = oww.predict(mono)["hey_jarvis"]
            if score > .6:
                oww.reset()
                if STATE["mode"] == "speaking":
                    interrupt_speech()  # barge-in: talk over Jarvis to stop him
                if STATE["mode"] in ("idle", "speaking", "thinking"):
                    handle_interaction(stream, whisper, oww)


def record_until_silence(stream, max_s=14, silence_s=1.1, lead=None):
    """Adaptive silence tail: short utterances (like 'para'/'stop') end the
    recording quickly, while longer speech gets the full silence_s tolerance
    so a normal thinking pause mid-sentence doesn't cut you off. Without
    this, bumping silence_s up to stop premature cutoffs also made 'Jarvis,
    stop' feel sluggish, since the stop-word check only runs after
    recording ends."""
    SHORT_UTTERANCE_S = 1.2  # speech shorter than this gets the fast tail
    FAST_SILENCE_S = 0.35
    chunks = [lead] if lead is not None else []
    quiet, speech_s, started = 0, 0, lead is not None
    for _ in range(int(max_s * SR / FRAME)):
        frame, _ = stream.read(FRAME)
        mono = frame[:, 0]
        chunks.append(mono)
        if _is_speech(mono):
            started, quiet = True, 0
            speech_s += FRAME / SR
        elif started:
            quiet += FRAME / SR
            threshold = FAST_SILENCE_S if speech_s < SHORT_UTTERANCE_S else silence_s
            if quiet >= threshold:
                break
    audio = np.concatenate(chunks).astype(np.float32) / 32768.0
    peak = np.abs(audio).max()
    if peak > 1e-4:  # normalize level - helps whisper on quiet/echoey mics
        audio = audio / peak * .9
    return audio


def handle_interaction(stream, whisper, oww, lead=None):
    """Records the utterance on the main audio thread (it owns the mic
    stream), then hands transcription + thinking + speaking off to a worker
    thread so wake-word/clap detection keeps running in real time instead of
    freezing for the several seconds an LLM round trip takes."""
    global followup_until
    followup_until = 0.0
    generation = _new_interaction_generation()
    if lead is None:
        _ding()
    set_state("listening")
    audio = record_until_silence(stream, lead=lead)
    oww.reset()
    threading.Thread(target=process_utterance, args=(whisper, audio, generation), daemon=True).start()


def process_utterance(whisper, audio, generation):
    global followup_until
    set_state("thinking")
    # auto-detect (pt/en/fr etc.) instead of a fixed language, so switching
    # tongues mid-conversation transcribes correctly, not just replies correctly
    segs, _info = whisper.transcribe(audio, language=None, beam_size=2, vad_filter=True)
    text = " ".join(s.text for s in segs).strip()
    if not text:
        set_state("idle")
        return
    print(f"🎙 {text}")

    # Stop command: checked first and returns instantly with no reply at all -
    # audio playback was already cut the moment the wake word was heard (the
    # barge-in in audio_loop), so this just has to swallow the "stop" itself
    # instead of answering it like a normal question.
    if STOP_TRIGGERS.search(text):
        interrupt_speech()
        set_state("idle")
        return

    if not _interaction_is_current(generation):
        return

    switch_paid = re.compile(r"\b(mudar|trocar|use|usar|ative|ativar|coloque|colocar)\s+(para\s+o\s+)?(modelo\s+)?(pago|claude|paid)\b", re.I)
    switch_free = re.compile(r"\b(mudar|trocar|use|usar|ative|ativar|coloque|colocar)\s+(para\s+o\s+)?(modelo\s+)?(gratis|grátis|gratuito|free|nvidia)\b", re.I)
    switch_local = re.compile(r"\b(mudar|trocar|use|usar|ative|ativar|coloque|colocar)\s+(para\s+o\s+)?(modelo\s+)?(local|llama|deepseek|evo)\b", re.I)
    close_home = re.compile(r"\b(fechar\s+(a\s+)?home|minimizar\s+(a\s+)?home|fechar\s+tela|minimizar\s+tela|fechar|minimizar|close\s+home|minimize\s+home)\b", re.I)
    
    if switch_paid.search(text):
        CFG["provider"] = "anthropic"
        try:
            on_disk = json.loads(CONFIG_PATH.read_text())
            on_disk["provider"] = "anthropic"
            CONFIG_PATH.write_text(json.dumps(on_disk, indent=2, ensure_ascii=False))
        except Exception:
            pass
        speak("Modelo pago Claude ativado, senhora. [LANG:pt]")
        followup_until = time.time() + FOLLOWUP_WINDOW
        return

    if switch_free.search(text):
        CFG["provider"] = "nvidia"
        try:
            on_disk = json.loads(CONFIG_PATH.read_text())
            on_disk["provider"] = "nvidia"
            CONFIG_PATH.write_text(json.dumps(on_disk, indent=2, ensure_ascii=False))
        except Exception:
            pass
        speak("Modelo gratuito ativado, senhora. [LANG:pt]")
        followup_until = time.time() + FOLLOWUP_WINDOW
        return

    if switch_local.search(text):
        CFG["provider"] = "local"
        try:
            on_disk = json.loads(CONFIG_PATH.read_text())
            on_disk["provider"] = "local"
            CONFIG_PATH.write_text(json.dumps(on_disk, indent=2, ensure_ascii=False))
        except Exception:
            pass
        speak("Cérebro local ativado, senhora. [LANG:pt]")
        followup_until = time.time() + FOLLOWUP_WINDOW
        return

    if close_home.search(text):
        HOME_MODE["active"] = False
        STUDY_MODE["active"] = False
        speak("Fechando a tela, senhora. [LANG:pt]")
        followup_until = time.time() + FOLLOWUP_WINDOW
        return

    m = STUDY_OPEN_TRIGGERS.search(text)
    if m:
        track_id = _study_track_from_text(text)
        if track_id:
            HOME_MODE["active"] = False
            STUDY_MODE["track"] = track_id
            STUDY_MODE["active"] = True
            name = study_mod.TRACKS[track_id]["name"]
            speak(f"Abrindo a sessão de estudo de {name}. Bons estudos, senhora. [LANG:pt]")
        else:
            speak("De qual trilha, senhora? Inteligência artificial ou francês? [LANG:pt]")
        followup_until = time.time() + FOLLOWUP_WINDOW
        return

    if STUDY_TODAY_TRIGGERS.search(text):
        speak(_study_today_text() + " [LANG:pt]")
        followup_until = time.time() + FOLLOWUP_WINDOW
        return

    if STUDY_COMPLETE_TRIGGERS.search(text):
        track_id = _study_track_from_text(text)
        if track_id:
            n = finish_study_session(track_id)
            name = study_mod.TRACKS[track_id]["name"]
            if n:
                speak(f"Sessão {n} de {name} concluída e registrada, senhora. Excelente trabalho. [LANG:pt]")
            else:
                speak(f"A trilha de {name} já está toda concluída, senhora. [LANG:pt]")
        else:
            speak("Concluir a sessão de qual trilha, senhora? IA ou francês? [LANG:pt]")
        followup_until = time.time() + FOLLOWUP_WINDOW
        return

    if BRIEFING_TRIGGERS.search(text):
        open_home_screen()
        threading.Thread(target=run_daily_briefing, daemon=True).start()
        followup_until = time.time() + FOLLOWUP_WINDOW
        return
    set_state("thinking", text)
    try:
        answer = think(text)
    except Exception as e:  # noqa: BLE001
        answer = f"Brain hiccup, {CFG['user_title']}: {e}"
    if not _interaction_is_current(generation):
        set_state("idle")
        return
    print(f"🎩 {answer}")
    speak(answer)
    followup_until = time.time() + FOLLOWUP_WINDOW


def _ding():
    t = np.linspace(0, .12, int(SR * .12), False)
    tone = (np.sin(2 * np.pi * 880 * t) * np.exp(-t * 18) * .3).astype(np.float32)
    try:
        sd.play(tone, SR)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- lifecycle
PID_FILE = JARVIS_HOME / "jarvis.pid"


def pid_alive(pid):
    try:
        if platform.system() == "Windows":
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                               capture_output=True, text=True, timeout=5)
            return str(pid) in r.stdout
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def quit_jarvis():
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    os._exit(0)


# ---------------------------------------------------------------- study mode
import study as study_mod

STUDY_MODE = {"active": False, "track": None}
STUDY_TODO_LIST = "Estudos"

STUDY_OPEN_TRIGGERS = re.compile(
    r"\b(abr[ae]|abrir|inicia[r]?|come[cç]a[r]?)\b.{0,30}\b(interface|tela|modo|sess[aã]o)\s+de\s+estudo", re.I)
STUDY_TODAY_TRIGGERS = re.compile(
    r"\b(o\s*que\s+(eu\s+)?estudo\s+hoje|estudo\s+de\s+hoje|sess[oõ]es?\s+de\s+hoje|"
    r"what\s+do\s+i\s+study\s+today)\b", re.I)
STUDY_COMPLETE_TRIGGERS = re.compile(
    r"\b(conclu[ií][r]?|finaliza[r]?|termine[i]?|terminar|acabei)\b.{0,25}\bsess[aã]o\b", re.I)
_TRACK_HINTS = re.compile(r"\b(franc[eê]s|french)\b", re.I), re.compile(r"\b(ia|a\.?i\.?|intelig[eê]ncia)\b", re.I)


def _study_track_from_text(text):
    fr, ai = _TRACK_HINTS
    if fr.search(text):
        return "frances"
    if ai.search(text):
        return "ai"
    return None


def _study_today_text():
    parts = []
    for item in study_mod.study_summary():
        if item["done"]:
            parts.append(f"A trilha de {item['name']} está concluída")
        else:
            title = re.sub(r"^[^A-Za-zÀ-ÿ]*Sess[aã]o\s*\d+\s*[—:-]\s*", "", item["title"] or "")
            parts.append(f"{item['name']}: sessão {item['session']} de {item['total']}, {title}")
    return "Hoje, " + ". ".join(parts) + "."


def _study_task_title(track_id, n):
    prefix = study_mod.TRACKS[track_id]["todo_prefix"]
    title = study_mod.session_title(track_id, n) or f"Sessão {n}"
    return f"{prefix} — Sessão {n}: {title}"


def ensure_study_todo_tasks():
    """Once a day: each track's session-of-the-day gets a task in the
    'Estudos' To Do list (due today) if one doesn't already exist."""
    try:
        token, err = _outlook_token()
        if err:
            return
        list_info = _outlook_task_list(token, create=True, name=STUDY_TODO_LIST)
        if not list_info:
            return
        import requests
        r = requests.get(
            f"https://graph.microsoft.com/v1.0/me/todo/lists/{list_info['id']}/tasks",
            headers={"Authorization": f"Bearer {token}"}, params={"$top": 100}, timeout=15)
        r.raise_for_status()
        existing = {t.get("title", ""): t for t in r.json().get("value", [])
                    if t.get("status") != "completed"}
        today = datetime.now().strftime("%Y-%m-%d")
        for track_id in study_mod.TRACKS:
            n = study_mod.current_session(track_id)
            if n is None:
                continue
            title = _study_task_title(track_id, n)
            if title in existing:
                continue
            prefix = study_mod.TRACKS[track_id]["todo_prefix"]
            already_has_track_task = any(t.startswith(f"{prefix} — Sessão") for t in existing)
            if already_has_track_task:
                continue  # an older session task is still open - don't stack a second one
            requests.post(
                f"https://graph.microsoft.com/v1.0/me/todo/lists/{list_info['id']}/tasks",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"title": title, "status": "notStarted",
                      "dueDateTime": {"dateTime": f"{today}T00:00:00", "timeZone": OUTLOOK_TIMEZONE}},
                timeout=15)
            print(f"[Study] To Do task created: {title}")
    except Exception as e:  # noqa: BLE001
        print("[Study] To Do task creation failed:", e)


def complete_study_todo_task(track_id, n):
    """Marks the matching 'Estudos' task completed, matching by the stable
    'Prefix — Sessão N' start rather than the full title."""
    try:
        token, err = _outlook_token()
        if err:
            return False
        list_info = _outlook_task_list(token, create=False, name=STUDY_TODO_LIST)
        if not list_info:
            return False
        import requests
        r = requests.get(
            f"https://graph.microsoft.com/v1.0/me/todo/lists/{list_info['id']}/tasks",
            headers={"Authorization": f"Bearer {token}"}, params={"$top": 100}, timeout=15)
        r.raise_for_status()
        prefix = f"{study_mod.TRACKS[track_id]['todo_prefix']} — Sessão {n}"
        for t in r.json().get("value", []):
            if t.get("title", "").startswith(prefix) and t.get("status") != "completed":
                requests.patch(
                    f"https://graph.microsoft.com/v1.0/me/todo/lists/{list_info['id']}/tasks/{t['id']}",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"status": "completed"}, timeout=15)
                print(f"[Study] To Do task completed: {t['title']}")
                return True
    except Exception as e:  # noqa: BLE001
        print("[Study] To Do task completion failed:", e)
    return False


def finish_study_session(track_id, minutes=0):
    n = study_mod.complete_session(track_id, minutes)
    if n is not None:
        threading.Thread(target=complete_study_todo_task, args=(track_id, n), daemon=True).start()
    return n


# ---------------------------------------------------------------- orb
ORB_HTML = (APP_DIR / "orb.html").read_text(encoding="utf-8")
HOME_HTML = (APP_DIR / "home.html").read_text(encoding="utf-8")
STUDY_HTML = (APP_DIR / "study.html").read_text(encoding="utf-8")
ORB_SIZE = 170
MARGIN = 24


class OrbApi:
    def get_state(self):
        return STATE

    def wake(self):
        if STATE["mode"] == "speaking":
            interrupt_speech()
        elif STATE["mode"] == "idle":
            WAKE_QUEUE.put(1)
        return "ok"

    def quit(self):
        quit_jarvis()

    def get_provider(self):
        key_file = Path(CFG.get("local_api_key_file") or DEFAULT_LOCAL_KEY_FILE).expanduser()
        return {"provider": CFG.get("provider", "local"),
                "nvidia_ready": bool(CFG.get("nvidia_api_key")),
                "local_ready": key_file.is_file()}

    def set_provider(self, provider):
        if provider not in ("anthropic", "nvidia", "local"):
            return "invalid"
        if provider == "nvidia" and not CFG.get("nvidia_api_key"):
            return "no_nvidia_key"
        if provider == "local":
            key_file = Path(CFG.get("local_api_key_file") or DEFAULT_LOCAL_KEY_FILE).expanduser()
            if not key_file.is_file():
                return "no_local_key"
        CFG["provider"] = provider
        try:
            on_disk = json.loads(CONFIG_PATH.read_text())
            on_disk["provider"] = provider
            CONFIG_PATH.write_text(json.dumps(on_disk, indent=2, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass
        return "ok"

    def get_home_data(self):
        now = datetime.now()
        hour = now.hour
        greet_word = ("Bom dia" if CFG["language"] == "pt" else "Good morning") if hour < 12 else \
                     ("Boa tarde" if CFG["language"] == "pt" else "Good afternoon") if hour < 18 else \
                     ("Boa noite" if CFG["language"] == "pt" else "Good evening")
        weekday_pt = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
                      "Sexta-feira", "Sábado", "Domingo"][now.weekday()]
        month_pt = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
                    "agosto", "setembro", "outubro", "novembro", "dezembro"][now.month - 1]
        return {
            "time": now.strftime("%H:%M"),
            "date": f"{weekday_pt}, {now.day} de {month_pt}" if CFG["language"] == "pt"
                    else now.strftime("%A, %B %-d"),
            "greeting": f"{greet_word}, {CFG.get('user_name') or CFG['user_title']}.",
            "agenda": CACHED_HOME_DATA["agenda"],
            "weather": CACHED_HOME_DATA["weather"],
            "birthdays": CACHED_HOME_DATA["birthdays"],
            "outreach": CACHED_HOME_DATA["outreach"],
            "tasks": get_task_summary(),
            "study": CACHED_HOME_DATA.get("study", []),
            "topic": HOME_MODE["topic"],
            "state": STATE,
        }

    def show_briefing(self):
        if HOME_MODE["active"]:
            return "already_active"
        open_home_screen()
        threading.Thread(target=run_daily_briefing, daemon=True).start()
        return "ok"

    def close_home(self):
        interrupt_speech()  # the X button must silence him too, not just hide the screen
        HOME_MODE["active"] = False
        set_state("idle")
        return "ok"

    # ---- study screen bridge ----
    def open_study(self, track_id):
        if track_id not in study_mod.TRACKS:
            return "unknown_track"
        HOME_MODE["active"] = False
        STUDY_MODE["track"] = track_id
        STUDY_MODE["active"] = True
        return "ok"

    def get_study_data(self):
        track_id = STUDY_MODE.get("track")
        if not track_id:
            return {}
        data = study_mod.render_session_html(track_id)
        data["total"] = study_mod.TRACKS[track_id]["total"]
        progress = study_mod._load_progress().get(track_id, {})
        data["total_minutes"] = progress.get("total_minutes", 0)
        return data

    def log_study_minutes(self, track_id, minutes):
        study_mod.log_minutes(track_id, minutes)
        return "ok"

    def complete_study_session(self, track_id):
        n = finish_study_session(track_id)
        return f"completed_{n}" if n else "already_done"

    def close_study(self):
        STUDY_MODE["active"] = False
        STUDY_MODE["track"] = None
        return "ok"

    def open_url(self, url):
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            opener = "open" if platform.system() == "Darwin" else "start"
            subprocess.Popen([opener, url] if opener == "open" else ["cmd", "/c", "start", "", url])
        return "ok"


def _add_mac_events(raw, items, seen):
    for line in raw.splitlines():
        if " -- " not in line:
            continue
        summary_part, when = line.split(" -- ", 1)
        summary = summary_part.split(": ", 1)[1] if ": " in summary_part else summary_part
        summary = summary.strip()
        if any(kw in summary.lower() for kw in ["faz ", "niver", "nasc", "aniv", "birth"]):
            continue  # birthdays get their own panel, not the regular agenda
        m = re.search(r"(\d{1,2}:\d{2})", when)
        t = m.group(1) if m else ""
        if (t, summary.lower()) not in seen:
            items.append({"time": t, "title": summary})
            seen.add((t, summary.lower()))


def _add_iso_events(raw, items, seen):
    """Google and Outlook both return 'Title -- ISO8601 datetime' lines."""
    for line in raw.splitlines():
        if " -- " not in line:
            continue
        title, when = line.split(" -- ", 1)
        title = title.strip()
        m = re.search(r"T(\d{2}:\d{2})", when) or re.search(r"(\d{1,2}:\d{2})", when)
        t = m.group(1) if m else ""
        if (t, title.lower()) not in seen:
            items.append({"time": t, "title": title})
            seen.add((t, title.lower()))


def _parse_agenda():
    """Merges today's events from every linked calendar source. Each source
    is independent - one having nothing (or being unlinked/blocked) must
    never stop the others from being checked, which is exactly the bug that
    made a real meeting invisible when the Mac Calendar simply had no events
    of its own today."""
    items, seen = [], set()

    try:
        raw = tool_read_calendar({"days_ahead": 1})
        if not raw.startswith(("BLOCKED", "(")):
            _add_mac_events(raw, items, seen)
    except Exception as e:  # noqa: BLE001
        print("[agenda] Mac Calendar failed:", e)

    try:
        graw = tool_read_google_calendar({"days_ahead": 1})
        if not graw.startswith(("BLOCKED", "(")):
            _add_iso_events(graw, items, seen)
    except Exception as e:  # noqa: BLE001
        print("[agenda] Google Calendar failed:", e)

    try:
        oraw = tool_read_outlook_calendar({"days_ahead": 1})
        if not oraw.startswith(("BLOCKED", "(")):
            _add_iso_events(oraw, items, seen)
    except Exception as e:  # noqa: BLE001
        print("[agenda] Outlook Calendar failed:", e)

    return sorted(items, key=lambda e: e["time"])[:6]


WMO_DESC_PT = {
    0: "céu limpo", 1: "poucas nuvens", 2: "parcialmente nublado", 3: "nublado",
    45: "névoa", 48: "névoa com geada", 51: "garoa fraca", 53: "garoa", 55: "garoa forte",
    61: "chuva fraca", 63: "chuva", 65: "chuva forte", 71: "neve fraca", 73: "neve",
    75: "neve forte", 80: "pancadas de chuva", 81: "pancadas de chuva fortes",
    95: "trovoadas", 96: "trovoadas com granizo",
}
WMO_DESC_EN = {
    0: "clear skies", 1: "mostly clear", 2: "partly cloudy", 3: "cloudy",
    45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 80: "rain showers", 81: "heavy rain showers",
    95: "thunderstorms", 96: "thunderstorms with hail",
}
_weather_cache = {"data": None, "at": 0}


def fetch_weather():
    city = CFG.get("weather_city")
    if not city:
        return None
    if _weather_cache["data"] is not None and time.time() - _weather_cache["at"] < 600:
        return _weather_cache["data"]
    try:
        import requests
        geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                           params={"name": city, "count": 1}, timeout=8).json()
        results = geo.get("results")
        if not results:
            return None
        lat, lon = results[0]["latitude"], results[0]["longitude"]
        wx = requests.get("https://api.open-meteo.com/v1/forecast",
                          params={"latitude": lat, "longitude": lon,
                                  "current": "temperature_2m,weather_code",
                                  "timezone": "auto"}, timeout=8).json()
        cur = wx.get("current", {})
        code = cur.get("weather_code")
        table = WMO_DESC_PT if CFG["language"] == "pt" else WMO_DESC_EN
        result = {"temp": round(cur.get("temperature_2m", 0)), "desc": table.get(code, "-"),
                  "city": results[0].get("name", city)}
        _weather_cache["data"], _weather_cache["at"] = result, time.time()
        return result
    except Exception:  # noqa: BLE001
        return _weather_cache["data"]


# ---------------------------------------------------------------- background cache

CACHED_HOME_DATA = {
    "agenda": [],
    "weather": None,
    "birthdays": [],
    "outreach": {
        "felipe_sent": 0,
        "thayna_sent": 0,
        "positives": 0,
        "negatives": 0,
        "followups": 0
    },
    "last_refreshed": 0
}


def fetch_yesterday_outreach_stats():
    """Real numbers only - no guessing.

    The message log (gid=msg_gid) has no 'who sent it' column at all, so the
    old code was silently guessing the sender from greeting words in the
    message text ('Hi '/'Olá ' etc.) - on the actual message templates that
    never matched, which is why it reported ~3-4 sent when 17 real messages
    went out yesterday (13 'enviado' + 4 'follow-up'; 6 more failed and
    needed a manual resend, which wasn't being surfaced at all).

    The leads sheet DOES reliably track who sent the first message per lead
    ('Gestão' contains '✅ Enviado por Thay' / '✅ Enviado por Felipe'), so
    that's the real source for the per-person split.

    Replies are the other real bug: 'positives' was counting leads whose
    Gestão is 'Em conversa' but only among leads *created* yesterday - a
    lead who replied to a follow-up sent yesterday, after being added
    weeks ago, was invisible. There's no per-reply timestamp in this sheet,
    so the honest fix is to report the live total of active conversations
    right now, not a yesterday-dated snapshot that doesn't correspond to
    when someone actually replied.
    """
    import csv
    import requests
    sheet_id = "1eC2im7e5U3IvJmBm783t0X-xAXi8RSmqowY-41sfDmM"
    leads_gid = "1547340779"
    msg_gid = "325599469"

    yesterday = datetime.now() - timedelta(days=1)
    target_dates = {yesterday.strftime("%d/%m/%Y"), yesterday.strftime("%Y-%m-%d"),
                    f"{yesterday.day}/{yesterday.month}/{yesterday.year}"}

    messages_sent = 0
    messages_failed = 0
    followups = 0
    felipe_sent = 0
    thayna_sent = 0
    positives = 0
    negatives = 0

    try:
        r_msg = requests.get(f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={msg_gid}", timeout=8)
        if r_msg.status_code == 200:
            reader = csv.reader(r_msg.text.splitlines())
            headers = next(reader, [])
            h = {name.strip().lower(): i for i, name in enumerate(headers)}
            date_i, status_i = h.get("data", 5), h.get("status_envio", 3)
            for row in reader:
                if len(row) <= date_i or not row[date_i]:
                    continue
                if row[date_i].split()[0] not in target_dates:
                    continue
                status = row[status_i].lower() if len(row) > status_i else ""
                if "follow-up" in status or "followup" in status:
                    followups += 1
                    messages_sent += 1
                elif "enviado" in status or "sucesso" in status:
                    messages_sent += 1
                elif "falha" in status or "erro" in status:
                    messages_failed += 1

        r_leads = requests.get(f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={leads_gid}", timeout=8)
        if r_leads.status_code == 200:
            reader = csv.reader(r_leads.text.splitlines())
            headers = next(reader, [])
            h = {name.strip().lower(): i for i, name in enumerate(headers)}
            date_i, gestao_i = h.get("data", 1), h.get("gestão", 13)
            for row in reader:
                gestao = row[gestao_i].strip().lower() if len(row) > gestao_i else ""
                if not gestao:
                    continue
                # who-sent-the-first-message split: only meaningful scoped to
                # leads actually created yesterday (it's a per-lead fact)
                if len(row) > date_i and row[date_i].strip() in target_dates:
                    if "felipe" in gestao:
                        felipe_sent += 1
                    elif "thay" in gestao:
                        thayna_sent += 1
                # live pipeline state: NOT date-filtered, so a reply that
                # came in today to a lead from last week still counts
                if "conversa" in gestao or "call marcada" in gestao:
                    positives += 1
                elif "cancelado" in gestao or "reprovado" in gestao or "nurture" in gestao:
                    negatives += 1
    except Exception as e:
        print("[Cache] Outreach stats refresh failed:", e)

    return {
        "felipe_sent": felipe_sent,
        "thayna_sent": thayna_sent,
        "messages_sent": messages_sent,
        "messages_failed": messages_failed,
        "positives": positives,
        "negatives": negatives,
        "followups": followups,
    }


def fetch_birthdays_of_the_week():
    birthdays = []
    try:
        raw = tool_read_calendar({"days_ahead": 7})
        if raw and not raw.startswith(("BLOCKED", "(")):
            for line in raw.splitlines():
                if " -- " not in line:
                    continue
                parts = line.split(" -- ", 1)
                summary_part = parts[0]
                when_part = parts[1]
                
                if ": " in summary_part:
                    cal_name, summary = summary_part.split(": ", 1)
                else:
                    summary = summary_part
                    
                summary = summary.strip()
                if any(kw in summary.lower() for kw in ["faz ", "niver", "nasc", "aniv", "birth"]):
                    name = summary.replace("Aniversário de", "").replace("Aniversário", "").replace("'s Birthday", "").replace("Birthday", "").strip()
                    clean_name = re.sub(r"\s+faz\s+\d+\s+anos.*", "", name, flags=re.I)
                    clean_name = re.sub(r"niver\s+", "", clean_name, flags=re.I)
                    
                    date_match = re.search(r"(\d{1,2}\s+de\s+[a-zA-Zç]+)", when_part, re.I)
                    bdate = date_match.group(1) if date_match else "Esta semana"
                    birthdays.append({"name": clean_name, "date": bdate})
    except Exception as e:
        print("Local birthday extraction failed:", e)
        
    if GOOGLE_TOKEN_PATH.exists():
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            creds = Credentials.from_authorized_user_info(
                json.loads(GOOGLE_TOKEN_PATH.read_text()), GOOGLE_SCOPES)
            if not creds.valid and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                GOOGLE_TOKEN_PATH.write_text(creds.to_json())
            service = build("calendar", "v3", credentials=creds)
            now = datetime.now()
            time_min = now.replace(hour=0, minute=0, second=0).isoformat() + "Z"
            time_max = (now.replace(hour=0, minute=0, second=0) + timedelta(days=7)).isoformat() + "Z"
            events = service.events().list(
                calendarId="primary", timeMin=time_min, timeMax=time_max,
                singleEvents=True, orderBy="startTime").execute().get("items", [])
            for e in events:
                summary = e.get('summary', '')
                if any(kw in summary.lower() for kw in ["aniversário", "birthday", "niver", "nascimento", "bday", "faz "]):
                    start = e['start'].get('dateTime', e['start'].get('date'))
                    name = summary.replace("Aniversário de", "").replace("Aniversário", "").replace("'s Birthday", "").replace("Birthday", "").strip()
                    clean_name = re.sub(r"\s+faz\s+\d+\s+anos.*", "", name, flags=re.I)
                    clean_name = re.sub(r"niver\s+", "", clean_name, flags=re.I)
                    bdate = "Esta semana"
                    try:
                        dt = datetime.strptime(start.split('T')[0], "%Y-%m-%d")
                        month_pt = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
                                    "agosto", "setembro", "outubro", "novembro", "dezembro"][dt.month - 1]
                        bdate = f"{dt.day} de {month_pt}"
                    except Exception:
                        pass
                    birthdays.append({"name": clean_name, "date": bdate})
        except Exception:
            pass
            
    seen = set()
    unique_birthdays = []
    for b in birthdays:
        if b["name"] not in seen:
            seen.add(b["name"])
            unique_birthdays.append(b)
    return unique_birthdays


def home_data_refresher_loop():
    global CACHED_HOME_DATA
    while True:
        try:
            print("[CacheRefresher] Refreshing background home data...")
            weather = fetch_weather()
            agenda = _parse_agenda()
            outreach = fetch_yesterday_outreach_stats()
            birthdays = fetch_birthdays_of_the_week()
            
            CACHED_HOME_DATA["weather"] = weather
            CACHED_HOME_DATA["agenda"] = agenda
            CACHED_HOME_DATA["outreach"] = outreach
            CACHED_HOME_DATA["birthdays"] = birthdays
            CACHED_HOME_DATA["study"] = study_mod.study_summary()
            CACHED_HOME_DATA["last_refreshed"] = time.time()
            print("[CacheRefresher] Refresh completed successfully.")

            # once per day, mirror the sessions-of-the-day into the To Do list
            today = datetime.now().strftime("%Y-%m-%d")
            marker = JARVIS_HOME / "last_study_todo_date.txt"
            try:
                already = marker.read_text().strip() == today
            except FileNotFoundError:
                already = False
            if not already:
                ensure_study_todo_tasks()
                marker.write_text(today)
        except Exception as e:
            print("[CacheRefresher] Error in refresh loop:", e)
        time.sleep(120)


def _default_home(win):
    screen = webview.screens[0] if webview.screens else None
    sw, sh = (screen.width, screen.height) if screen else (1440, 900)
    return sw - ORB_SIZE - MARGIN, sh - ORB_SIZE - MARGIN


def configure_window_for_all_spaces(win):
    """Make the orb/home follow the user across every macOS Space (Desktop
    1, 2, 3...) instead of only being visible on whichever Space it was
    created on - pywebview's Window object has no public '.native' handle,
    the real NSWindow lives in the cocoa backend's own BrowserView registry,
    keyed by the window's uid.

    AppKit objects are not thread-safe: mutating the NSWindow from this
    background thread (orb_position_loop) either silently no-ops or crashes
    the process outright (verified - SIGABRT) depending on timing, the same
    class of bug as the earlier toggle_fullscreen() freeze. The fix is the
    same: hop onto Cocoa's main run loop via PyObjCTools.AppHelper.callAfter
    instead of touching the NSWindow directly from here."""
    if platform.system() != "Darwin":
        return

    def _apply():
        try:
            import AppKit
            from webview.platforms.cocoa import BrowserView
            instance = BrowserView.instances.get(win.uid)
            native = getattr(instance, "window", None)
            if native is None:
                print("[Window] Could not find the native NSWindow for uid", win.uid)
                return
            can_join = getattr(AppKit, "NSWindowCollectionBehaviorCanJoinAllSpaces", 1 << 0)
            fullscreen_aux = getattr(AppKit, "NSWindowCollectionBehaviorFullScreenAuxiliary", 1 << 8)
            native.setCollectionBehavior_(can_join | fullscreen_aux)
            native.setHidesOnDeactivate_(False)
            native.setLevel_(getattr(AppKit, "NSFloatingWindowLevel", 3))
            print("[Window] Jarvis configured for all macOS Spaces.")
        except Exception as e:  # noqa: BLE001
            print("[Window] Could not configure all-Spaces behavior:", e)

    try:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(_apply)
    except Exception as e:  # noqa: BLE001
        print("[Window] Could not schedule all-Spaces behavior:", e)


HOME_MODE = {"active": False, "topic": None}
BRIEFING_RUNNING = False
BRIEFING_TRIGGERS = re.compile(
    r"\b(abr[ae]\s+(a\s+)?(sua\s+)?home|resumo\s+do\s+dia|vis[aã]o\s+geral|"
    r"atualiza[cç][oõ]es\s+do\s+dia|panorama\s+do\s+dia|"
    r"(daily\s+)?(overview|briefing)|open\s+(your\s+)?home)\b", re.I)
STOP_TRIGGERS = re.compile(
    r"^\s*(?:(?:hey|ei)\s+)?(?:jarvis[\s,;:.-]*)?(?:por\s+favor[\s,;:.-]*)?"
    r"(para|pare|parar|cal[ae]|cala\s*a?\s*boca|chega|sil[eê]n[cç]io|"
    r"stop|shut\s*up|quiet|be\s+quiet|enough)\b.*$", re.I)


def open_home_screen():
    """Request the home window immediately; the spoken briefing can follow in a thread."""
    HOME_MODE["active"] = True
    HOME_MODE["topic"] = None


def run_daily_briefing():
    """A scripted, deterministic morning-briefing sequence (not left to the
    LLM to improvise) - real name, real time, real weather, real agenda -
    while the fullscreen HUD highlights whichever panel is being narrated."""
    global BRIEFING_RUNNING
    if BRIEFING_RUNNING:
        return
    BRIEFING_RUNNING = True
    HOME_MODE["active"] = True
    HOME_MODE["topic"] = None
    set_state("speaking")
    try:
        name = CFG.get("user_name") or CFG["user_title"]
        now = datetime.now()
        hour = now.hour
        pt = CFG["language"] == "pt"
        greet = ("Bom dia" if hour < 12 else "Boa tarde" if hour < 18 else "Boa noite") if pt \
            else ("Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening")

        greeting_text = f"{greet}, {name}. " + (f"São {now.strftime('%H:%M')} agora." if pt
                        else f"It's {now.strftime('%H:%M')} right now.")

        weather = CACHED_HOME_DATA["weather"]
        weather_text = None
        if weather:
            weather_text = (f"Estão {weather['temp']} graus em {weather['city']}, {weather['desc']}." if pt
                            else f"It's {weather['temp']} degrees in {weather['city']}, {weather['desc']}.")

        agenda = CACHED_HOME_DATA["agenda"]
        if agenda:
            preview = "; ".join(f"{a['title']} às {a['time']}" if pt else f"{a['title']} at {a['time']}"
                                for a in agenda[:3] if a["time"])
            n = len(agenda)
            agenda_text = (f"Você tem {n} compromisso{'s' if n != 1 else ''} hoje. {preview}." if pt
                          else f"You have {n} item{'s' if n != 1 else ''} on your calendar today. {preview}.")
        else:
            agenda_text = "Nada agendado para hoje — dia livre." if pt else "Nothing on the calendar today - a clear day."

        # Outreach narration
        outreach = CACHED_HOME_DATA["outreach"]
        outreach_text = None
        if outreach:
            sent = outreach.get("messages_sent", 0)
            failed = outreach.get("messages_failed", 0)
            if sent > 0 or failed > 0:
                outreach_text = (f"Ontem na automação de sites, enviamos {sent} mensagens." if pt
                                 else f"Yesterday in site automation, we sent {sent} messages.")
                if failed:
                    outreach_text += (f" {failed} falharam e precisam ser reenviadas manualmente." if pt
                                      else f" {failed} failed and need a manual resend.")
                outreach_text += (f" Ao todo temos {outreach['positives']} conversas ativas agora." if pt
                                  else f" We currently have {outreach['positives']} active conversations.")
            else:
                outreach_text = ("Nenhuma mensagem de automação ontem." if pt else "No automation messages yesterday.")

        close_text = "Esse é o resumo do seu dia. Diga se precisar de mais alguma coisa." if pt \
            else "That's your day in a nutshell. Say the word if you need anything else."

        import asyncio
        import edge_tts
        
        # Local speak segment helper to prevent idle state flicker
        def speak_segment(text, topic):
            if not text:
                return
            HOME_MODE["topic"] = topic
            set_state("speaking", text)
            
            clean = re.sub(r"[*_#`\[\]]", "", text)
            path = JARVIS_HOME / "reply.mp3"
            voice = {"en": CFG.get("voice_en"), "fr": CFG.get("voice_fr")}.get(_last_lang) or CFG["voice"]
            
            async def gen():
                await edge_tts.Communicate(clean, voice, rate="+8%").save(str(path))
            try:
                asyncio.run(gen())
                data, sr = _decode_audio(path)
                with _play_lock:
                    sd.play(data, sr, latency="high")
                sd.wait()
            except Exception as e:
                print("Briefing TTS segment failed:", e)

        speak_segment(greeting_text, "greeting")
        speak_segment(weather_text, "weather")
        speak_segment(agenda_text, "agenda")
        speak_segment(outreach_text, "outreach")
        speak_segment(close_text, None)

    finally:
        HOME_MODE["topic"] = None
        BRIEFING_RUNNING = False
        set_state("idle")


LAST_BRIEFING_PATH = JARVIS_HOME / "last_briefing_date.txt"


def proactive_briefing_watcher():
    """Greets the user with the daily briefing automatically the first time
    Jarvis is alive on a new day - so mornings don't require asking for it.
    Waits for the background data cache's first refresh so the numbers are
    real, not empty placeholders."""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        if LAST_BRIEFING_PATH.read_text().strip() == today:
            return  # already greeted today
    except FileNotFoundError:
        pass
    while CACHED_HOME_DATA["last_refreshed"] == 0:
        time.sleep(1)
    time.sleep(2)
    run_daily_briefing()
    LAST_BRIEFING_PATH.write_text(today)


def orb_position_loop(win):
    """Rests bottom-right (or wherever the user last dragged it to) as a
    small orb when idle, and glides to screen-center - still a small orb -
    for ordinary questions. The full-screen HUD 'home' screen is separate:
    it only opens when HOME_MODE['active'] is set (daily briefing request or
    a triple-click), takes over fullscreen, then hands control back here."""
    configure_window_for_all_spaces(win)
    home = (CFG["orb_x"], CFG["orb_y"])
    if home[0] is None:
        home = _default_home(win)
    win.move(*home)
    last_known, moving_until, last_mode = home, 0.0, "idle"
    fullscreen_view = None  # None | "home" | "study" - which big screen is loaded

    while True:
        time.sleep(.15)

        # study screen outranks home; both are fullscreen takeovers of the
        # same window, restored to the small orb when neither is active
        want = "study" if STUDY_MODE["active"] else "home" if HOME_MODE["active"] else None
        if want:
            if fullscreen_view != want:
                try:
                    screen = webview.screens[0] if webview.screens else None
                    sw, sh = (screen.width, screen.height) if screen else (1440, 900)
                    win.load_html(STUDY_HTML if want == "study" else HOME_HTML)
                    win.resize(sw, sh)
                    win.move(0, 0)
                except Exception as e:  # noqa: BLE001
                    print(f"{want} screen open failed:", e)
                fullscreen_view = want
            last_mode = STATE["mode"]
            continue
        elif fullscreen_view:
            try:
                win.load_html(ORB_HTML)
                win.resize(ORB_SIZE, ORB_SIZE)
                win.move(*home)
            except Exception as e:  # noqa: BLE001
                print("fullscreen close failed:", e)
            last_known, moving_until = home, time.time() + .6
            fullscreen_view = None
            last_mode = "idle"
            continue

        mode = STATE["mode"]
        now = time.time()

        if mode != "idle" and last_mode == "idle":
            screen = webview.screens[0] if webview.screens else None
            sw, sh = (screen.width, screen.height) if screen else (1440, 900)
            target = (sw // 2 - ORB_SIZE // 2, sh // 2 - ORB_SIZE // 2)
            win.move(*target)
            last_known, moving_until = target, now + .6
        elif mode == "idle" and last_mode != "idle":
            win.move(*home)
            last_known, moving_until = home, now + .6

        elif mode == "idle" and now > moving_until:
            try:
                cur = (win.x, win.y)
            except Exception:  # noqa: BLE001
                cur = last_known
            if cur != last_known:  # user dragged it - this is the new home
                home = cur
                save_orb_position(*home)
                last_known = cur
        last_mode = mode


def main():
    provider = CFG.get("provider", "local")
    if provider != "local" and API_KEY.startswith("PUT-YOUR"):
        print(f"! Set your API key in {CONFIG_PATH} (api_key field) or export ANTHROPIC_API_KEY.")
        print("  Or set provider to \"local\" for the OpenAI-compatible brain on :11434.")
        return
    if provider == "local":
        key_file = Path(CFG.get("local_api_key_file") or DEFAULT_LOCAL_KEY_FILE).expanduser()
        if not key_file.is_file():
            print(f"! Local key file missing: {key_file}")
            return
        print(f"Provider=local → {CFG.get('local_base_url') or 'http://127.0.0.1:11434/v1'}")

    # Atomic lock: O_CREAT|O_EXCL means exactly one process can create the
    # pidfile, even if two launch in the same instant (login autostart +
    # sentinel + manual double-click all racing was how two orbs appeared).
    while True:
        try:
            fd = os.open(PID_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                old_pid = int(PID_FILE.read_text().strip())
            except (ValueError, OSError):
                old_pid = None
            if old_pid and pid_alive(old_pid):
                print(f"Jarvis is already running (pid {old_pid}).")
                print("Double-click Stop-Jarvis to quit it, or hold the orb for ~1s.")
                return
            PID_FILE.unlink(missing_ok=True)  # stale lock from a crash - reclaim

    threading.Thread(target=audio_loop, daemon=True).start()
    threading.Thread(target=home_data_refresher_loop, daemon=True).start()
    threading.Thread(target=proactive_briefing_watcher, daemon=True).start()

    if CFG.get("slack_bot_token") and CFG.get("slack_app_token"):
        import slack_bridge
        threading.Thread(
            target=slack_bridge.start, args=(CFG, think, speak, STATE), daemon=True).start()

    global webview
    import webview
    win = webview.create_window(
        "Jarvis", html=ORB_HTML, js_api=OrbApi(),
        width=ORB_SIZE, height=ORB_SIZE, x=None, y=None,
        frameless=True, on_top=True, transparent=True, resizable=False,
        easy_drag=True)
    try:
        webview.start(orb_position_loop, win)  # blocks until the orb window closes
    finally:
        PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
