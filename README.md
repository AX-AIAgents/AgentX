# AgentX - Green Agent (Assessor)

**AgentBeats Competition Entry**

A2A protocol-based agent evaluation system with 3D scoring:
- **Action Match (40%)**: Correct tool selection
- **Argument Match (50%)**: Correct parameters
- **Efficiency (10%)**: Step optimization

## Components

- **Green Agent**: Evaluator/Assessor (port 8090)
- **MCP Server**: 76 tools across Notion, Gmail, Google Drive, YouTube, Search (port 8091)

## Quick Start

```bash
# Local development
./run_local.sh

# With AgentBeats Controller
agentbeats run_ctrl
```

## Docker

```bash
docker build -t artificax/green-agent:v1 .
docker run -p 8090:8090 -p 8091:8091 artificax/green-agent:v1
```

## Endpoints

- `GET /health` - Health check
- `POST /reset` - Reset state
- `GET /.well-known/agent-card.json` - A2A Agent Card