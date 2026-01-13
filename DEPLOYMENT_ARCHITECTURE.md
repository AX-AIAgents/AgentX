# AgentX Deployment Architecture

## 🏗️ Sistem Mimarisi

### 1. Green Agent Container (Cloud Run / Render)

```
┌─────────────────────────────────────────────────────┐
│  Green Agent Container                              │
│  Public URL: https://green-agent.run.app            │
│                                                     │
│  ┌─────────────────────────────────────┐           │
│  │ MCP Server (Internal Port 8091)     │           │
│  │ - 76 tools (Notion, Gmail, etc.)    │           │
│  │ - Runs in background                │           │
│  └──────────────┬──────────────────────┘           │
│                 │ (localhost:8091)                  │
│                 ↓                                   │
│  ┌─────────────────────────────────────┐           │
│  │ Green Agent (Port 8090)             │           │
│  │ - A2A Server                        │           │
│  │ - Evaluator                         │           │
│  │ - MCP Proxy: /mcp/*                 │ ←─────────┼─── Purple Agent
│  │   ↳ Forwards to localhost:8091      │           │    MCP requests
│  └─────────────────────────────────────┘           │
│                 ↑                                   │
└─────────────────┼───────────────────────────────────┘
                  │
         (Public HTTPS)
                  │
          ┌───────┴────────┐
          │  AgentBeats    │
          │  Platform      │
          └────────────────┘
```

### 2. Purple Agent Container (Render)

```
┌─────────────────────────────────────────────────────┐
│  Purple Agent Container                             │
│  Public URL: https://agentx-purple.onrender.com     │
│                                                     │
│  ┌─────────────────────────────────────┐           │
│  │ Purple Agent (Port 9000)            │           │
│  │ - OpenAI GPT-4o-mini                │           │
│  │ - A2A Client                        │           │
│  │ - MCP_ENDPOINT config               │           │
│  └─────────────────────────────────────┘           │
│                                                     │
└─────────────────────────────────────────────────────┘
```

## 🔌 Port ve Endpoint Konfigürasyonu

### Green Agent (Production)

**Dockerfile expose:**
```dockerfile
EXPOSE 8090 8091
```

**Ancak Cloud Run/Render sadece 1 port'a izin verir!**

**Çözüm**: MCP'yi Green Agent üzerinden proxy et:

| Endpoint | Internal | External (Public) |
|----------|----------|-------------------|
| A2A Server | localhost:8090 | https://green-agent.run.app/ |
| MCP Direct | localhost:8091 | ❌ Erişilemez |
| MCP Proxy | localhost:8091 | https://green-agent.run.app/mcp/* |

### Purple Agent Environment Variables

```bash
# Render Dashboard > agentx-purple > Environment

OPENAI_API_KEY=sk-proj-...
MCP_ENDPOINT=https://green-agent.run.app/mcp
PORT=10000
RENDER=true
```

## 📡 MCP Proxy Nasıl Çalışır?

### Purple Agent → Green Agent → MCP Server

```
1. Purple Agent: GET https://green-agent.run.app/mcp/tools
                    ↓
2. Green Agent:   GET http://localhost:8091/tools
                    ↓
3. MCP Server:    Return tools list
                    ↓
4. Green Agent:   Proxy response back
                    ↓
5. Purple Agent:  Receive tools list
```

### Kod İmplementasyonu

**Green Agent (`src/a2a_server.py`):**
```python
async def mcp_proxy(request: Request) -> JSONResponse:
    """Forward MCP requests to internal MCP server."""
    path = request.path_params.get("path", "")
    mcp_url = f"http://localhost:{MCP_PORT}/{path}"
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        if request.method == "GET":
            response = await client.get(mcp_url, params=request.query_params)
        elif request.method == "POST":
            body = await request.body()
            response = await client.post(mcp_url, content=body)
        
        return JSONResponse(response.json(), status_code=response.status_code)

# Route registration
app.add_route("/mcp/{path:path}", mcp_proxy, methods=["GET", "POST"])
```

**Purple Agent (`src/agents/external_agent.py`):**
```python
# MCP endpoint from environment
mcp_endpoint = os.getenv("MCP_ENDPOINT", "http://localhost:8091")

async def fetch_tools_from_mcp():
    async with httpx.AsyncClient(timeout=5.0) as http:
        # This will call Green Agent's /mcp/tools endpoint
        response = await http.get(f"{mcp_endpoint}/tools")
        return response.json().get("tools", [])
```

## 🚀 Deployment Checklist

### Green Agent (Cloud Run)

- [ ] Build Docker image: `docker build -t green-agent:v1 -f Dockerfile .`
- [ ] Push to GHCR: `docker push ghcr.io/ax-aiagents/green-agent:v1`
- [ ] Deploy to Cloud Run: `gcloud run deploy green-agent --image=...`
- [ ] Get public URL: `https://green-agent-xxxxx.run.app`
- [ ] Test health: `curl https://green-agent-xxxxx.run.app/health`
- [ ] Test MCP proxy: `curl https://green-agent-xxxxx.run.app/mcp/tools`

### Purple Agent (Render)

- [x] Build Docker image: `docker build -t purple-agent:v1 -f Dockerfile.purple .`
- [x] Deploy to Render: ✅ Done
- [x] Public URL: `https://agentx-purple.onrender.com`
- [ ] Set env vars:
  - [ ] `OPENAI_API_KEY=sk-proj-...`
  - [ ] `MCP_ENDPOINT=https://green-agent-xxxxx.run.app/mcp`
  - [ ] `RENDER=true`
- [ ] Test: `curl https://agentx-purple.onrender.com/health`

### AgentBeats Registration

- [ ] Register Green Agent: https://agentbeats.org/register
  - Controller URL: `https://green-agent-xxxxx.run.app`
- [ ] Register Purple Agent: https://agentbeats.org/register
  - Controller URL: `https://agentx-purple.onrender.com`
- [ ] Upload scenario.toml
- [ ] Link GitHub results repo

## 🔍 Testing

### Local Test (2 containers)

```bash
# Terminal 1: Green Agent
docker run -p 8090:8090 green-agent:v1

# Terminal 2: Purple Agent (pointing to Green)
docker run -p 9000:9000 \
  -e OPENAI_API_KEY=sk-... \
  -e MCP_ENDPOINT=http://host.docker.internal:8090/mcp \
  purple-agent:v1

# Terminal 3: Test
curl -X POST http://localhost:9000/a2a/message \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"message/send","id":"1","params":{"message":{"role":"user","parts":[{"type":"text","text":"Hello"}]}}}'
```

### Production Test (Cloud)

```bash
# Test Green Agent health
curl https://green-agent-xxxxx.run.app/health

# Test MCP proxy
curl https://green-agent-xxxxx.run.app/mcp/tools

# Test Purple Agent
curl https://agentx-purple.onrender.com/health
curl https://agentx-purple.onrender.com/debug/env
```

## ⚠️ Önemli Notlar

1. **Single Port Limitation**: Cloud Run ve Render sadece 1 porta izin verir, bu yüzden MCP proxy gerekli
2. **HTTPS Gerekli**: AgentBeats platformu HTTP'ye izin vermez
3. **Environment Variables**: Her serviste doğru env var'lar olmalı
4. **Cold Start**: İlk istek 30-60 saniye sürebilir (free tier)
5. **Logs**: Deploy sonrası logları mutlaka kontrol et

## 🎯 Sonraki Adımlar

1. Green Agent'ı Cloud Run'a deploy et
2. Purple Agent'ta `MCP_ENDPOINT`'i güncelle (Green Agent URL'i)
3. Her ikisini de test et
4. AgentBeats platformuna kaydet
5. Demo video çek
6. Abstract yaz
7. 15 Ocak'ta teslim et! 🚀
