#!/usr/bin/env python3
"""Servidor do Jarvis: serve viewer/ e expõe /chat e /remember.

Só biblioteca padrão. A API key vive em config.json (fora de viewer/)
e nunca é enviada ao navegador.

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
PORT = 4700
DEFAULT_LOCAL_KEY_FILE = "/home/thomas-pashoulas/.cursor/deepseek-cursor-api.key"

HISTORY = []  # histórico curto da sessão (lado servidor)
MAX_HISTORY = 12

SYSTEM_PROMPT = """Você é Jarvis: um mordomo britânico impecavelmente educado, seco e de humor afiado, falando em português do Brasil. Chame a usuária de "senhora" de vez em quando (não em toda frase). Uma tirada genuinamente engraçada vale mais que três frases sem graça.

Você tem ferramentas para ler arquivos do computador da usuária (somente leitura). Use-as quando a pergunta envolver documentos, pastas ou arquivos que não estejam nas notas fornecidas. Não invente conteúdo de arquivo: se não encontrou, diga.

Regras:
- Respostas curtas: UMA frase espirituosa + os fatos, em 2-3 frases no total. Nunca recite notas ou arquivos de volta — resuma.
- Perguntas sobre as notas: responda a partir das notas fornecidas. Se não cobrirem, procure nos arquivos ou admita com elegância.
- Papo furado e piadas: responda com graça, sem citar notas nem usar ferramentas.
- Sua resposta FINAL deve ser SEMPRE JSON válido: {"answer": "...", "nodes": [ids das notas usadas], "smalltalk": true/false}. Se não usou nenhuma nota, "nodes" fica vazio."""

HOME = os.path.expanduser("~")

TOOLS = [
    {"name": "list_files",
     "description": "Lista arquivos e subpastas de uma pasta do computador. Caminhos comuns: ~/Desktop, ~/Documents, ~/Downloads e o vault de notas.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Caminho absoluto da pasta (pode usar ~)"}},
         "required": ["path"]}},
    {"name": "search_files",
     "description": "Procura arquivos pelo nome (busca recursiva, sem diferenciar maiúsculas) a partir de uma pasta raiz.",
     "input_schema": {"type": "object", "properties": {
         "root": {"type": "string", "description": "Pasta raiz da busca (pode usar ~)"},
         "query": {"type": "string", "description": "Trecho do nome do arquivo"}},
         "required": ["root", "query"]}},
    {"name": "read_file",
     "description": "Lê o conteúdo de um arquivo de texto (md, txt, csv, json, código). Retorna até 6000 caracteres.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Caminho absoluto do arquivo (pode usar ~)"}},
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
        raise ValueError("acesso permitido apenas dentro da pasta do usuário")
    if p in _blocked_secret_paths():
        raise ValueError("este arquivo é confidencial")
    return p


def run_tool(name, args):
    try:
        if name == "list_files":
            p = _safe_path(args["path"])
            entries = sorted(os.listdir(p))[:120]
            return "\n".join(("[dir] " if os.path.isdir(os.path.join(p, e)) else "") + e
                             for e in entries if not e.startswith(".")) or "(pasta vazia)"
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
                return "(arquivo grande demais)"
            return open(p, encoding="utf-8", errors="ignore").read()[:6000]
        return f"(ferramenta desconhecida: {name})"
    except Exception as e:  # noqa: BLE001
        return f"(erro: {e})"


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
    """Loop de agente: deixa o modelo usar as ferramentas de arquivo até responder."""
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
    return '{"answer": "Explorei demais os arquivos e me perdi na biblioteca, senhora. Refaça a pergunta com mais pistas.", "nodes": []}'


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
        return ('{"answer": "O cérebro local não está disponível, senhora — '
                'nenhum modelo em :11434. Verifique o llama-server.", "nodes": []}')

    # Flatten Anthropic-style history (list content / images) to plain strings.
    flat = []
    for m in messages:
        role = m["role"]
        content = m["content"]
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") for b in content if isinstance(b, dict)
            ) or "(imagem omitida)"
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
        return ('{"answer": "Explorei demais os arquivos e me perdi na biblioteca, '
                'senhora. Refaça a pergunta com mais pistas.", "nodes": []}')
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
                "answer": f"Cérebro local indisponível, senhora: {e2 or e}",
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
    answer = data.get("answer") or raw.strip() or "As linhas se cruzaram, senhora. Tente novamente."
    nodes = [n for n in data.get("nodes", []) if isinstance(n, int)]
    if not nodes and not data.get("smalltalk"):
        nodes = candidates[:1]
    return {"answer": answer, "nodes": nodes}


def handle_chat(question, image=None):
    notes = load_notes()
    top = score_notes(question, notes)
    context = "\n\n".join(
        f"[NOTA id={i}] {notes[i]['title']}\n{notes[i]['text'][:1500]}" for i in top
    ) or "(nenhuma nota relevante encontrada)"

    user_text = f"NOTAS RELEVANTES:\n{context}\n\nPERGUNTA: {question}"
    cfg = load_config()
    provider = _provider(cfg)

    if image and provider == "local":
        return {
            "answer": "Estou cego localmente, senhora — o cérebro em :11434 não vê imagens.",
            "nodes": [],
        }

    if image:  # frame da tela compartilhada (base64 jpeg) — só Anthropic
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}},
            {"type": "text", "text": user_text + "\n(A imagem é a tela que estou vendo agora.)"},
        ]
    else:
        content = user_text
    # imagens antigas saem do histórico (pesam demais nos tokens)
    for m in HISTORY:
        if isinstance(m["content"], list):
            m["content"] = " ".join(b.get("text", "(imagem da tela)") for b in m["content"])
    HISTORY.append({"role": "user", "content": content})
    del HISTORY[:-MAX_HISTORY]

    if provider == "local":
        raw = call_local(cfg, [m for m in HISTORY if isinstance(m["content"], str)])
    elif cfg.get("api_key", "").startswith("PUT-YOUR"):
        if image:
            return {"answer": "Para eu enxergar sua tela, senhora, preciso da API key no config.json — o fallback é cego.", "nodes": []}
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
            "answer": f"Anotado e arquivado, senhora. “{title}” agora brilha na sua galáxia."}


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
        if self.path == "/settings":
            cfg = load_config()
            # só dados inofensivos — a key jamais sai daqui
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
            self._json({"answer": f"Um contratempo técnico, senhora: {e}", "nodes": []}, 500)


if __name__ == "__main__":
    cfg = load_config()
    prov = _provider(cfg)
    print(f"Jarvis de prontidão em http://localhost:{PORT} (abra no Chrome) — provider={prov}")
    if prov == "local":
        print(f"  local brain → {cfg.get('local_base_url', 'http://127.0.0.1:11434/v1')}")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
