# AgentX: Cross-API Orchestration Benchmark for Multi-Tool AI Agents

## Abstract

Modern AI agents struggle with **Cross-API orchestration**—the ability to seamlessly chain operations across multiple heterogeneous service providers to complete complex enterprise workflows. While existing benchmarks focus on single-API tool calling, real-world productivity tasks require agents to coordinate between Google Workspace, Notion, email systems, and web services simultaneously.

**AgentX** addresses this gap by introducing a comprehensive evaluation framework with **103 cross-API scenarios** spanning five enterprise domains. Our benchmark uniquely measures agents' ability to:

1. **Select appropriate tools** across 76 MCP-compatible endpoints from 5 different API providers
2. **Pass correct parameters** with proper data types and semantic accuracy
3. **Execute efficiently** within optimal step bounds

## The Cross-API Problem

### Current Multi-API Approaches: Isolated Tool Calling

Existing benchmarks evaluate agents on **isolated tool calling**—each task uses tools from a single API provider:

```
Task: "Create a document"
└── Google Docs API → createDocument()

Task: "Send an email"  
└── Gmail API → sendEmail()
```

**Problem**: Real enterprise workflows don't work this way. A typical productivity task requires data to flow between multiple systems.

### Cross-API Orchestration: Data Flow Across Providers

AgentX evaluates **cross-API orchestration**—where outputs from one API become inputs to another:

```
Task: "Compile project updates and notify stakeholders"

Step 1: Notion API → Search project pages
Step 2: Google Drive → Get document content  
Step 3: Google Sheets → Extract metrics data
Step 4: Google Docs → Create summary document
Step 5: Gmail → Draft notification email
```

**Challenge**: The agent must:
- Understand API-specific data schemas
- Transform IDs and formats between providers
- Maintain context across multiple tool calls
- Handle partial failures gracefully

## Benchmark Design

### Inputs

| Component | Description |
|-----------|-------------|
| **Kickoff Message** | Natural language task description |
| **Initial State** | Pre-populated data in simulated APIs |
| **Tool Schemas** | 76 OpenAPI-compatible tool definitions |
| **Success Criteria** | Required actions + argument constraints |

### Outputs

| Component | Description |
|-----------|-------------|
| **Tool Call Trace** | Ordered list of (tool, arguments, result) |
| **Final State** | Post-execution state of all APIs |
| **3D Score Vector** | (action_score, argument_score, efficiency_score) |
| **Weighted Total** | 0.5×action + 0.4×argument + 0.1×efficiency |

### Task Distribution

| Domain | Tasks | Cross-API Complexity |
|--------|-------|---------------------|
| Research | 21 | 3-5 APIs per task |
| Storage | 25 | 2-4 APIs per task |
| Communication | 20 | 2-3 APIs per task |
| Media | 18 | 2-4 APIs per task |
| Productivity | 19 | 3-5 APIs per task |
| **Total** | **103** | **Avg: 3.2 APIs/task** |

## Performance Metrics

### 3D Scoring Methodology

| Dimension | Weight | Metric | Formula |
|-----------|--------|--------|---------|
| **Action Match** | 50% | Tool selection accuracy | `matched / required` |
| **Argument Quality** | 40% | Parameter correctness | `passed_checks / total_checks` |
| **Efficiency** | 10% | Step optimization | `max(0, 1 - (actual - optimal) / (max - optimal))` |

### Evaluation Operators

| Operator | Validation |
|----------|------------|
| `exists` | Argument is present |
| `not_empty` | Non-null, non-empty value |
| `is_email` | Valid email format |
| `contains_http` | Valid URL |
| `equals` | Exact value match |
| `contains` | Substring match |

## Key Contributions

1. **First Cross-API Benchmark**: Unlike single-API benchmarks, AgentX evaluates multi-provider orchestration
2. **Real Enterprise Scenarios**: 103 tasks derived from actual productivity workflows
3. **Reproducible Evaluation**: Containerized mock mode enables deterministic testing
4. **Fine-Grained Scoring**: 3D metrics provide actionable insights beyond pass/fail

## Citation

```bibtex
@misc{agentx2026,
  title={AgentX: Cross-API Orchestration Benchmark for Multi-Tool AI Agents},
  author={AX-Artificial Intelligence Team},
  year={2026},
  url={https://github.com/AX-Artificial-Intelligence/AgentX}
}
```
