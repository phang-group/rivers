# River's Engineer

River's Engineer is PHANG's public engineering credibility tool: a CLI and local UI that reverse-engineer codebases into architectural reports.

## Purpose

This repository exists to turn real codebases into explainable architecture artifacts. It is both a product and a public demonstration of PHANG's engineering taste.

## Status

**Phase:** active build, pre-launch  
**Visibility direction:** public/open-source  
**Operational posture:** local-first, contributor-ready

## Architecture

Current structure is a Python package with two main surfaces:

- CLI surface through `river`
- local UI server for report visualization

High-level flow:

`filesystem collector -> structural analyzer -> LLM pass 1 -> LLM pass 2 -> markdown/json report -> local UI`

## Stack

- Python
- Typer
- Rich
- FastAPI
- Uvicorn
- Anthropic SDK
- setuptools packaging

## Roadmap Direction

Short-term:
- stabilize the core analyze pipeline
- make report artifacts deterministic enough for repeated use
- tighten packaging and contributor onboarding

Medium-term:
- improve report/UI coupling
- add tests around collector/analyzer behavior
- prepare for public repo visibility under PHANG branding

## Deployment Direction

This is not a VPS-first product right now. Deployment direction is:

- local CLI install for early users
- optional hosted demo later if economics and maintenance justify it

## Environment

Use `.env.example` or exported shell variables for local setup. The only required secret today is the Anthropic API key.

## Never Commit

- real API keys
- generated local report artifacts unless intentionally publishing examples
- virtualenvs, caches, build outputs, local test fixtures with user code

## Folder Hygiene Suggestions

- keep package code under `rivers_engineer/` only
- separate example artifacts from real generated output
- avoid checking in reports created from private client codebases
- add tests for collector and analyzer regressions before widening scope

## Safe Git Commands

```bash
git status
git remote -v
git checkout -b chore/repo-hygiene
git add README.md .gitignore .env.example pyproject.toml
git diff --staged
git commit -m "docs: standardize repo entrypoint and hygiene"
```

## Migration Notes

- local folder name remains `rivers-engineer 2`; remote can remain `rivers`
- before public push, normalize branding, homepage URLs, and contribution docs
- generated `river-report-*` output should stay local unless intentionally curated as examples

## Quick Start

```bash
pip install -e .
export ANTHROPIC_API_KEY=replace-me
river --help
```

3. **`analyzer.analyze()`** — detects languages, parses dependency manifests, runs AST extraction, detects frameworks, selects top 25 key files
4. **`archaeologist.excavate()`** — builds context prompt, sends to `claude-sonnet-4-6`, retries on rate limits, returns Chapters 1–4
5. **`critic.critique()`** — receives archaeology text as input data, sends to a second independent LLM call, returns Chapter 5 + Reverse Path
6. **`reporter.generate()`** — assembles the markdown book, writes `.md` and `.json` sidecar to the project directory
7. **Terminal** — Rich renders the completion panel, then prints a Chapter 1 preview in the terminal
8. **`river ui`** — FastAPI + uvicorn serve `ui/index.html` on `localhost:3000`

---

## Project structure

```
rivers_engineer/
├── cli.py           — Entry point, two subcommands: analyze + ui
├── collector.py     — Filesystem walker, file reader, smart truncation
├── analyzer.py      — Language/framework detection, AST extraction, dep parsing
├── archaeologist.py — LLM 1: produces Chapters 1–4
├── critic.py        — LLM 2: produces Chapter 5 + Reverse Path
├── prompts.py       — All LLM prompt templates
├── reporter.py      — Assembles .md + .json output files
├── page_generator.py — LLM 3: generates UI wireframes (on demand)
├── ui_server.py     — FastAPI server for the visual UI
└── ui/
    └── index.html   — Single-file visual interface
```

---

## Troubleshooting

**`river: command not found`**
```bash
pip install -e ~/Desktop/rivers-engineer\ 2
```

**`Your credit balance is too low`**
Add API credits at [console.anthropic.com](https://console.anthropic.com) → Plans & Billing. Note: Claude Pro (claude.ai) and API credits are separate.

**`pip install` fails with `BackendUnavailable`**
The `pyproject.toml` had a bad build backend. It's already fixed in this repo — just re-run `pip install -e .`.

**Analysis is slow**
Use `--depth summary` to skip file contents and only analyze structure. Much faster and cheaper for large projects.
