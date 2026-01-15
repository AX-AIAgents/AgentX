# AgentX Architecture & Flow Diagrams

## 1. Multi-API vs Cross-API: The Key Difference

### Traditional Multi-API Approach (Isolated)

```mermaid
flowchart LR
    subgraph "Task 1: Document"
        A1[Agent] --> B1[Google Docs API]
    end
    
    subgraph "Task 2: Email"
        A2[Agent] --> B2[Gmail API]
    end
    
    subgraph "Task 3: Search"
        A3[Agent] --> B3[Notion API]
    end
    
    style A1 fill:#f9f
    style A2 fill:#f9f
    style A3 fill:#f9f
```

**Problem**: Each task uses only ONE API. No data flows between systems.

---

### AgentX Cross-API Approach (Orchestrated)

```mermaid
flowchart TD
    subgraph "Single Task: Compile Q4 Report & Notify"
        Agent[🤖 AI Agent]
        
        Agent -->|1. Search projects| Notion[(Notion API)]
        Notion -->|page_ids| Agent
        
        Agent -->|2. Get documents| Drive[(Google Drive API)]
        Drive -->|doc_content| Agent
        
        Agent -->|3. Extract metrics| Sheets[(Google Sheets API)]
        Sheets -->|metrics_data| Agent
        
        Agent -->|4. Create summary| Docs[(Google Docs API)]
        Docs -->|doc_id| Agent
        
        Agent -->|5. Draft notification| Gmail[(Gmail API)]
    end
    
    style Agent fill:#9f9,stroke:#333,stroke-width:2px
    style Notion fill:#000,color:#fff
    style Drive fill:#4285f4,color:#fff
    style Sheets fill:#34a853,color:#fff
    style Docs fill:#4285f4,color:#fff
    style Gmail fill:#ea4335,color:#fff
```

**Solution**: Single task orchestrates 5 APIs. Outputs become inputs.

---

## 2. Evaluation Architecture

```mermaid
flowchart TB
    subgraph AgentBeats["AgentBeats Platform"]
        Client[AgentBeats Client]
    end
    
    subgraph GreenAgent["Green Agent (Evaluator)"]
        A2A[A2A Server :9009]
        MCP[MCP Server :8091]
        Tasks[(103 Tasks)]
        Scorer[3D Scorer]
    end
    
    subgraph PurpleAgent["Purple Agent (Participant)"]
        Agent[AI Agent]
        LLM[OpenAI GPT-4o-mini]
    end
    
    Client -->|"POST /rpc"| A2A
    A2A -->|task_config| Agent
    Agent -->|discover_tools| MCP
    MCP -->|76 tools| Agent
    Agent -->|tool_call| MCP
    MCP -->|result| Agent
    Agent -->|task_complete| A2A
    A2A -->|tool_trace| Scorer
    Scorer -->|3D_score| Client
    
    style Client fill:#ff9
    style A2A fill:#9f9
    style MCP fill:#9f9
    style Agent fill:#f9f
    style LLM fill:#f9f
```

---

## 3. 3D Scoring Pipeline

```mermaid
flowchart LR
    subgraph Input
        Trace[Tool Call Trace]
        Criteria[Success Criteria]
    end
    
    subgraph "Action Scoring (50%)"
        AS[Match required tools]
        AS --> ASR[matched / required]
    end
    
    subgraph "Argument Scoring (40%)"
        AG[Validate parameters]
        AG --> AGR[passed / total]
    end
    
    subgraph "Efficiency Scoring (10%)"
        EF[Count steps]
        EF --> EFR["1 - (actual-opt)/(max-opt)"]
    end
    
    subgraph Output
        Total["Total = 0.5×A + 0.4×Ar + 0.1×E"]
    end
    
    Trace --> AS
    Trace --> AG
    Trace --> EF
    Criteria --> AS
    Criteria --> AG
    Criteria --> EF
    ASR --> Total
    AGR --> Total
    EFR --> Total
    
    style Total fill:#9f9,stroke:#333,stroke-width:2px
```

---

## 4. Task Execution Flow

```mermaid
sequenceDiagram
    participant AB as AgentBeats
    participant GA as Green Agent
    participant PA as Purple Agent
    participant MCP as MCP Server
    
    AB->>GA: Start Assessment
    GA->>PA: Task Config (kickoff_message)
    
    PA->>MCP: GET /tools
    MCP-->>PA: 76 tool schemas
    
    loop Until task complete or max_turns
        PA->>PA: LLM decides tool call
        PA->>MCP: POST /tools/call
        MCP-->>PA: Tool result
        PA->>GA: Status update
    end
    
    PA->>GA: Task complete
    GA->>GA: Calculate 3D score
    GA-->>AB: Evaluation result
```

---

## 5. Cross-API Data Flow Example

```mermaid
flowchart TB
    subgraph Task["Task: Research competitor and prepare report"]
        Start([Start]) --> S1
        
        S1[🔍 google_search<br/>query: 'competitor analysis'] --> R1[URLs]
        R1 --> S2[📄 scrape<br/>url: result_url] --> R2[Content]
        R2 --> S3[📖 API-post-search<br/>query: 'competitor'] --> R3[Notion pages]
        R3 --> S4[📝 createGoogleDoc<br/>name: 'Report'] --> R4[doc_id]
        R4 --> S5[✉️ draft_email<br/>to: team@company.com<br/>body: doc_link] --> End([End])
    end
    
    style Start fill:#9f9
    style End fill:#f99
    style S1 fill:#4285f4,color:#fff
    style S2 fill:#4285f4,color:#fff
    style S3 fill:#000,color:#fff
    style S4 fill:#4285f4,color:#fff
    style S5 fill:#ea4335,color:#fff
```

---

## 6. API Coverage Map

```mermaid
mindmap
  root((76 MCP Tools))
    Notion API
      21 tools
      Search pages
      Create pages
      Append blocks
      Manage databases
    Google Drive
      18 tools
      Search files
      Create docs/sheets/slides
      Move/copy items
      Share permissions
    Gmail
      12 tools
      Search emails
      Read messages
      Draft emails
      Send emails
    YouTube
      3 tools
      Get transcript
      Get video info
      Timed transcript
    Web Search
      2 tools
      Google search
      URL scraping
```

---

## 7. Benchmark Statistics

| Metric | Value |
|--------|-------|
| Total Tasks | 103 |
| Total Tools | 76 |
| API Providers | 5 |
| Avg APIs per Task | 3.2 |
| Difficulty Levels | Easy / Medium / Hard |
| Domains | Research, Storage, Communication, Media, Productivity |
