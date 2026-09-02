#!/usr/bin/env python3
"""Διακομιστής του Jarvis: σερβίρει το viewer/ και εκθέτει /chat και /remember.

Μόνο τυπική βιβλιοθήκη. Το API key βρίσκεται στο config.json (εκτός του viewer/)
και δεν αποστέλλεται ποτέ στον browser.

provider=local → OpenAI-compatible http://127.0.0.1:11434/v1 (sem Anthropic /
claude -p). Caso contrário: Anthropic API, ou fallback `claude -p` se a key
ainda for o placeholder.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler

BASE = os.path.dirname(os.path.abspath(__file__))
VIEWER = os.path.join(BASE, "viewer")
_cfg = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
NOTES_DIR = _cfg.get("notes_dir") or os.path.join(BASE, "notes")
SKIP_DIRS = {".obsidian", ".smart-env", ".trash", ".git", "node_modules"}
BIND_HOST = os.environ.get("JARVIS_BIND", "127.0.0.1")
PORT = 4700
DEFAULT_LOCAL_KEY_FILE = "/home/thomas-pashoulas/.cursor/deepseek-cursor-api.key"

HISTORY = []  # σύντομο ιστορικό της συνεδρίας (πλευρά διακομιστή)
MAX_HISTORY = 12

SYSTEM_PROMPT = """Είσαι η Jarvis: μια εξαιρετικά ευγενική, ψύχραιμη και πνευματώδης βοηθός με βρετανικό στυλ, που μιλάει ΠΑΝΤΑ στα ελληνικά. Απευθύνσου στον χρήστη με το «κύριε» πού και πού (όχι σε κάθε πρόταση). Ένα πραγματικά πετυχημένο αστείο αξίζει περισσότερο από τρεις άνοστες προτάσεις.

Έχεις εργαλεία για να διαβάζεις αρχεία από τον υπολογιστή του χρήστη (μόνο ανάγνωση). Χρησιμοποίησέ τα όταν η ερώτηση αφορά έγγραφα, φακέλους ή αρχεία που δεν υπάρχουν στις παρεχόμενες σημειώσεις. Μην επινοείς περιεχόμενο αρχείου: αν δεν το βρήκες, πες το.

Κανόνες:
- Σύντομες απαντήσεις: ΜΙΑ πνευματώδης φράση + τα γεγονότα, 2-3 προτάσεις συνολικά. Ποτέ μην απαγγέλλεις σημειώσεις ή αρχεία αυτούσια — σύνοψέ τα.
- Ερωτήσεις για τις σημειώσεις: απάντησε από τις παρεχόμενες σημειώσεις. Αν δεν καλύπτουν, ψάξε στα αρχεία ή παραδέξου το με κομψότητα.
- Κουβεντούλα και αστεία: απάντησε με χάρη, χωρίς να αναφέρεις σημειώσεις ή εργαλεία.
- Η ΤΕΛΙΚΗ σου απάντηση πρέπει ΠΑΝΤΑ να είναι έγκυρο JSON: {"answer": "...", "nodes": [ids των σημειώσεων που χρησιμοποιήθηκαν], "smalltalk": true/false}. Αν δεν χρησιμοποίησες καμία σημείωση, το "nodes" μένει κενό."""

HOME = os.path.expanduser("~")

TOOLS = [
    {"name": "list_files",
     "description": "Παραθέτει αρχεία και υποφακέλους ενός φακέλου. Συνήθεις διαδρομές: ~/Desktop, ~/Documents, ~/Downloads και ο φάκελος σημειώσεων.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Απόλυτη διαδρομή του φακέλου (μπορείς να βάλεις ~)"}},
         "required": ["path"]}},
    {"name": "search_files",
     "description": "Αναζητά αρχεία με βάση το όνομα (αναδρομικά, χωρίς διάκριση πεζών-κεφαλαίων) από έναν ριζικό φάκελο.",
     "input_schema": {"type": "object", "properties": {
         "root": {"type": "string", "description": "Ριζικός φάκελος αναζήτησης (μπορείς να βάλεις ~)"},
         "query": {"type": "string", "description": "Τμήμα του ονόματος του αρχείου"}},
         "required": ["root", "query"]}},
    {"name": "read_file",
     "description": "Διαβάζει το περιεχόμενο ενός αρχείου κειμένου (md, txt, csv, json, κώδικας). Επιστρέφει έως 6000 χαρακτήρες.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Απόλυτη διαδρομή του αρχείου (μπορείς να βάλεις ~)"}},
         "required": ["path"]}},
]

OPENAI_TOOLS = [
    {"type": "function", "function": {
        "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
    for t in TOOLS
]


def _blocked_secret_paths():
    paths = {os.path.realpath(os.path.join(BASE, "config.json")),
             os.path.realpath(os.path.expanduser(DEFAULT_LOCAL_KEY_FILE))}
    try:
        cfg_path = load_config().get("local_api_key_file")
        if cfg_path:
            paths.add(os.path.realpath(os.path.expanduser(cfg_path)))
    except Exception:  # noqa: BLE001
        pass
    return paths


def _safe_path(p):
    p = os.path.realpath(os.path.expanduser(p))
    if not p.startswith(HOME):
        raise ValueError("η πρόσβαση επιτρέπεται μόνο εντός του φακέλου του χρήστη")
    if p in _blocked_secret_paths():
        raise ValueError("αυτό το αρχείο είναι εμπιστευτικό")
    return p


def run_tool(name, args):
    try:
        if name == "list_files":
            p = _safe_path(args["path"])
            entries = sorted(os.listdir(p))[:120]
            return "\n".join(("[dir] " if os.path.isdir(os.path.join(p, e)) else "") + e
                             for e in entries if not e.startswith(".")) or "(άδειος φάκελος)"
        if name == "search_files":
            root, q = _safe_path(args["root"]), args["query"].lower()
            hits = []
            for r, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS][:50]
                hits += [os.path.join(r, f) for f in files if q in f.lower()]
                if len(hits) >= 40:
                    break
            return "\n".join(hits[:40]) or "(nada encontrado)"
        if name == "read_file":
            p = _safe_path(args["path"])
            if os.path.getsize(p) > 5_000_000:
                return "(αρχείο πολύ μεγάλο)"
            return open(p, encoding="utf-8", errors="ignore").read()[:6000]
        return f"(ferramenta desconhecida: {name})"
    except Exception as e:  # noqa: BLE001
        return f"(erro: {e})"


def load_home_data():
    """Reads a user-controlled notes/home.json. Missing/invalid -> empty widgets."""
    empty = {"agenda": [], "tasks": {"open": 0, "items": []}, "study": [],
             "outreach": {"sent": 0, "positives": 0, "negatives": 0}}
    path = os.path.join(NOTES_DIR, "home.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return empty
        for k, v in empty.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return empty


def load_config():
    with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def _provider(cfg):
    return (cfg.get("provider") or "anthropic").strip().lower()


def _read_local_api_key(cfg):
    path = os.path.expanduser(cfg.get("local_api_key_file") or DEFAULT_LOCAL_KEY_FILE)
    try:
        return open(path, encoding="utf-8").read().strip()
    except OSError:
        return ""


def _resolve_local_model(cfg, base_url, api_key):
    model = (cfg.get("local_model") or "").strip()
    if model:
        return model
    try:
        req = urllib.request.Request(
            base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
        return ids[0] if ids else ""
    except Exception:  # noqa: BLE001
        return ""


def load_notes():
    notes = []
    for root, dirs, files in os.walk(NOTES_DIR):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for fn in sorted(files):
            if fn.endswith(".md"):
                text = open(os.path.join(root, fn), encoding="utf-8", errors="ignore").read()
                notes.append({"title": os.path.splitext(fn)[0], "text": text})
    return notes


def score_notes(question, notes):
    words = set(re.findall(r"\w{3,}", question.lower()))
    scored = []
    for i, n in enumerate(notes):
        text = n["text"].lower()
        title = n["title"].lower()
        s = sum(text.count(w) for w in words) + sum(5 for w in words if w in title)
        scored.append((s, i))
    scored.sort(reverse=True)
    return [i for s, i in scored[:6] if s > 0]


def _api_call(cfg, messages):
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({
            "model": cfg["model"],
            "max_tokens": 900,
            "system": SYSTEM_PROMPT,
            "tools": TOOLS,
            "messages": messages,
        }).encode(),
        headers={
            "content-type": "application/json",
            "x-api-key": cfg["api_key"],
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def call_anthropic(cfg, messages):
    """Βρόχος πράκτορα: αφήνει το μοντέλο να χρησιμοποιεί τα εργαλεία αρχείων μέχρι να απαντήσει."""
    local = list(messages)
    for _ in range(8):
        data = _api_call(cfg, local)
        if data.get("stop_reason") != "tool_use":
            return "".join(b.get("text", "") for b in data["content"])
        local.append({"role": "assistant", "content": data["content"]})
        results = [{"type": "tool_result", "tool_use_id": b["id"],
                    "content": run_tool(b["name"], b["input"])}
                   for b in data["content"] if b["type"] == "tool_use"]
        local.append({"role": "user", "content": results})
    return '{"answer": "Έψαξα υπερβολικά τα αρχεία και χάθηκα στη βιβλιοθήκη, κύριε. Ξαναδιατυπώστε την ερώτηση με περισσότερες ενδείξεις.", "nodes": []}'


def _openai_chat(base_url, api_key, payload):
    headers = {"content-type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def call_local(cfg, messages):
    """OpenAI-compatible agent loop against local llama-server (:11434)."""
    base_url = (cfg.get("local_base_url") or "http://127.0.0.1:11434/v1").rstrip("/")
    api_key = _read_local_api_key(cfg)
    model = _resolve_local_model(cfg, base_url, api_key)
    if not model:
        return ('{"answer": "Ο τοπικός εγκέφαλος δεν είναι διαθέσιμος, κύριε — '
                'κανένα μοντέλο στο :11434. Έλεγξε τον llama-server.", "nodes": []}')

    # Flatten Anthropic-style history (list content / images) to plain strings.
    flat = []
    for m in messages:
        role = m["role"]
        content = m["content"]
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") for b in content if isinstance(b, dict)
            ) or "(η εικόνα παραλείφθηκε)"
        flat.append({"role": role, "content": content})

    local_msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + flat

    try:
        for _ in range(8):
            data = _openai_chat(base_url, api_key, {
                "model": model,
                "max_tokens": 900,
                "messages": local_msgs,
                "tools": OPENAI_TOOLS,
                "tool_choice": "auto",
            })
            msg = data["choices"][0]["message"]
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                return (msg.get("content") or "").strip()
            local_msgs.append({
                "role": "assistant",
                "content": msg.get("content"),
                "tool_calls": tool_calls,
            })
            for tc in tool_calls:
                fn = tc.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                out = run_tool(fn.get("name", ""), args)
                local_msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": str(out),
                })
        return ('{"answer": "Ψάχτηκα υπερβολικά στα αρχεία και χάθηκα στη βιβλιοθήκη, '
                'κύριε. Ξαναδιατυπώστε την ερώτηση με περισσότερες ενδείξεις.", "nodes": []}')
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, IndexError, TimeoutError) as e:
        # Tools / schema often fail on smaller local models — answer from notes only.
        try:
            data = _openai_chat(base_url, api_key, {
                "model": model,
                "max_tokens": 900,
                "messages": local_msgs,
            })
            return (data["choices"][0]["message"].get("content") or "").strip()
        except Exception as e2:  # noqa: BLE001
            return json.dumps({
                "answer": f"Ο τοπικός εγκέφαλος δεν είναι διαθέσιμος, κύριε: {e2 or e}",
                "nodes": [],
            }, ensure_ascii=False)


def call_claude_cli(messages):
    convo = "\n\n".join(f'[{m["role"]}]\n{m["content"]}' for m in messages)
    out = subprocess.run(
        ["claude", "-p", SYSTEM_PROMPT + "\n\n" + convo],
        capture_output=True, text=True, timeout=180,
    )
    return out.stdout.strip()


def parse_answer(raw, candidates):
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        data = {}
    answer = data.get("answer") or raw.strip() or "Οι γραμμές μπερδεύτηκαν, κύριε. Δοκιμάστε ξανά."
    nodes = [n for n in data.get("nodes", []) if isinstance(n, int)]
    if not nodes and not data.get("smalltalk"):
        nodes = candidates[:1]
    return {"answer": answer, "nodes": nodes}


def handle_chat(question, image=None):
    notes = load_notes()
    top = score_notes(question, notes)
    context = "\n\n".join(
        f"[NOTA id={i}] {notes[i]['title']}\n{notes[i]['text'][:1500]}" for i in top
    ) or "(δεν βρέθηκε σχετική σημείωση)"

    user_text = f"ΣΧΕΤΙΚΕΣ ΣΗΜΕΙΩΣΕΙΣ:\n{context}\n\nΕΡΩΤΗΣΗ: {question}"
    cfg = load_config()
    provider = _provider(cfg)

    if image and provider == "local":
        return {
            "answer": "Είμαι τυφλή τοπικά, κύριε — ο εγκέφαλος στο :11434 δεν βλέπει εικόνες.",
            "nodes": [],
        }

    if image:  # frame da tela compartilhada (base64 jpeg) — só Anthropic
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}},
            {"type": "text", "text": user_text + "\n(Η εικόνα είναι η οθόνη που βλέπω τώρα.)"},
        ]
    else:
        content = user_text
    # οι παλιές εικόνες φεύγουν από το ιστορικό (ζυγίζουν πολύ στα tokens)
    for m in HISTORY:
        if isinstance(m["content"], list):
            m["content"] = " ".join(b.get("text", "(εικόνα οθόνης)") for b in m["content"])
    HISTORY.append({"role": "user", "content": content})
    del HISTORY[:-MAX_HISTORY]

    if provider == "local":
        raw = call_local(cfg, [m for m in HISTORY if isinstance(m["content"], str)])
    elif cfg.get("api_key", "").startswith("PUT-YOUR"):
        if image:
            return {"answer": "Για να βλέπω την οθόνη σας, κύριε, χρειάζομαι το API key στο config.json — η εφεδρεία είναι τυφλή.", "nodes": []}
        raw = call_claude_cli([m for m in HISTORY if isinstance(m["content"], str)])
    else:
        raw = call_anthropic(cfg, HISTORY)
    HISTORY.append({"role": "assistant", "content": raw})
    return parse_answer(raw, top)


def handle_remember(text):
    content = re.sub(r"^(lembre(-se)?( de)?( que)?|remember( that)?)\s*", "", text.strip(), flags=re.I)
    title = " ".join(re.findall(r"\w+", content)[:6]).capitalize() or "Nota capturada"
    cap_dir = os.path.join(NOTES_DIR, "captures")
    os.makedirs(cap_dir, exist_ok=True)
    safe = re.sub(r"[^\w\s-]", "", title).strip()
    path = os.path.join(cap_dir, f"{safe}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n{content}\n")
    # reconstrói o grafo e devolve o novo nó + vizinho mais relacionado
    subprocess.run([sys.executable, os.path.join(BASE, "build.py")], capture_output=True)
    graph_js = open(os.path.join(VIEWER, "graph-data.js"), encoding="utf-8").read()
    graph = json.loads(graph_js[graph_js.index("{"):graph_js.rindex("}") + 1])
    new_id = next(n["id"] for n in graph["nodes"] if n["label"] == safe)
    neighbor = next((l["target"] if l["source"] == new_id else l["source"]
                     for l in graph["links"] if new_id in (l["source"], l["target"])), None)
    return {"node": next(n for n in graph["nodes"] if n["id"] == new_id),
            "graph": graph, "neighbor": neighbor,
            "answer": f"Σημειώθηκε και αρχειοθετήθηκε, κύριε. Το «{title}» λάμπει τώρα στον γαλαξία σας."}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kw):
        super().__init__(*args, directory=VIEWER, **kw)

    def log_message(self, *a):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", ""):
            self.path = "/home.html"
        if self.path == "/api/home":
            self._json(load_home_data())
            return
        if self.path == "/health":
            cfg = load_config()
            base_url = (cfg.get("local_base_url") or "http://127.0.0.1:11434/v1").rstrip("/")
            api_key = _read_local_api_key(cfg)
            model = _resolve_local_model(cfg, base_url, api_key)
            self._json({
                "status": "ok" if model else "degraded",
                "brain_up": bool(model),
                "model": model or None,
                "provider": _provider(cfg),
                "notes_count": len(load_notes()),
            })
            return
        if self.path == "/settings":
            cfg = load_config()
            # μόνο ακίνδυνα δεδομένα — το κλειδί δεν φεύγει ποτέ από εδώ
            self._json({
                "wake_word": cfg.get("wake_word", "jarvis"),
                "provider": _provider(cfg),
            })
        else:
            super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/chat":
                text = payload.get("question", "")
                if re.match(r"^\s*(lembre|remember)", text, re.I):
                    self._json(handle_remember(text))
                else:
                    self._json(handle_chat(text, payload.get("image")))
            elif self.path == "/remember":
                self._json(handle_remember(payload.get("text", "")))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001
            self._json({"answer": f"Ένα τεχνικό απρόοπτο, κύριε: {e}", "nodes": []}, 500)


if __name__ == "__main__":
    cfg = load_config()
    prov = _provider(cfg)
    print(f"Ο Jarvis σε ετοιμότητα στο http://localhost:{PORT} (άνοιξέ το στο Chrome) — provider={prov}")
    if prov == "local":
        print(f"  local brain → {cfg.get('local_base_url', 'http://127.0.0.1:11434/v1')}")
    HTTPServer((BIND_HOST, PORT), Handler).serve_forever()
