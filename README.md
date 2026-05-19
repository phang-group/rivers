# River's Engineer

**AI-native engineering workflow tool.** Reverse-engineers any codebase into a complete architectural story using two collaborating LLMs.

Works with **DeepSeek, Anthropic Claude, OpenAI, and Ollama** — you control the provider.

---

## What it does

```
filesystem collector → structural analyzer → LLM 1 (Archaeologist) → LLM 2 (Critic) → markdown/json report → local UI
```

The **Archaeologist** reads the codebase and writes Chapters 1–4: architecture, data flow, entry points, tech map.

The **Critic** receives the Archaeologist's output as input data (not shared context), challenges the findings, and produces Chapter 5 + a Reverse Path — the sequence of steps to rebuild the system from scratch.

Both LLMs work independently. The separation produces better output than one LLM asked to do both.

---

## Quick start

```bash
pip install -e .

# Default: DeepSeek (fast, cost-efficient)
export RIVER_API_KEY=your-deepseek-key
river analyze ./your-project

# Use Anthropic Claude instead
export RIVER_PROVIDER=anthropic
export RIVER_API_KEY=your-anthropic-key
river analyze ./your-project

# Use OpenAI
export RIVER_PROVIDER=openai
export RIVER_API_KEY=your-openai-key
river analyze ./your-project

# Use Ollama (local, no key required)
export RIVER_PROVIDER=ollama
export RIVER_MODEL=llama3
river analyze ./your-project
```

---

## Provider configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RIVER_PROVIDER` | `deepseek` | Provider: `deepseek`, `anthropic`, `openai`, `ollama` |
| `RIVER_API_KEY` | — | API key for the selected provider |
| `RIVER_MODEL` | provider default | Override model name |
| `RIVER_API_BASE` | provider default | Override base URL (useful for proxies, local models) |

Provider defaults:

| Provider | Default model | Base URL |
|----------|--------------|----------|
| deepseek | `deepseek-chat` | `https://api.deepseek.com` |
| anthropic | `claude-sonnet-4-6` | Anthropic SDK default |
| openai | `gpt-4o` | `https://api.openai.com/v1` |
| ollama | `llama3` | `http://localhost:11434/v1` |

---

## Commands

```bash
# Analyze a codebase
river analyze ./my-project

# Analyze a specific git branch
river analyze ./my-project --branch feature/auth

# Summary mode (structure only, faster and cheaper)
river analyze ./my-project --depth summary

# Save report to a specific path
river analyze ./my-project --output ./reports/my-project.md

# Open the visual UI (reads the most recent report)
river ui

# Open with a specific report
river ui --file ./river-report-20240101-120000.json
```

---

## Project structure

```
rivers_engineer/
├── cli.py            — Entry point: analyze + ui subcommands
├── provider.py       — Provider abstraction (DeepSeek/Anthropic/OpenAI/Ollama)
├── collector.py      — Filesystem walker, file reader, smart truncation
├── analyzer.py       — Language/framework detection, AST, dependency parsing
├── archaeologist.py  — LLM 1: produces Chapters 1-4
├── critic.py         — LLM 2: produces Chapter 5 + Reverse Path
├── prompts.py        — All LLM prompt templates
├── reporter.py       — Assembles .md + .json output
├── page_generator.py — LLM 3: generates UI wireframes (on demand)
├── ui_server.py      — FastAPI server for the visual UI
└── ui/
    └── index.html    — Single-file visual interface
```

---

## Stack

- Python 3.9+
- Typer + Rich (CLI)
- FastAPI + Uvicorn (local UI server)
- openai SDK (DeepSeek, OpenAI, Ollama)
- anthropic SDK (Claude)

---

## Design philosophy

PHANG controls orchestration. Not vendors. Provider-agnostic by default so that model changes, pricing shifts, and inference economics don't require code changes — only environment variable changes.

The Archaeologist + Critic pattern mirrors good human review: one person documents thoroughly, another challenges aggressively. Neither role works as well when collapsed into one.

---

## Troubleshooting

**`river: command not found`**
```bash
pip install -e .
```

**`No API key found`**
```bash
export RIVER_API_KEY=your-key
# or export RIVER_PROVIDER=anthropic && export RIVER_API_KEY=your-anthropic-key
```

**Analysis is slow / expensive**
```bash
river analyze ./my-project --depth summary
```
Summary mode skips file contents and analyzes structure only.

**Using local models with Ollama**
```bash
ollama pull llama3
export RIVER_PROVIDER=ollama
river analyze ./my-project
```

---

## Never commit

- API keys
- Generated `river-report-*` artifacts (unless curating examples)
- Virtualenvs, caches, build outputs

---

## License

MIT
