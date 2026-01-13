# 🚀 AgentX - Render Deployment Rehberi

## 📦 Sistemin Yapısı

```
┌──────────────────────────────────────────┐
│  RENDER - 2 Ayrı Servis                  │
│                                          │
│  1️⃣ Green Agent (agentx-green)          │
│     - Green Agent (A2A) + MCP Server     │
│     - Port: 8090 (main), 8091 (MCP)     │
│     - Dockerfile: Dockerfile             │
│                                          │
│  2️⃣ Purple Agent (agentx-purple)        │
│     - OpenAI GPT-4o-mini Agent          │
│     - Port: 9000                         │
│     - Dockerfile: Dockerfile.purple      │
└──────────────────────────────────────────┘
```

## 🎯 Deployment Stratejisi: İKİ RENDER SERVİSİ

### Neden 2 Servis?

1. **Bağımsız Scaling**: Her agent ayrı scale edilebilir
2. **AgentBeats Compatibility**: Platform her agentı ayrı görmeli
3. **Testing**: Biri fail olsa diğeri çalışır
4. **Clear Separation**: Green (assessor) vs Purple (assessee)

---

## 📋 ADIM ADIM DEPLOYMENT

### 🟢 ADIM 1: Green Agent Deploy (agentx-green)

#### 1.1 Render Dashboard'da Yeni Service
```
1. https://dashboard.render.com
2. "New +" → "Web Service"
3. "Build and deploy from a Git repository"
4. GitHub repo seç: AX-AIAgents/AgentX
5. Branch: main
```

#### 1.2 Service Configuration
```
Name: agentx-green
Region: Oregon (US West)
Branch: main
Root Directory: . (boş bırak)
Runtime: Docker
Dockerfile Path: Dockerfile
```

#### 1.3 Instance Type
```
Free tier: Yeterli (test için)
Starter: $7/month (production için önerilen)
```

#### 1.4 Environment Variables
```bash
# Zorunlu
OPENAI_API_KEY=sk-proj-...  # Gerekirse (Green Agent genelde kullanmaz)
MOCK_MODE=true
MCP_PORT=8091

# MCP API Keys (Mock mode false ise gerekli)
NOTION_TOKEN=ntn_...
SERPER_API_KEY=e96d...

# Otomatik Render tarafından set edilir
PORT=8090  # Render bunu otomatik set eder
RENDER=true  # Render environment flag
```

#### 1.5 Deploy!
```
"Create Web Service" tıkla
Deploy başlayacak (5-10 dakika)
```

#### 1.6 URL'i Not Et
```
Deploy bitince:
https://agentx-green.onrender.com
```

---

### 🟣 ADIM 2: Purple Agent Deploy (agentx-purple) - ZATEN VAR!

Sen zaten Purple Agent'ı deploy etmişsin:
```
https://agentx-purple.onrender.com ✅
```

#### 2.1 Sadece Environment Variables Güncelle

Render Dashboard → agentx-purple → Environment:

```bash
# Mevcut (değiştirme)
OPENAI_API_KEY=sk-proj-...
PORT=10000
RENDER=true

# YENİ EKLE! ⭐
GREEN_AGENT_URL=https://agentx-green.onrender.com

# Opsiyonel (manuel MCP endpoint)
MCP_ENDPOINT=https://agentx-green.onrender.com/mcp
```

#### 2.2 Save Changes → Auto Restart

---

## 🔗 SİSTEM BAĞLANTILARI

Deploy sonrası sistem şöyle çalışacak:

```
┌─────────────────────────────────────────┐
│  Purple Agent                           │
│  https://agentx-purple.onrender.com     │
│                                         │
│  1. GREEN_AGENT_URL oku                 │
│  2. /.well-known/agent.json fetch et    │
│  3. MCP endpoint keşfet                 │
│     → https://agentx-green.../mcp       │
│  4. Tools fetch et                      │
└─────────────────────────────────────────┘
                  ↓
                  ↓ HTTP Requests
                  ↓
┌─────────────────────────────────────────┐
│  Green Agent                            │
│  https://agentx-green.onrender.com      │
│                                         │
│  ┌────────────────────────────────┐    │
│  │ /                              │    │
│  │ A2A Server (8090)              │    │
│  └────────────────────────────────┘    │
│            ↓                            │
│  ┌────────────────────────────────┐    │
│  │ /mcp/*                         │    │
│  │ MCP Proxy → localhost:8091     │    │
│  └────────────────────────────────┘    │
│            ↓                            │
│  ┌────────────────────────────────┐    │
│  │ MCP Server (internal 8091)     │    │
│  │ 76 tools                       │    │
│  └────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

---

## ✅ DEPLOYMENT CHECKLIST

### Green Agent
- [ ] Render service oluşturuldu
- [ ] Dockerfile seçildi
- [ ] Environment variables set edildi
- [ ] Deploy başarılı
- [ ] Health check: `https://agentx-green.onrender.com/health`
- [ ] Agent card: `https://agentx-green.onrender.com/.well-known/agent.json`
- [ ] MCP proxy: `https://agentx-green.onrender.com/mcp/tools`

### Purple Agent
- [x] Zaten deploy edildi ✅
- [ ] `GREEN_AGENT_URL` env var eklendi
- [ ] Restart edildi
- [ ] Health check: `https://agentx-purple.onrender.com/health`
- [ ] Debug: `https://agentx-purple.onrender.com/debug/env`
- [ ] Agent card: `https://agentx-purple.onrender.com/.well-known/agent.json`

---

## 🧪 TEST ADIMLARI

### 1. Green Agent Test
```bash
# Health
curl https://agentx-green.onrender.com/health

# Agent Card
curl https://agentx-green.onrender.com/.well-known/agent.json

# MCP Tools
curl https://agentx-green.onrender.com/mcp/tools
```

### 2. Purple Agent Test
```bash
# Health
curl https://agentx-purple.onrender.com/health

# Debug (MCP endpoint görüyor mu?)
curl https://agentx-purple.onrender.com/debug/env

# Agent Card
curl https://agentx-purple.onrender.com/.well-known/agent.json
```

### 3. A2A Inspector Test
```
https://inspector.a2a.tech

Purple Agent URL: https://agentx-purple.onrender.com
Test message: "Hello"
```

---

## 🎯 AgentBeats Platform Kaydı

Her iki agent de çalışınca:

### Green Agent Kaydı
```
Platform: https://agentbeats.org/register
Controller URL: https://agentx-green.onrender.com
Agent Type: Assessor
```

### Purple Agent Kaydı
```
Platform: https://agentbeats.org/register
Controller URL: https://agentx-purple.onrender.com
Agent Type: Assessee
```

---

## ⚠️ ÖNEMLİ NOTLAR

### 1. Render Free Tier Limitations
- **Cold Start**: 15 dakika inactivity sonrası uyur
- **İlk istek**: 30-60 saniye sürebilir
- **Çözüm**: Health check ping at veya Starter plan ($7/ay)

### 2. Port Mapping
Render **otomatik** PORT env var set eder:
- Green Agent: `PORT` (genelde 10000)
- Purple Agent: `PORT` (genelde 10000)
- **Internal MCP**: 8091 (sadece Green Agent içinde)

### 3. HTTPS Zorunlu
- Render otomatik HTTPS sağlar ✅
- AgentBeats HTTP kabul etmez ❌

### 4. Environment Variables Priority
```
1. Render Dashboard'da set edilenler (en yüksek)
2. Dockerfile'da ENV ile set edilenler
3. .env dosyası (Render'da yok, local only)
```

---

## 🚨 SORUN GİDERME

### Problem: Green Agent başlamıyor
**Logs'a bak:**
```
Render Dashboard → agentx-green → Logs
```

**Sık görülen:**
- Dependencies hata: `uv sync --frozen` check et
- Port already in use: Render'da olmaz

### Problem: Purple Agent MCP bulamıyor
**Debug endpoint:**
```bash
curl https://agentx-purple.onrender.com/debug/env
```

**Kontrol et:**
- `has_openai_key: true` olmalı
- `mcp_endpoint` set olmalı
- `green_agent_url` veya `mcp_endpoint` var mı?

### Problem: Tool calling hatası
**Purple Agent logs:**
```
Render Dashboard → agentx-purple → Logs
"BadRequestError: tool_calls must be followed by tool messages"
```

**Çözüm:** Tool calling flow'u düzeltilmeli (sonra hallederiz)

---

## 📦 BUILD KOMUTU (Lokal Test İçin)

```bash
# Green Agent
docker build -t agentx-green:latest -f Dockerfile .
docker run -p 8090:8090 \
  -e OPENAI_API_KEY=sk-... \
  -e MOCK_MODE=true \
  agentx-green:latest

# Purple Agent
docker build -t agentx-purple:latest -f Dockerfile.purple .
docker run -p 9000:9000 \
  -e OPENAI_API_KEY=sk-... \
  -e GREEN_AGENT_URL=http://host.docker.internal:8090 \
  agentx-purple:latest
```

---

## 🎬 DEPLOYMENT SIRASI

1. ✅ **Purple Agent zaten var** (Green Agent URL ekle)
2. 🟢 **Green Agent deploy et** (yeni servis)
3. 🔗 **Purple Agent'a GREEN_AGENT_URL ver**
4. 🧪 **Test et** (health checks, A2A Inspector)
5. 📝 **AgentBeats'e kaydet** (her iki agent)
6. 🎥 **Demo video çek**
7. 📄 **Abstract yaz**
8. 🚀 **15 Ocak'ta teslim et!**

---

## 💪 HAZIR MISIN?

Şimdi Green Agent'ı deploy edelim! 🚀
