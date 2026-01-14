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
