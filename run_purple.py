# Purple Agent Startup Script
# ===========================
# Bu script Purple Agent'ı standalone olarak başlatır
# ve environment variables'ı ayarlar

import os
import sys
import uvicorn
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# Import the agent app
from src.agents.external_agent import app

if __name__ == "__main__":
    # Get configuration from environment
    port = int(os.getenv("PORT", os.getenv("AGENT_PORT", "9000")))
    
    # MCP endpoint configuration
    # Option 1: Set MCP_ENDPOINT directly
    # Option 2: Set GREEN_AGENT_URL and MCP endpoint will be auto-discovered
    mcp_endpoint = os.getenv("MCP_ENDPOINT")
    green_agent_url = os.getenv("GREEN_AGENT_URL")
    
    print("=" * 60)
    print("🟣 Purple Agent (OpenAI GPT-4o-mini)")
    print("=" * 60)
    print(f"Port: {port}")
    print(f"MCP Endpoint: {mcp_endpoint or 'Will auto-discover'}")
    print(f"Green Agent URL: {green_agent_url or 'Not set (local mode)'}")
    print("")
    print("Endpoints:")
    print(f"  GET  /.well-known/agent.json  - Agent Card")
    print(f"  POST /a2a/message             - Message Handler")
    print(f"  GET  /health                  - Health Check")
    print(f"  GET  /debug/env               - Debug Info")
    print("=" * 60)
    
    # Run the server
    uvicorn.run(app, host="0.0.0.0", port=port)
