# Agent Lab

Agent Lab is a local-first workbench for testing how small language models handle bounded project work. The harness—not the model alone—supplies project workspaces, a limited tool catalog, workflow gates, persistence, and independent task evaluators. Local GGUF inference through llama.cpp is the default; an OpenAI-compatible API is an optional experiment using the same harness.

## Why it exists

It started as a curiosity: how competent can a model small enough to run on an ordinary desktop (an i5-8400 with a GTX 1070) become when the harness around it does the heavy lifting, and what are the pieces of the harnesses behind Codex, Claude Code and the chat apps? It is a learning project and something to show and play with, not a daily-driver coding agent. The output worth having is evidence about what each part of the harness adds to a tiny model, graded by checkers that test whether the result actually works.

## Quick start

On Windows, from the repository root, use two PowerShell windows. The checked-in configuration currently targets local Gemma 4 E2B at 127.0.0.1:8080.

    # Window 1: start the local model server
    .\scripts\start-gemma4-local.ps1 -ModelSize E2B

    # Window 2: start the Agent Lab console
    .\scripts\start-agent-lab-ui.ps1

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). Before starting, make sure the selected GGUF model and llama.cpp runtime are present under models/ and runtime/; those large assets are intentionally excluded from Git. Detailed setup, bridges, providers, workspaces, and operator commands are in [the operational guide](agent-lab/README.md).

## Browse the interface

The [public showcase](https://silascroe.github.io/lobotomite-harness/) is the real Agent Lab console in read-only showcase mode, replaying recorded runs exactly as they happened. It has no model connection and cannot reach this computer; every action that would start or change work is switched off. Recordings are exported and sanitized with `scripts/export_showcase.py` and deployed by `.github/workflows/pages.yml`.

## What it contains

- agent-lab/harness/ — model-provider integration, tool/action handling, workflow and recovery control, approvals, persistence, review evidence, and workspace leases.
- agent-lab/ui/ — the local web console (ES modules: views, narration, data source, specimen) and its Python server.
- site/showcase/ — sanitized run recordings the public showcase replays.
- agent-lab/tasks/ and agent-lab/checks/ — built-in task presets and independent evaluators.
- agent-lab/benchmarks/ — model-matrix runners, reports, and benchmark tests.
- scripts/ — Windows launchers, run commands, bridges, and response inspection.
- docs/ — architecture, current status, decisions, research, and dated designs/plans.

The app can work in scratch folders, persistent Agent Lab projects, or an explicitly selected existing folder. A selected folder is real filesystem access: path checks and workspace locks are not an operating-system sandbox. Use a deliberate project directory and keep credentials out of model-visible workspaces.

## Project map

- [Architecture](docs/ARCHITECTURE.md)
- [Current status and next work](docs/STATUS.md)
- [Durable design decisions](docs/DECISIONS.md)
- [Detailed operator guide](agent-lab/README.md)

Python unit tests and UI contract checks are documented in the operator guide. Model benchmarks are slower, depend on the local inference server, and write ignored run artifacts; they are not part of the quick test loop.
