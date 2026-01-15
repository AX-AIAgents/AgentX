# 🔗 AgentX: Cross-API Orchestration Benchmark

<div align="center">

**The first benchmark for evaluating AI agents on cross-API orchestration tasks**

[![Tasks](https://img.shields.io/badge/Tasks-103-blue?style=for-the-badge)]()
[![Tools](https://img.shields.io/badge/Tools-76-green?style=for-the-badge)]()
[![APIs](https://img.shields.io/badge/APIs-5-orange?style=for-the-badge)]()
[![AgentBeats](https://img.shields.io/badge/AgentBeats-13%2F13-success?style=for-the-badge)]()

</div>

---

## 🎯 What is Cross-API Orchestration?

Unlike single-API benchmarks, **AgentX** evaluates agents on tasks that require **chaining operations across multiple API providers**:

```
📋 Task: "Compile Q4 metrics and notify stakeholders"

  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
  │   Notion    │ ──▶ │Google Drive │ ──▶ │Google Sheets│
  │  (search)   │     │ (get docs)  │     │ (get data)  │
  └─────────────┘     └─────────────┘     └─────────────┘
         │                                       │
         ▼                                       ▼
  ┌─────────────┐                         ┌─────────────┐
  │ Google Docs │ ◀─────────────────────▶ │   Gmail     │
  │ (create)    │                         │  (draft)    │
  └─────────────┘                         └─────────────┘
```

---

## 📊 3D Scoring System

| Metric | Weight | What It Measures |
|--------|--------|-----------------|
| **Action Match** | 50% | Did the agent call the right tools? |
| **Argument Quality** | 40% | Were parameters correct? |
| **Efficiency** | 10% | How many steps were used? |

```
Total Score = (Action × 0.5) + (Argument × 0.4) + (Efficiency × 0.1)
```

---

## 🚀 Quick Start

### Prerequisites
- Python 3.13+ with [uv](https://github.com/astral-sh/uv)
- Docker (optional)

### Run Locally

```bash
# Clone & install
git clone https://github.com/AX-AIAgents/AgentX.git
cd AgentX && uv sync

# Set API key
export OPENAI_API_KEY=your_key

# Run evaluation
uv run agentbeats-run scenario.toml
```

### Run with Docker

```bash
docker compose up
```

---

## 📁 Project Structure

```
AgentX/
├── src/
│   ├── server.py              # Green Agent (Evaluator)
│   ├── mcp_http_server.py     # 76 MCP Tools Server
│   ├── agents/agent.py        # Purple Agent (Participant)
│   └── data/
│       └── task_definitions.jsonl  # 103 Tasks
├── ABSTRACT.md                # Academic documentation
├── DIAGRAM.md                 # Architecture diagrams
└── scenario.toml              # Benchmark configuration
```

---

## 🔧 API Coverage

| Provider | Tools | Example Operations |
|----------|-------|-------------------|
| **Notion** | 21 | Search, create pages, append blocks |
| **Gmail** | 12 | Search, read, draft, send emails |
| **Google Drive** | 18 | Search, create docs/sheets/slides |
| **YouTube** | 3 | Get transcripts, video info |
| **Web Search** | 2 | Serper search, URL scraping |

---

## 📈 Benchmark Results

| Agent | Action | Argument | Efficiency | **Total** |
|-------|--------|----------|------------|-----------|
| GPT-4o-mini | 28.57% | 21.43% | 57.14% | **28.57%** |
| *Your Agent* | ? | ? | ? | ? |

---

## 📄 Documentation

- [**ABSTRACT.md**](ABSTRACT.md) - Academic paper format
- [**DIAGRAM.md**](DIAGRAM.md) - Architecture & flow diagrams

---

## 📜 License

MIT License

---

<div align="center">

**Built for AgentBeats Benchmark Competition 2026**

*5 APIs • 76 Tools • 103 Tasks • 3D Scoring*

</div>