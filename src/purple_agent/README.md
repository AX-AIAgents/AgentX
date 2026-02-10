# 🟣 Advanced Purple Agent

AgentBeats ve AgentX ile uyumlu gelişmiş A2A agent modülü.

## Özellikler

- **Multi-Model**: GPT-4o, GPT-4o-mini desteği
- **Retry Logic**: Exponential backoff ile yeniden deneme
- **Parallel Tools**: Birden fazla tool'u aynı anda çalıştırma
- **Metrics**: Prometheus uyumlu metrikler
- **Health Checks**: /health ve /ready endpoint'leri

---

## 🚀 Hızlı Başlangıç

```bash
# Server başlat
uv run src/purple_agent/server.py --host 127.0.0.1 --port 9000

# Veya farklı model ile
MODEL=gpt-4o uv run src/purple_agent/server.py --port 9000
```

---

## 📊 Benchmark Yapma

### Adım 1: Green Agent'ı Başlat

```bash
# Terminal 1 - Green Agent (MCP tools sağlar, skorlama yapar)
cd /Users/huseyin/Documents/LLM/agentx
uv run src/server.py --port 8090
```

### Adım 2: Purple Agent'ı Başlat

```bash
# Terminal 2 - Purple Agent (task çözer)
uv run src/purple_agent/server.py --port 9000
```

### Adım 3: Benchmark Çalıştır

```bash
# Scenario ile benchmark
uv run agentbeats-run --scenario scenario.toml \
  --purple-agent http://localhost:9000

# Veya task file ile
python run.py --task-file tasks.jsonl \
  --external-agent http://localhost:9000
```

---

## 🔄 Benchmark Akışı

```
Green Agent (8090)          Purple Agent (9000)
      │                            │
      │──── Task Gönder ──────────▶│
      │                            │
      │                    Tool çağrısı yap
      │◀─── Tool Call ────────────│
      │                            │
      │     MCP üzerinden          │
      │     tool çalıştır          │
      │──── Tool Result ─────────▶│
      │                            │
      │◀─── Response ─────────────│
      │                            │
   Skorlama                        │
      │                            │
```

---

## 📋 Örnek Task

```json
{
  "task_id": "search_summarize",
  "instruction": "AI haberlerini ara ve Notion'a kaydet",
  "success_criteria": {
    "required_tools": ["brave_search", "notion_create_page"],
    "optimal_steps": 3,
    "max_steps": 10
  }
}
```

---

## 🐳 Docker ile Benchmark

```bash
# Build
docker build -f Dockerfile.purple_agent -t purple-agent:v2 .

# Çalıştır
docker run -p 9000:9000 \
  -e OPENAI_API_KEY=sk-xxx \
  -e MCP_ENDPOINT=http://host.docker.internal:8090/mcp \
  purple-agent:v2
```

---

## 📊 Skorlama Metrikleri

| Metrik | Açıklama |
|--------|----------|
| **Correctness** | Doğru tool'lar çağrıldı mı? |
| **Completeness** | Tüm adımlar tamamlandı mı? |
| **Efficiency** | `optimal_steps / actual_steps` |

---

## ⚙️ Environment Variables

| Variable | Default | Açıklama |
|----------|---------|----------|
| `OPENAI_API_KEY` | - | OpenAI API key |
| `MODEL` | gpt-4o-mini | Model seçimi |
| `TEMPERATURE` | 0.7 | Temperature |
| `MAX_RETRIES` | 3 | Retry sayısı |
| `MCP_ENDPOINT` | localhost:8090 | Green Agent MCP |

---

## 🔍 Endpoints

| Endpoint | Method | Açıklama |
|----------|--------|----------|
| `/.well-known/agent.json` | GET | Agent Card |
| `/` | POST | A2A JSON-RPC |
| `/health` | GET | Health check |
| `/metrics` | GET | Prometheus metrics |
| `/ready` | GET | Readiness probe |
