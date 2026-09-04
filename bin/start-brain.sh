#!/usr/bin/env bash
# Standalone llama.cpp launcher for jarvis-second-brain.
# Independent of the deleted ~/jarvis-os. Vulkan bare-metal, OpenAI-compatible :11434.
set -euo pipefail

MODEL="${LLM_MODEL:-$HOME/models/Qwen3.6-27B-Fable-Fus-711-UnHeretic-NM-DAU-NEO-MAX-NEO-MTP-Q4_K_M.gguf}"
BIN="${LLAMA_SERVER_BIN:-$HOME/ai_stack/llama.cpp/build/bin/llama-server}"
MMPROJ="${LLM_MMPROJ:-$HOME/models/mmproj-F16.gguf}"
KEY_FILE="${LLAMA_API_KEY_FILE:-$HOME/.cursor/deepseek-cursor-api.key}"
HOST="${LLM_HOST:-0.0.0.0}"
PORT="${LLM_PORT:-11434}"
CTX="${LLM_CTX:-65536}"
NGL="${LLM_NGL:-999}"

[ -f "$MODEL" ] || { echo "start-brain: model missing: $MODEL" >&2; exit 1; }
[ -x "$BIN" ]   || { echo "start-brain: binary missing: $BIN" >&2; exit 1; }
[ -f "$KEY_FILE" ] || { echo "start-brain: api key file missing: $KEY_FILE" >&2; exit 1; }

BASE="$(basename "$MODEL")"
ALIAS="${BASE%.gguf}"; ALIAS="${ALIAS%-Q4_K_M}"

args=(-m "$MODEL" --host "$HOST" --port "$PORT" -c "$CTX" -ngl "$NGL"
      --alias "$ALIAS" --api-key-file "$KEY_FILE")
[ -f "$MMPROJ" ] && args+=(--mmproj "$MMPROJ")

cd "$(dirname "$BIN")"
exec "$BIN" "${args[@]}"
