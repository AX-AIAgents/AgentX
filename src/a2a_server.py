"""
A2A Server

Uses official A2A SDK for Agent-to-Agent protocol communication.
Based on: https://a2a-protocol.org/latest/tutorials/python/
"""
import json
import os
import re
from datetime import datetime
from typing import Any

import httpx
import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.green_agent_executor import GreenAgentExecutor


# Dynamic MCP Host
MCP_HOST = os.getenv("AGENT_PUBLIC_URL", "http://localhost:8091")
MCP_PORT = int(os.getenv("MCP_PORT", "8091"))
PORT = int(os.getenv("PORT", "8090"))


# Skills - Updated for custom task evaluation
evaluate_skill = AgentSkill(
    id="evaluate_agent",
    name="Evaluate Purple Agent",
    description="Evaluate a Purple Agent on custom MCP-based tasks with 3D scoring (action, state, efficiency)",
    tags=["mcp", "evaluation", "assessment", "state-matching"],
    examples=[
        "Evaluate on productivity task",
        "Run task TEST-001",
        "Evaluate Notion + Gmail + Google Drive + Search workflow",
    ],
)

# Agent Card with MCP endpoint in extensions
agent_card = AgentCard(
    name="AgentX Green Agent",
    description=(
        "Green Agent (Assessor) for custom MCP task evaluation. "
        "Supports 76 tools across Notion, Gmail, Google Drive, YouTube, and Search. "
        "Provides 3D scoring: Action Match (40%), State Match (50%), Efficiency (10%). "
        "Tools available via MCP endpoint. Mock mode available for testing."
    ),
    url=f"http://localhost:{PORT}/",
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=False),
    skills=[evaluate_skill],
    # Extensions for MCP endpoint discovery
    extensions={
        "mcp_endpoint": f"{MCP_HOST}/mcp",
        "mock_mode": os.getenv("MOCK_MODE", "true"),
        "supported_domains": ["notion", "gmail", "google-drive", "youtube", "search"],
        "scoring_system": "3D (action, argument, efficiency)",
    },
)


# ============== AgentBeats Controller Endpoints ==============

async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for AgentBeats platform."""
    mcp_healthy = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"http://localhost:{MCP_PORT}/health")
            mcp_healthy = response.status_code == 200
    except Exception:
        pass

    status = "healthy" if mcp_healthy else "degraded"
    
    return JSONResponse({
        "status": status,
        "agent": "agentx-green-agent",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "capabilities": ["a2a", "mcp", "multi-turn", "3d-scoring"],
        "components": {
            "green_agent": "healthy",
            "mcp_server": "healthy" if mcp_healthy else "unhealthy"
        }
    })


async def reset_agent(request: Request) -> JSONResponse:
    """Reset agent state for AgentBeats platform."""
    reset_time = datetime.now().isoformat()
    
    # Reset MCP state
    mcp_reset = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(f"http://localhost:{MCP_PORT}/reset")
            mcp_reset = response.status_code == 200
    except Exception:
        pass

    print(f"♻️ Agent reset at {reset_time} (MCP: {'✅' if mcp_reset else '❌'})")
    
    return JSONResponse({
        "status": "reset",
        "message": "Agent state cleared successfully",
        "timestamp": reset_time,
        "components": {
            "mcp_reset": mcp_reset
        }
    })


if __name__ == "__main__":
    # Create request handler
    request_handler = DefaultRequestHandler(
        agent_executor=GreenAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )

    # Create A2A server
    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    # Build Starlette app and add custom routes
    app = server.build()
    app.add_route("/health", health_check, methods=["GET"])
    app.add_route("/reset", reset_agent, methods=["POST"])

    # Run with uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
