

## 🎬 Demo Video

[![AgentX Demo](https://img.shields.io/badge/Demo-Video-red?style=for-the-badge&logo=youtube)](https://youtu.be/YOUR_VIDEO_ID)

> *Video showcases end-to-end evaluation flow: task dispatch, tool execution, and 3D scoring*

---

## 🚀 Quick Start

### Prerequisites
- Python 3.13+
- [uv](https://github.com/astral-sh/uv) package manager
- Docker (for containerized deployment)

### Local Development

```bash
# Clone the repository
git clone https://github.com/AX-AIAgents/AgentX.git
cd AgentX

# Install dependencies
uv sync

# Set environment variables
export OPENAI_API_KEY=your_openai_key

# Run with AgentBeats CLI
uv run agentbeats-run scenario.toml
```

### Docker Deployment

```bash
# Pull images from GHCR
docker pull ghcr.io/ax-aiagents/green-agent:v1
docker pull ghcr.io/ax-aiagents/purple-agent:v1

# Run Green Agent (Evaluator)
docker run -d --name green-agent \
  -p 8090:8090 -p 8091:8091 \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  ghcr.io/ax-aiagents/green-agent:v1

# Run Purple Agent (Participant)
docker run -d --name purple-agent \
  -p 9000:9000 \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  ghcr.io/ax-aiagents/purple-agent:v1
```

---

## 📁 Project Structure

```
AgentX/
├── Dockerfile                    # Green Agent container
├── Dockerfile.purple             # Purple Agent container
├── scenario.toml                 # AgentBeats configuration
├── pyproject.toml                # Python dependencies
├── src/
│   ├── server.py                 # Green Agent entrypoint
│   ├── agent.py                  # Evaluation logic
│   ├── executor.py               # Task execution
│   ├── messenger.py              # A2A messaging
│   ├── mcp_http_server.py        # 76 MCP tools server
│   ├── agents/
│   │   ├── server.py             # Purple Agent entrypoint
│   │   └── agent.py              # OpenAI GPT-4o-mini agent
│   ├── tools/
│   │   ├── task_loader.py        # Task definitions loader
│   │   └── mcp_scorer.py         # 3D scoring engine
│   └── data/
│       └── task_definitions.jsonl # 103 evaluation scenarios
└── .github/
    └── workflows/
        └── publish.yml           # CI/CD for GHCR
```

---

## 🎯 Scoring System

AgentX uses a **3D Scoring Methodology**:

| Dimension | Weight | Description |
|-----------|--------|-------------|
| **Action Match** | 50% | Did the agent call the required tools? |
| **Argument Quality** | 40% | Were the parameters correct and complete? |
| **Efficiency** | 10% | How close to optimal step count? |

**Formula**: `Total = (Action × 0.5) + (Argument × 0.4) + (Efficiency × 0.1)`

---

## 🔧 Configuration

### scenario.toml
```toml
[green_agent]
endpoint = "http://127.0.0.1:8090"
cmd = "uv run src/server.py --host 127.0.0.1 --port 8090"

[[participants]]
role = "purple_agent"
endpoint = "http://127.0.0.1:9000"
cmd = "uv run src/agents/server.py --host 127.0.0.1 --port 9000 --mcp-endpoint http://localhost:8091"

[config]
task_ids = [0, 1, 2, 3, 4]
max_turns = 10
```

---

## 📊 AgentBeats Compliance

| Requirement | Status |
|-------------|--------|
| ENTRYPOINT with --host, --port | ✅ |
| Platform: linux/amd64 | ✅ |
| A2A Protocol v0.3.0 | ✅ |
| Stateless Design | ✅ |
| Artifact Generation | ✅ |
| Health Checks | ✅ |
| **Compliance Score** | **13/13** |

---

## 📄 License

MIT License - See [LICENSE](LICENSE) for details.

---

## 👥 Team

**AgentX Team** - AgentBeats Benchmark Competition 2026

---

**Platform**: AgentBeats  
**Protocol**: A2A v0.3.0  
**Tools**: 76 MCP-compatible endpoints  
**Tasks**: 103 evaluation scenarios  


# AgentX: A Comprehensive Benchmark for Evaluating Multi-Tool Agent Orchestration in Enterprise Productivity Workflows

## Abstract

AgentX is a rigorous evaluation benchmark designed to assess AI agents' capabilities in complex, multi-step enterprise productivity tasks. The benchmark comprises **103 curated evaluation scenarios** spanning five critical domains: **Research, Storage Management, Communication, Media Processing, and Productivity Automation**—with difficulty levels ranging from easy to hard.

The system implements the **A2A (Agent-to-Agent) Protocol v0.3.0**, enabling standardized communication between our evaluation infrastructure (Green Agent) and participating AI agents (Purple Agents). The Green Agent orchestrates the evaluation process by dispatching task requests, monitoring tool usage, and generating structured assessment artifacts.

### Key Technical Features

- **76 MCP-Compatible Tools**: Integration with Google Workspace (Drive, Docs, Sheets, Slides, Gmail), Notion API, YouTube transcription, and web search capabilities
- **3D Scoring Methodology**:
  - **Action Match (50%)**: Validates correct tool selection from required action sequences
  - **Argument Quality (40%)**: Evaluates parameter accuracy, data type compliance, and semantic correctness
  - **Efficiency Score (10%)**: Measures optimal step utilization against defined thresholds
- **Real-World Task Complexity**: Multi-tool workflows requiring research, document creation, cross-platform data integration, and automated communication

### Evaluation Protocol

Each evaluation task follows a structured protocol:
1. Green Agent delivers task specifications via A2A messaging
2. Purple Agent executes required tool calls through MCP endpoints
3. Tool interactions are captured and validated against success criteria
4. Weighted scoring produces a normalized performance metric

### Infrastructure

- **Containerized Deployment**: Docker-based architecture for reproducible evaluations
- **Artifact Generation**: Structured JSON reports with detailed scoring breakdowns
- **AgentBeats Compatibility**: Full 13/13 compliance score with the AgentBeats evaluation platform

### Sample Task Categories

| Domain | Example Task | Required Tools |
|--------|-------------|----------------|
| Research | Academic literature review with collaborative sharing | `google_search`, `createGoogleDoc`, `send_email` |
| Storage | Cross-platform document consolidation and organization | `search`, `getGoogleDocContent`, `createFolder`, `moveItem` |
| Communication | Stakeholder meeting preparation with automated outreach | `search_emails`, `read_email`, `createGoogleSlides`, `draft_email` |
| Media | YouTube content analysis with structured note-taking | `google_search`, `get_timed_transcript`, `createGoogleDoc` |

### Contribution

AgentX addresses the gap in standardized evaluation frameworks for tool-augmented AI agents operating in enterprise environments. By providing reproducible, scored assessments across realistic productivity scenarios, this benchmark enables objective comparison of agent architectures, prompting strategies, and tool-calling capabilities.

---