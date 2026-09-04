# Collaboration & Development Guide

**Project:** Jarvis Second Brain / Local AI Assistant  
**Source plan:** [Jarvis_Second_Brain_Collaboration_Plan.docx](Jarvis_Second_Brain_Collaboration_Plan.docx)  
**Canonical workspace (EVO-3):** `/home/thomas-pashoulas/Desktop/jarvis-second-brain`  
(compat symlink: `~/jarvis-second-brain` → same folder)

Read this before changing architecture or merging experimental work. Machine identity and bind policy live in [`../MACHINE.md`](../MACHINE.md). First-run checklist: [`../CHECKLIST.md`](../CHECKLIST.md).

---

## 1. Project goal

Build and improve a local AI assistant that acts as a second brain. The system should help capture thoughts, understand recurring patterns, organize information, and eventually identify or predict overthinking patterns.

## 2. Current direction

- Use the existing Jarvis Second Brain project as the foundation.
- Keep the system focused on local tools and local execution where practical.
- Explore the combination of n8n, AI agents, the existing Jarvis system, and Hermes.
- Improve the assistant based on real daily use rather than building unnecessary features.

**EVO reality (today):** primary path is **web galaxy** (`server.py` + `viewer/`) with local brain on `127.0.0.1:11434`. Desktop voice (`desktop/`) is secondary on this machine.

## 3. Initial development plan

1. **Understand the existing codebase** — structure, configuration, models, tools, prompts, workflows.
2. **Run the project locally** — verify the current system works before changing core behavior.
3. **Map the existing architecture** — how AI, tools, memory/second-brain, and automation communicate.
4. **Identify improvement points** — reliability, reasoning, memory, automation, or user interaction.
5. **Prototype one useful improvement** — small, measurable change instead of broad rewrites.
6. **Test with real use cases** — thought-capture / overthinking examples; compare vs current behavior.

### Quick verify on EVO

```bash
cd /home/thomas-pashoulas/Desktop/jarvis-second-brain
curl -sS http://127.0.0.1:4700/health
# open http://127.0.0.1:4700 in a browser on the EVO display
```

Galaxy: `jarvis-galaxy.service` → `127.0.0.1:4700`  
Brain: `llama-server.service` → `127.0.0.1:11434`  
Both loopback-only; from another machine use SSH tunnel (never bind `0.0.0.0` without explicit agreement).

## 4. n8n / automation direction

n8n can be the orchestration layer for external services and repeatable workflows. Do not force everything through n8n — use it where automation clearly helps.

- Connect external services when needed.
- Trigger AI workflows from defined events.
- Keep sensitive or core processing local where possible.
- Compare n8n-based workflows with Hermes and the existing local architecture.

## 5. Collaboration workflow

- Work against the shared EVO environment when necessary.
- Prefer Git-based version control for code changes.
- Create a **separate branch** for experimental changes.
- Explain significant architectural or behavioral changes before merging.
- Keep configuration, credentials, and secrets out of the repository (`config.json`, API key files).
- Document completed work so both collaborators can understand and maintain it.

### Remotes (this clone)

| Remote | Repo |
|--------|------|
| `mine` | `https://github.com/thomaspas/jarvis-second-brain` |
| `fork1` | `https://github.com/thomaspas/jarvis-second-brain-1` |
| `ksenoi-mhn-pusharis` | upstream `Thaynabarreiro/jarvis-second-brain` |

Default active branch for EVO web-galaxy work: `cursor/web-galaxy-first-run`.

## 6. First milestone

A working base of the system running reliably with the existing local setup, followed by **one concrete improvement** to the assistant’s ability to organize or reason about the user’s thoughts.

## 7. What is needed from the project owner

- Clarification of the highest-priority user problem.
- Access to the relevant project files and development environment.
- Existing prompts, notes, or design decisions that should not be changed.
- Examples of current behavior that works well and behavior that should be improved.
- Agreement on how changes should be tested and merged.

## 8. Working principle

Focus on useful results rather than simply adding code. Each change should have a clear purpose, be testable, and improve the system for the actual user.

## 9. Immediate next steps

1. Finish local setup and verify the current project.
2. Review the existing prompts and architecture.
3. Identify the first improvement opportunity.
4. Discuss the proposed change with the project owner.
5. Implement, test, and demonstrate the first working improvement.

---

## Doc map for collaborators

| Doc | Role |
|-----|------|
| This file | Collaboration / development guide |
| [`MACHINE.md`](../MACHINE.md) | EVO-3 hardware, services, bind policy |
| [`CHECKLIST.md`](../CHECKLIST.md) | Install / verify checklist |
| [`README.md`](../README.md) | Product overview and stack |
| Original `.docx` | Same plan as Word source of truth for contractors |
