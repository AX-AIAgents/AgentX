# AgentX - Competition Ready Yol Haritası

## 📋 GENEL BAKIŞ

Bu döküman, AgentX sistemini **Competition Ready** (Yarışmaya Hazır) hale getirmek için gerekli tüm adımları içerir.

**Mevcut Durum:** Production Ready (Teknik olarak çalışıyor)  
**Hedef Durum:** Competition Ready (Yarışma gereksinimlerini karşılıyor)

---

## ✅ ŞU AN HAZIR OLANLAR

- [x] Multi-turn conversation
- [x] MCP integration (76 tools)
- [x] OpenAI GPT-4o-mini agent
- [x] A2A protocol implementation
- [x] 3D Scoring system
- [x] Conversation history management
- [x] Tool call ID matching
- [x] Task reset mechanism

**Mevcut Skor:** 24% (Action: 14%, Args: 0%, Efficiency: 100%)

---

## 🔴 KRİTİK EKSİKLER

### Must-Have (Zorunlu)
- [x] AgentBeats Controller entegrasyonu ✅
- [x] Docker containerization ✅
- [ ] HTTPS deployment (Cloud Run)
- [ ] Platform registration
- [ ] Demo video (3 dakika)
- [ ] Abstract (300 kelime)

### Should-Have (Olması İyi)
- [ ] Argument quality iyileştirmesi
- [ ] System prompt optimization
- [ ] Few-shot examples

---

## 📊 PHASE ÖZET TABLOSU

| Phase | Süre | Öncelik | Durum |
|-------|------|---------|-------|
| Phase 1: AgentBeats Controller | 2-3 saat | 🔥 YÜKSEK | ✅ TAMAMLANDI |
| Phase 2: Dockerization | 3-4 saat | 🔥 YÜKSEK | ✅ TAMAMLANDI |
| Phase 3: Cloud Deployment | 2-3 saat | 🟡 ORTA | 🟡 SIRADA |
| Phase 4: Argument Quality | 2-3 saat | 🟡 ORTA | ⚪ BEKLIYOR |
| Phase 5: Demo & Docs | 3-4 saat | 🟢 DÜŞÜK | ⚪ BEKLIYOR |
| Phase 6: Platform Registration | 1-2 saat | 🔥 YÜKSEK | ⚪ BEKLIYOR |

**Toplam Tahmini Süre:** 13-19 saat (Phase 1-2 tamamlandı: ~4 saat)

---

## 📦 PHASE 1: AGENTBEATS CONTROLLER ENTEGRASYONU

**Süre:** 2-3 saat  
**Öncelik:** 🔥 YÜKSEK  
**Durum:** 🟡 BAŞLANIYOR

### Gereksinimler

AgentBeats platformunun ajanı yönetebilmesi için:
- Controller kurulumu
- `run.sh` script'i
- `/reset` endpoint'i
- `/health` endpoint'i

### Adım 1.1: AgentBeats CLI Kurulumu

```bash
# AgentBeats paketini kur (PyPI'dan)
pip install earthshaker

# Kurulumu doğrula
agentbeats --version
```

**Not:** Paket adı `earthshaker`, komut adı `agentbeats`

### Adım 1.2: run.sh Script'i Oluştur

**Dosya:** `/Users/huseyin/Documents/LLM/agentx/run.sh`

```bash
#!/bin/bash
#
# AgentX Runner Script
# ====================
# Bu script AgentBeats platformunun ajanı yönetmesini sağlar.
# Controller, ajanın durumunu izler, restart eder ve reset komutlarını yönetir.

set -e  # Exit on error

# Environment variables
export A2A_PORT=${A2A_PORT:-8090}
export MCP_PORT=${MCP_PORT:-8091}
export PURPLE_AGENT_PORT=${PURPLE_AGENT_PORT:-9000}
export PYTHONPATH="$(pwd):$PYTHONPATH"

echo "🚀 Starting AgentX..."
echo "   A2A Port: $A2A_PORT"
echo "   MCP Port: $MCP_PORT"
echo "   Purple Agent Port: $PURPLE_AGENT_PORT"

# Activate virtual environment if exists
if [ -d ".venv" ]; then
    echo "📦 Activating virtual environment..."
    source .venv/bin/activate
fi

# Start Purple Agent in background (external agent)
echo "🟣 Starting Purple Agent..."
python -m src.agents.external_agent &
PURPLE_PID=$!
sleep 3

# Start MCP Server in background
echo "🔧 Starting MCP Server..."
python src/mcp_http_server.py &
MCP_PID=$!
sleep 2

# Start Green Agent (A2A Server)
echo "🟢 Starting Green Agent..."
python src/a2a_server.py &
GREEN_PID=$!
sleep 3

# Wait for all processes
echo "✅ All services started"
echo "   Green Agent PID: $GREEN_PID"
echo "   MCP Server PID: $MCP_PID"
echo "   Purple Agent PID: $PURPLE_PID"

# Keep running
wait $GREEN_PID
```

**İzin ver:**
```bash
chmod +x run.sh
```

### Adım 1.3: Green Agent'a Reset/Health Endpoints Ekle

**Dosya:** `src/a2a_server.py`

Var olan koda eklenecek:

```python
# Global state for evaluation
evaluation_state = {
    "active_tasks": {},
    "conversation_history": [],
    "last_reset": None
}

@app.post("/reset")
async def reset_agent():
    """
    Reset agent state for clean evaluation.
    
    AgentBeats platformu her test öncesi bu endpoint'i çağırır.
    Agent'ın tüm state'ini temizleyip başlangıç durumuna döndürür.
    """
    global evaluation_state
    
    # Clear all state
    evaluation_state = {
        "active_tasks": {},
        "conversation_history": [],
        "last_reset": datetime.now().isoformat()
    }
    
    print(f"♻️ Agent reset at {evaluation_state['last_reset']}")
    
    return {
        "jsonrpc": "2.0",
        "result": {
            "status": "reset",
            "message": "Agent state cleared successfully",
            "timestamp": evaluation_state['last_reset']
        }
    }


@app.get("/health")
async def health_check():
    """
    Health check endpoint for AgentBeats platform.
    
    Platform bu endpoint'i kullanarak agent'ın hazır olup olmadığını kontrol eder.
    """
    # Check if Purple Agent is reachable
    purple_healthy = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get("http://localhost:9000/health")
            purple_healthy = response.status_code == 200
    except:
        pass
    
    # Check if MCP is reachable
    mcp_healthy = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get("http://localhost:8091/tools")
            mcp_healthy = response.status_code == 200
    except:
        pass
    
    status = "healthy" if (purple_healthy and mcp_healthy) else "degraded"
    
    return {
        "status": status,
        "agent": "agentx-green-agent",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "capabilities": [
            "a2a",
            "mcp",
            "multi-turn",
            "3d-scoring"
        ],
        "components": {
            "green_agent": "healthy",
            "purple_agent": "healthy" if purple_healthy else "unhealthy",
            "mcp_server": "healthy" if mcp_healthy else "unhealthy"
        }
    }
```

### Adım 1.4: Purple Agent Reset (Zaten Var)

**Dosya:** `src/agents/external_agent.py`

```python
@app.post("/reset")
def reset():
    """Reset conversation state."""
    global conversation_history, available_tools
    conversation_history = []
    available_tools = []
    return {
        "status": "reset",
        "message": "Purple Agent conversation cleared",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
def health():
    """Health check for Purple Agent."""
    return {
        "status": "ok",
        "agent": "openai_gpt4o_mini_agent",
        "model": "gpt-4o-mini",
        "tools_loaded": len(available_tools)
    }
```

### Adım 1.5: Controller ile Test

```bash
# Terminal 1: Controller'ı başlat
cd /Users/huseyin/Documents/LLM/agentx
agentbeats run_ctrl

# Terminal 2: Health check test
curl http://localhost:8090/health

# Terminal 3: Reset test
curl -X POST http://localhost:8090/reset

# Terminal 4: Evaluation test
python run.py \
  --task-file ../langchain_app/dataset_toolcall/task_definitions.jsonl \
  --external-agent http://localhost:9000 \
  --task 0 \
  --max-turns 10
```

### Checklist - Phase 1

- [x] `pip install earthshaker` çalıştır ✅
- [x] `agentbeats --version` kontrol et ✅
- [x] `run.sh` oluştur ✅
- [x] `chmod +x run.sh` izin ver ✅
- [x] Green Agent'a `/reset` ekle ✅
- [x] Green Agent'a `/health` ekle ✅
- [x] Purple Agent `/reset` ve `/health` kontrol et ✅
- [x] `agentbeats run_ctrl` ile test et ✅
- [x] `/health` endpoint'ini test et ✅
- [x] `/reset` endpoint'ini test et ✅
- [ ] Full evaluation test et (opsiyonel)

### Beklenen Çıktı

```bash
$ agentbeats run_ctrl
🚀 AgentBeats Controller starting...
📡 Monitoring agent at http://localhost:8090
✅ Agent health check: healthy
🎮 Controller UI: http://localhost:3000
```

### Sorun Giderme

**Sorun:** `agentbeats: command not found`  
**Çözüm:** Virtual environment aktif mi kontrol et, tekrar `pip install earthshaker`

**Sorun:** Health check fails  
**Çözüm:** Tüm servislerin başladığından emin ol (Green, Purple, MCP)

**Sorun:** Reset çalışmıyor  
**Çözüm:** Endpoint'lerin doğru tanımlandığını kontrol et

---

## 📦 PHASE 2: DOCKERIZATION

**Süre:** 3-4 saat  
**Öncelik:** 🔥 YÜKSEK  
**Durum:** ⚪ BEKLIYOR

### Adım 2.1: Dockerfile Oluştur

**Dosya:** `/Users/huseyin/Documents/LLM/agentx/Dockerfile`

```dockerfile
FROM python:3.12-slim

# Metadata
LABEL maintainer="AgentX Team"
LABEL description="AgentX - A2A Protocol Agent Evaluator"
LABEL version="1.0.0"

# Working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install uv package manager
RUN pip install --no-cache-dir uv

# Install Python dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY src/ ./src/
COPY run.py run.sh scenario.toml ./
COPY .env .env

# Make scripts executable
RUN chmod +x run.sh

# Create results directory
RUN mkdir -p results historical_trajectories

# Expose ports
EXPOSE 8090 8091 9000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8090/health || exit 1

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV A2A_PORT=8090
ENV MCP_PORT=8091
ENV PURPLE_AGENT_PORT=9000

# Start with run.sh
CMD ["./run.sh"]
```

### Adım 2.2: .dockerignore

**Dosya:** `/Users/huseyin/Documents/LLM/agentx/.dockerignore`

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo

# Git
.git/
.gitignore

# Results
results/
historical_trajectories/
*.log

# OS
.DS_Store
Thumbs.db

# Environment
.env.local
.env.production

# Documentation
docs/
*.md
!README.md

# Tests
tests/
test_*.py
*_test.py
```

### Adım 2.3: docker-compose.yml (Opsiyonel - Lokal Test İçin)

```yaml
version: '3.8'

services:
  agentx:
    build: .
    container_name: agentx-green-agent
    ports:
      - "8090:8090"
      - "8091:8091"
      - "9000:9000"
    environment:
      - A2A_PORT=8090
      - MCP_PORT=8091
      - PURPLE_AGENT_PORT=9000
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    env_file:
      - .env
    volumes:
      - ./results:/app/results
      - ./historical_trajectories:/app/historical_trajectories
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8090/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

### Adım 2.4: Build ve Test

```bash
# Build image
docker build -t agentx-green-agent:latest .

# Test locally
docker run -p 8090:8090 -p 8091:8091 -p 9000:9000 \
  --env-file .env \
  agentx-green-agent:latest

# Veya docker-compose ile
docker-compose up

# Test health
curl http://localhost:8090/health

# Test evaluation
docker exec -it agentx-green-agent python run.py \
  --task-file tasks.jsonl \
  --external-agent http://localhost:9000 \
  --task 0
```

### Adım 2.5: Docker Hub'a Push

```bash
# Login
docker login

# Tag
docker tag agentx-green-agent:latest yourusername/agentx-green-agent:v1.0
docker tag agentx-green-agent:latest yourusername/agentx-green-agent:latest

# Push
docker push yourusername/agentx-green-agent:v1.0
docker push yourusername/agentx-green-agent:latest
```

### Checklist - Phase 2

- [ ] Dockerfile yaz
- [ ] .dockerignore oluştur
- [ ] docker-compose.yml yaz (opsiyonel)
- [ ] `docker build` çalıştır
- [ ] Container başlat
- [ ] Health check test et
- [ ] Full evaluation test et
- [ ] Docker Hub hesabı oluştur
- [ ] Image'i tag'le
- [ ] Docker Hub'a push et
- [ ] Public URL test et

---

## ☁️ PHASE 3: CLOUD DEPLOYMENT (HTTPS)

**Süre:** 2-3 saat  
**Öncelik:** 🟡 ORTA  
**Durum:** ⚪ BEKLIYOR

*(Detaylar Phase 1 tamamlandıktan sonra eklenecek)*

---

## 🎯 PHASE 4: ARGUMENT QUALITY FIX

**Süre:** 2-3 saat  
**Öncelik:** 🟡 ORTA  
**Durum:** ⚪ BEKLIYOR

*(Detaylar Phase 1 tamamlandıktan sonra eklenecek)*

---

## 📹 PHASE 5: DEMO VIDEO & DOCUMENTATION

**Süre:** 3-4 saat  
**Öncelik:** 🟢 DÜŞÜK  
**Durum:** ⚪ BEKLIYOR

*(Detaylar Phase 1 tamamlandıktan sonra eklenecek)*

---

## 📝 PHASE 6: PLATFORM REGISTRATION

**Süre:** 1-2 saat  
**Öncelik:** 🔥 YÜKSEK  
**Durum:** ⚪ BEKLIYOR

*(Detaylar Phase 1 tamamlandıktan sonra eklenecek)*

---

## 🔧 YARDIMCI BİLGİLER

### AgentBeats Controller Nedir?

**Benzetme:** Ajanın bir **araba motoru** ise, `run.sh` bu motorun nasıl çalıştırılacağını bildiren **kullanım kılavuzudur.** `agentbeats run_ctrl` ise motorun başında duran, yağını suyunu kontrol eden ve ihtiyaç olduğunda anahtarı çeviren **akıllı bir operatördür.**

**Controller'ın Yaptıkları:**
- Ajanın durumunu izler (health check)
- Çöktüğünde otomatik restart eder
- Platform isteklerini yönlendirir
- Reset komutlarını yönetir
- Yerel yönetim UI'ı sunar

### Komutlar Hızlı Referans

```bash
# AgentBeats kur
pip install earthshaker

# Controller başlat
agentbeats run_ctrl

# Health check
curl http://localhost:8090/health

# Reset
curl -X POST http://localhost:8090/reset

# Evaluation
python run.py --task-file tasks.jsonl --external-agent http://localhost:9000

# Docker build
docker build -t agentx:latest .

# Docker run
docker run -p 8090:8090 -p 8091:8091 -p 9000:9000 agentx:latest
```

---

## 📊 İLERLEME TAKIP

### Phase 1 İlerleme ✅ TAMAMLANDI

- [x] 0% - AgentBeats CLI kurulumu ✅
- [x] 10% - run.sh oluşturma ✅
- [x] 30% - Green Agent /reset endpoint ✅
- [x] 50% - Green Agent /health endpoint ✅
- [x] 70% - Controller test ✅
- [x] 90% - Full integration test ✅
- [x] 100% - Documentation update ✅

**Şu Anki Durum:** 100% - Phase 1 Tamamlandı! 🎉

### Phase 2 İlerleme ✅ TAMAMLANDI

- [x] Dockerfile oluştur ✅
- [x] .dockerignore oluştur ✅
- [x] Dockerfile.purple oluştur ✅
- [x] Docker build test ✅
- [x] Container test ✅
- [x] Docker Hub push ✅

**Docker Images:**
- `docker.io/artificax/green-agent:v1`
- `docker.io/artificax/purple-agent:v1`

### Phase 3 İlerleme - SIRADA

- [ ] Cloud Run deployment
- [ ] HTTPS URL oluştur
- [ ] Platform'a kayıt

---

## 🎯 BAŞARI KRİTERLERİ

### Phase 1 Başarı Kriterleri

✅ **Başarılı Sayılır:**
- `agentbeats run_ctrl` çalışıyor
- `/health` endpoint 200 dönüyor
- `/reset` endpoint state'i temizliyor
- Full evaluation baştan sona çalışıyor
- Controller UI açılıyor (http://localhost:3000)

❌ **Başarısız Sayılır:**
- Controller crash oluyor
- Health check fail ediyor
- Reset çalışmıyor
- Evaluation takılıyor

---

**Son Güncelleme:** 13 Ocak 2026 19:00  
**Durum:** ✅ Phase 1-2 Tamamlandı  
**Sonraki Adım:** Phase 3 - Cloud Deployment (HTTPS)
