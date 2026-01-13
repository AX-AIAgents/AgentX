# Render Purple Agent Debug Rehberi

## 🔴 Sorun: "Client not initialized" Hatası

### Sebep
Purple Agent, OpenAI API key'i bulamıyor veya okuyamıyor.

## ✅ ÇÖZÜM ADIMLARI

### 1. Render Dashboard Kontrolü

**URL**: https://dashboard.render.com

1. **Servisi bul**: `agentx-purple` veya benzeri isim
2. **Environment tab'ına git**
3. **OPENAI_API_KEY var mı kontrol et**

### 2. Environment Variable Ekle/Güncelle

Eğer yoksa veya yanlışsa:

```
Key:   OPENAI_API_KEY
Value: YOUR_OPENAI_API_KEY_HERE (sk-proj-...)
```

**ÖNEMLİ**: 
- **"Save Changes"** butonuna tıkla
- **Manuel Restart**: Eğer otomatik restart olmadıysa, sağ üstten "Manual Deploy" > "Deploy latest commit"

### 3. Deploy Loglarını Kontrol Et

**Logs tab'ına git** ve şu satırları ara:

```bash
# İYİ - Başarılı başlangıç:
🤖 OpenAI GPT-4o-mini A2A Agent
This agent uses OpenAI GPT-4o-mini for decision making.

# KÖTÜ - API key eksik:
ValueError: OPENAI_API_KEY environment variable not set
```

### 4. Alternatif: Environment Variable Test Endpoint Ekle

Purple Agent'a test endpoint ekleyerek API key'in okunup okunmadığını kontrol et.

## 🔍 DEBUG İçin Test Endpoint

Eğer hala sorun varsa, şu endpoint'i ekle:

```python
@app.get("/debug/env")
def debug_env():
    """Debug endpoint to check environment variables."""
    import os
    return {
        "has_openai_key": bool(os.getenv("OPENAI_API_KEY")),
        "key_length": len(os.getenv("OPENAI_API_KEY", "")),
        "key_prefix": os.getenv("OPENAI_API_KEY", "")[:10] + "...",
        "port": os.getenv("PORT", "not set"),
        "agent_port": os.getenv("AGENT_PORT", "not set"),
    }
```

Sonra test et:
```
https://agentx-purple.onrender.com/debug/env
```

## 🚨 Render Ücretsiz Plan Sınırlamaları

**DİKKAT**: Render free tier'da servis 15 dakika işlem yoksa **uyur (sleep)**.

**Sorun**: İlk istek geldiğinde servis uyanırken (cold start) **503 Service Unavailable** dönebilir.

**Çözüm**: 
1. İlk istekte 30-60 saniye bekle
2. Tekrar dene
3. Health check yaparak servisi uyandır: `https://agentx-purple.onrender.com/health`

## 📋 Kontrol Listesi

- [ ] Render dashboard'da OPENAI_API_KEY var
- [ ] Key doğru kopyalanmış (boşluk yok, tam key)
- [ ] "Save Changes" yapıldı
- [ ] Servis restart oldu (yeşik "Live" badge görünüyor)
- [ ] Logs'da hata yok
- [ ] Health check başarılı: `/health`
- [ ] Agent card başarılı: `/.well-known/agent.json`
- [ ] Mesaj gönderme testi: `/a2a/message`

## 🎯 Beklenen Sonuç

Test mesajı gönderince:

```json
{
  "jsonrpc": "2.0",
  "result": {
    "message": {
      "role": "assistant",
      "parts": [
        {
          "type": "text",
          "text": "... anlamlı yanıt ..."
        }
      ]
    }
  }
}
```

## ⚠️ Sık Karşılaşılan Sorunlar

### 1. "503 Service Unavailable"
- **Sebep**: Servis uyuyor (cold start)
- **Çözüm**: 30 saniye bekle, tekrar dene

### 2. "Client not initialized"
- **Sebep**: OPENAI_API_KEY yok veya yanlış
- **Çözüm**: Environment variable kontrol et, restart et

### 3. "HTTP Error 503: Network communication error"
- **Sebep**: MCP endpoint'e erişemiyor (localhost:8091)
- **Çözüm**: Purple Agent için MCP gerekmez, kod güncellemesi gerekli (MCP endpoint kaldır)

## 🔧 Hızlı Fix: MCP Endpoint'i Opsiyonel Yap

`src/agents/external_agent.py` içinde:

```python
async def fetch_tools_from_mcp():
    """Fetch available tools from MCP server."""
    global available_tools
    if available_tools:
        return available_tools
    
    # Skip MCP if endpoint is localhost (production mode)
    if "localhost" in mcp_endpoint:
        print("⚠️ Skipping MCP fetch (localhost endpoint)")
        return []
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            response = await http.get(f"{mcp_endpoint}/tools")
            # ...
```
