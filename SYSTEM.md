# AgentX - A2A Agent Evaluation System

## 📋 Genel Bakış

AgentX, AI agent'larını **Agent-to-Agent (A2A)** protokolü ile test eden bir evaluation framework'üdür. OpenAI GPT-4o-mini gibi LLM'leri kullanarak, karmaşık görevleri MCP (Model Context Protocol) toolları ile yerine getiren agent'ların performansını ölçer.

### Temel Özellikler

- ✅ **A2A Protocol**: JSON-RPC 2.0 tabanlı agent iletişimi
- ✅ **MCP Tool Integration**: Notion, Gmail, Google Drive, YouTube, Search toolları
- ✅ **Multi-turn Conversations**: Agent'lar iteratif olarak tool çağrıları yapabilir
- ✅ **3D Scoring**: Action Match, Argument Quality, Efficiency
- ✅ **OpenAI Integration**: GPT-4o-mini ile function calling
- ✅ **Dynamic Tool Discovery**: 76 tool otomatik keşfedilir

---

## 🏗️ Sistem Mimarisi

```
┌─────────────────────────────────────────────────────────────┐
│                         run.py                               │
│                    (Orchestrator)                            │
└─────────────────────────────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Green Agent  │◄──►│ Purple Agent │◄──►│  MCP Server  │
│   (8090)     │    │   (9000)     │    │   (8091)     │
└──────────────┘    └──────────────┘    └──────────────┘
   Evaluator          External Agent      Tool Provider
```

### Bileşenler

#### 1. **run.py** - Ana Orchestrator
- Tüm servisleri başlatır
- Task'ları yükler ve Green Agent'a gönderir
- Sonuçları toplar ve raporlar

#### 2. **Green Agent** (Evaluator) - Port 8090
- A2A server olarak çalışır
- Purple Agent'ı test eder
- Tool çağrılarını MCP üzerinden execute eder
- Scoring yapar (Action, Argument, Efficiency)

**Dosyalar:**
- `src/green_agent_executor.py`: A2A message handler
- `src/green_agent_orchestrator.py`: Evaluation loop ve Purple Agent client

#### 3. **Purple Agent** (Test Edilen Agent) - Port 9000
- OpenAI GPT-4o-mini kullanır
- A2A protokolü ile iletişim kurar
- MCP toollarını keşfeder ve kullanır
- Multi-turn conversation yapabilir

**Dosya:**
- `src/agents/external_agent.py`: OpenAI-powered A2A agent

#### 4. **MCP Server** (Tool Provider) - Port 8091
- 76 tool sunar (Notion, Gmail, Google Drive, YouTube, Search)
- HTTP REST API ile erişilebilir
- Tool schema'ları OpenAI format'ında döner

**Dosya:**
- `src/mcp_http_server.py`: MCP HTTP wrapper

---

## 🔄 İşleyiş Akışı

### Başlangıç Sequence

```
1. run.py başlatılır
   └─> Green Agent subprocess başlar (8090)
   └─> MCP Server subprocess başlar (8091)
   └─> Purple Agent harici olarak çalışır (9000)

2. run.py kickoff mesajı gönderir
   └─> Green Agent'a (8090)
       └─> Green Agent task config'i parse eder
           └─> Purple Agent'a (9000) task instruction gönderir
```

### Evaluation Loop

```
┌─────────────────────────────────────────────────────────┐
│  Green Agent                                            │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 1. Send task instruction to Purple Agent       │   │
│  └─────────────────────────────────────────────────┘   │
│           │                                             │
│           ▼                                             │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 2. Receive response from Purple Agent          │   │
│  │    - Check for tool_calls                       │   │
│  │    - Check for completion signal                │   │
│  └─────────────────────────────────────────────────┘   │
│           │                                             │
│           ▼                                             │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 3. If tool_calls exist:                         │   │
│  │    - Execute each tool via MCP (8091)           │   │
│  │    - Record tool calls for scoring              │   │
│  │    - Send results back to Purple Agent          │   │
│  │    - LOOP back to step 2                        │   │
│  └─────────────────────────────────────────────────┘   │
│           │                                             │
│           ▼                                             │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 4. If no tool_calls:                            │   │
│  │    - End evaluation                              │   │
│  │    - Calculate score                             │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### Purple Agent (OpenAI) Workflow

```
┌─────────────────────────────────────────────────────────┐
│  Purple Agent (OpenAI GPT-4o-mini)                      │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 1. Receive task from Green Agent               │   │
│  │    - Parse task instruction                     │   │
│  │    - Add to conversation_history                │   │
│  └─────────────────────────────────────────────────┘   │
│           │                                             │
│           ▼                                             │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 2. Fetch tools from MCP (8091)                  │   │
│  │    - GET /tools → 76 tools                      │   │
│  │    - Convert to OpenAI function format          │   │
│  └─────────────────────────────────────────────────┘   │
│           │                                             │
│           ▼                                             │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 3. Build OpenAI messages                        │   │
│  │    - system: workflow instructions              │   │
│  │    - user: task instruction                     │   │
│  │    - assistant: previous tool_calls             │   │
│  │    - tool: tool results                         │   │
│  └─────────────────────────────────────────────────┘   │
│           │                                             │
│           ▼                                             │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 4. Call OpenAI API                              │   │
│  │    - model: gpt-4o-mini                         │   │
│  │    - tools: 76 MCP tools                        │   │
│  │    - tool_choice: auto                          │   │
│  └─────────────────────────────────────────────────┘   │
│           │                                             │
│           ▼                                             │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 5. Process response                             │   │
│  │    - If tool_calls: return A2A tool_call msg    │   │
│  │    - If text: check for completion signal       │   │
│  │    - Save assistant message to history          │   │
│  └─────────────────────────────────────────────────┘   │
│           │                                             │
│           ▼                                             │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 6. Receive tool results from Green Agent        │   │
│  │    - Add to conversation_history                │   │
│  │    - LOOP back to step 3                        │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## 📡 A2A Protocol

### Message Format

```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "id": "msg-123",
  "params": {
    "message": {
      "role": "user",
      "parts": [
        {"type": "text", "text": "Task instruction..."},
        {"type": "tool_call", "id": "tc-1", "name": "search", "arguments": {...}},
        {"type": "tool_result", "toolCallId": "tc-1", "result": {...}}
      ]
    }
  }
}
```

### Response Format

```json
{
  "jsonrpc": "2.0",
  "id": "msg-123",
  "result": {
    "message": {
      "role": "assistant",
      "parts": [
        {"type": "text", "text": "I'll search for..."},
        {"type": "tool_call", "id": "tc-1", "name": "search", "arguments": {...}}
      ]
    }
  }
}
```

### Agent Discovery

Purple Agent, `/.well-known/agent.json` endpoint'i ile keşfedilebilir:

```json
{
  "name": "OpenAI GPT-4o-mini Agent",
  "description": "An A2A-compatible agent powered by OpenAI",
  "url": "http://localhost:9000/",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false
  },
  "skills": [
    {
      "id": "task_execution",
      "name": "Execute Productivity Tasks",
      "tags": ["productivity", "search", "documents"]
    }
  ]
}
```

---

## 🔧 MCP Tool Integration

### Tool Discovery

```bash
# MCP'den toolları al
curl http://localhost:8091/tools

# Response (76 tools):
{
  "tools": [
    {
      "name": "search",
      "description": "Search for files in Google Drive",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "pageSize": {"type": "number"}
        }
      }
    },
    ...
  ]
}
```

### Tool Execution

```bash
# Tool çağrısı yap
curl -X POST http://localhost:8091/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "search",
    "arguments": {"query": "project reports", "pageSize": 10}
  }'

# Response:
{
  "result": {
    "files": [...],
    "nextPageToken": "..."
  }
}
```

### Available Tools

**Google Drive (16 tools)**
- search, listFolder, getFileContent, createTextFile, updateTextFile, deleteFile, etc.

**Gmail (12 tools)**
- list_emails, search_emails, get_email, draft_email, send_email, etc.

**Notion (24 tools)**
- API-post-search, API-get-page, API-patch-block-children, etc.

**YouTube (4 tools)**
- get_transcript, search_videos, etc.

**Search (20 tools)**
- google_search, bing_search, wikipedia_search, etc.

---

## 🎯 Conversation History Management

### Kritik Özellikler

#### 1. **Task Reset**
Her yeni task başlangıcında `<task_config>` tespit edilince conversation_history temizlenir:

```python
if "<task_config>" in text:
    print("🔄 New task detected - resetting conversation history")
    conversation_history.clear()
```

#### 2. **Tool Call ID Matching**
OpenAI'ın beklediği format:
- Assistant message: `tool_calls` array with unique IDs
- Tool results: `tool_call_id` must match assistant's tool_call ID

```python
# Save tool_call IDs from assistant
last_tool_call_ids = [tc["id"] for tc in assistant_msg["tool_calls"]]

# Match when adding tool results
tool_call_id = last_tool_call_ids[idx]
messages.append({
    "role": "tool",
    "tool_call_id": tool_call_id,
    "content": json.dumps(result)
})
```

#### 3. **Message Sequence**
OpenAI beklenen sıralama:
```
system → user → assistant (tool_calls) → tool → assistant → tool → ...
```

### Conversation History Structure

```python
conversation_history = [
    {
        "role": "user",
        "content": "Task: Search and create doc...",
        "tool_results": []
    },
    {
        "assistant_message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {
                        "name": "search",
                        "arguments": "{\"query\":\"...\"}"
                    }
                }
            ]
        }
    },
    {
        "tool_results": [
            {
                "id": "call_abc123",
                "result": {"files": [...]}
            }
        ]
    }
]
```

---

## 📊 Scoring System

### 3D Scoring

**1. Action Match (50% weight)**
```python
matched = set(called_tools) ∩ set(required_tools)
score = len(matched) / len(required_tools)
```

**2. Argument Quality (40% weight)**
- Tool parametrelerinin doğruluğu
- Required vs optional parametreler
- Değer validasyonu

**3. Efficiency (10% weight)**
```python
if actual_steps <= optimal_steps:
    score = 1.0
elif actual_steps <= max_steps:
    score = (max_steps - actual_steps) / (max_steps - optimal_steps)
else:
    score = 0.0
```

### Final Score

```python
total_score = (
    action_score * 0.5 +
    argument_score * 0.4 +
    efficiency_score * 0.1
)
```

---

## 🚀 Kullanım

### Hızlı Başlangıç

```bash
# 1. Purple Agent'ı başlat (terminal 1)
cd agentx
source .venv/bin/activate
python -m src.agents.external_agent

# 2. Evaluation çalıştır (terminal 2)
cd agentx
source .venv/bin/activate
python run.py \
  --task-file /path/to/task_definitions.jsonl \
  --external-agent http://localhost:9000 \
  --task 0 \
  --max-turns 10
```

### Komut Satırı Parametreleri

```
--task-file TASK_FILE          Task definitions JSONL dosyası
--external-agent EXTERNAL_AGENT Purple Agent URL (http://localhost:9000)
--task TASK                     Tek bir task çalıştır (index)
--tasks TASKS                   Task range (örn: 0-5)
--max-turns MAX_TURNS           Maximum turn sayısı (default: 30)
--config CONFIG                 Config dosyası (default: scenario.toml)
--servers-only                  Sadece servisleri başlat
--no-servers                    Servisleri başlatma
```

### Task Definition Format

```json
{
  "task_id": "AX-STOR-393d59",
  "domain": "storage",
  "instruction": "Search for project reports in Google Drive, read the Q3 sheet...",
  "expected_actions": [
    {
      "tool": "search",
      "arguments": {
        "query": "project reports",
        "pageSize": 50
      },
      "required_args": ["query"]
    },
    {
      "tool": "getGoogleSheetContent",
      "arguments": {
        "spreadsheetId": "...",
        "range": "Q3"
      },
      "required_args": ["spreadsheetId", "range"]
    }
  ]
}
```

---

## 🐛 Debugging

### Log Seviyeleri

**Purple Agent Logs:**
```
📨 Incoming message - role: user, has_text: True, has_tool_results: False
📦 Fetched 76 tools from MCP
📚 Building messages from 3 history entries
🤖 Calling OpenAI with 76 tools, 4 messages
   Last message roles: ['user', 'assistant', 'tool']
   ✅ OpenAI response received
   Response: tool_calls=True, content=None...
   🔧 Tool call: search
   📋 Arguments: {"query": "..."}
```

**Green Agent Logs:**
```
🔄 Turn 1/10
   💜 Purple: I'll search for project reports...
   🔧 Purple calls: search
   🔧 Executing: search
```

### Yaygın Hatalar

**1. Tool Call ID Mismatch**
```
BadRequestError: 'tool_call_id' of 'tc-2' not found in 'tool_calls'
```
**Çözüm:** Tool call ID'leri conversation history'de doğru eşleştirildi (fixed).

**2. Empty Arguments**
```
📋 Arguments: {}
```
**Sebep:** MCP tool schema'sında `required: []` boş. OpenAI parametreleri optional görüyor.

**3. Premature Completion**
```
🏁 Completion signal detected in content: I've finished...
```
**Sebep:** Purple Agent'ın response'unda "finished", "task complete" gibi kelimeler var.

---

## 📈 Performans Metrikleri

### Başarı Oranları (Mevcut Durum)

- **Skor:** 24% (17%'den iyileşti)
- **Action Match:** 14.29% (1/7 tool matched → çeşitli toollar çağrıldı)
- **Argument Quality:** 0% (boş arguments sorunu devam ediyor)
- **Efficiency:** 100% (optimal step sayısı içinde)

### İyileştirme Alanları

1. **Argument Quality:**
   - System prompt'a parametre örnekleri ekle
   - MCP tool schema'larını iyileştir
   - Few-shot examples ekle

2. **Action Match:**
   - Task instruction'ı daha spesifik yap
   - Required toolları açıkça belirt
   - Tool seçim stratejisini iyileştir

3. **Multi-turn Stability:**
   - Max turns arttırılabilir (şu an 10)
   - Duplicate tool pattern detection var
   - Infinite loop protection aktif

---

## 🔐 Güvenlik ve Yapılandırma

### Environment Variables

```bash
# .env dosyası
OPENAI_API_KEY=sk-...
MCP_PORT=8091
MCP_SERVERS=notion,gmail,search,youtube,google-drive
GOOGLE_CREDENTIALS_PATH=/path/to/credentials.json
NOTION_TOKEN=secret_...
```

### Port Yapılandırması

```toml
# scenario.toml
[server]
a2a_port = 8090      # Green Agent
mcp_port = 8091      # MCP Server
# Purple Agent: 9000 (hardcoded in external_agent.py)
```

---

## 📚 Referanslar

- **A2A Protocol:** Agent-to-Agent JSON-RPC 2.0
- **MCP (Model Context Protocol):** Tool standardization framework
- **OpenAI Function Calling:** GPT-4 tool use capability
- **AgentX Original:** Tau-Benchmark tabanlı evaluation (legacy)

---

## 🎉 Özet

AgentX sistemi, OpenAI GPT-4o-mini kullanarak **multi-turn conversation** ve **tool calling** yapabilen bir AI agent'ı test eder. 

**Başarılar:**
- ✅ A2A protokol implementasyonu
- ✅ OpenAI conversation history yönetimi
- ✅ Tool call ID matching
- ✅ Multi-turn execution (7+ tool calls)
- ✅ Task reset ve conversation cleanup
- ✅ 76 MCP tool integration

**Devam Eden Çalışmalar:**
- 🔄 Argument quality iyileştirmesi
- 🔄 System prompt optimization
- 🔄 Tool selection strategy

**Mimari Güçlü Yanlar:**
- Modüler tasarım (Green/Purple/MCP ayrımı)
- Protocol-based communication
- Extensible scoring system
- Debug-friendly logging

---

**Son Güncelleme:** 13 Ocak 2026  
**Versiyon:** 1.0 (Post-OpenAI Integration)  
**Durum:** Production Ready ✅
