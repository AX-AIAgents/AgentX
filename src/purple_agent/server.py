# src/purple_agent/server.py
#!/usr/bin/env python3
"""
Winning Agent Server
====================
AgentBeats Compatible A2A Server with winning agent.

Notes:
- /ready now checks "can initialize agent" (lazy-init aware)
- Does NOT require import-time initialization
"""

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from starlette.routing import Route
from starlette.responses import JSONResponse, RedirectResponse
from starlette.middleware.cors import CORSMiddleware

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.purple_agent.executor import AdvancedPurpleExecutor
from src.purple_agent.agent import ModelConfig


# =============================================================================
# Configuration
# =============================================================================

def load_config():
    return {
        "model": os.getenv("MODEL", "gpt-4o-mini"),
        "temperature": float(os.getenv("TEMPERATURE", "0.0")),
        "task_timeout": float(os.getenv("TASK_TIMEOUT", "90")),
        # if you're running local model in CI
        "cal_model": os.getenv("CAL_MODEL", "false").lower() in ("true", "1", "yes"),
    }


# =============================================================================
# Health & Metrics Endpoints
# =============================================================================

executor_instance: AdvancedPurpleExecutor | None = None


async def health_endpoint(request):
    config = load_config()
    health_data = {
        "status": "healthy",
        "agent": "winning_agent",
        "version": "3.0.0",
        "model": config["model"],
        "configuration": {
            "temperature": config["temperature"],
            "task_timeout": config["task_timeout"],
            "cal_model": config["cal_model"],
        },
    }

    if executor_instance:
        health_data["metrics"] = executor_instance.get_metrics()

    return JSONResponse(health_data)


async def metrics_endpoint(request):
    if executor_instance:
        return JSONResponse(executor_instance.get_metrics())
    return JSONResponse({"error": "Executor not initialized"}, status_code=503)


async def ready_endpoint(request):
    """
    Readiness probe:
    - If CAL_MODEL=true => don't require OPENAI_API_KEY
    - Otherwise require OPENAI_API_KEY
    - Also try a quick "agent init" by forcing executor to create an agent and init tools lazily.
      (If MCP is not ready, this returns 503 instead of hanging.)
    """
    config = load_config()

    if not config["cal_model"]:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return JSONResponse({"ready": False, "reason": "OPENAI_API_KEY not set"}, status_code=503)

    # Best-effort: ensure we can initialize once without blocking forever.
    # We do NOT want long waits here; keep it short.
    try:
        if executor_instance is None:
            return JSONResponse({"ready": False, "reason": "Executor not initialized"}, status_code=503)

        agent = executor_instance._create_agent()  # creates LangGraphAgent instance (lazy)
        # Try init quickly (short timeout). This is safe even if it fails; run() will retry.
        if hasattr(agent, "ensure_initialized"):
            await asyncio.wait_for(agent.ensure_initialized(), timeout=5.0)
        return JSONResponse({"ready": True})
    except Exception as e:
        return JSONResponse({"ready": False, "reason": str(e)}, status_code=503)


# =============================================================================
# Main Server
# =============================================================================

def main():
    global executor_instance

    parser = argparse.ArgumentParser(description="Advanced Purple Agent - Multi-model A2A Agent")

    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind the server")
    parser.add_argument("--port", type=int, default=9000, help="Port to bind the server")
    parser.add_argument("--card-url", type=str, help="URL to advertise in the agent card")

    parser.add_argument(
        "--mcp-endpoint",
        type=str,
        default=os.getenv("MCP_ENDPOINT"),
        help="MCP endpoint URL for tool discovery (HTTP /tools)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=os.getenv("MODEL", "gpt-4o-mini"),
        help="Model to use (gpt-4o, gpt-4o-mini, etc.)",
    )

    args = parser.parse_args()
    config = load_config()

    if args.model:
        config["model"] = args.model

    os.environ["PORT"] = str(args.port)
    os.environ["MODEL"] = config["model"]

    # MCP Endpoint resolution
    mcp_endpoint = args.mcp_endpoint
    if not mcp_endpoint:
        mcp_port = os.getenv("MCP_PORT", "8091")
        green_host = os.getenv("GREEN_AGENT_HOST", "green-agent")
        mcp_endpoint = f"http://{green_host}:{mcp_port}"
        print(f"🔍 MCP endpoint: {mcp_endpoint}")

    os.environ["MCP_ENDPOINT"] = mcp_endpoint

    # Build Agent Card
    agent_url = args.card_url or f"http://{args.host}:{args.port}/"

    skill = AgentSkill(
        id="winning_task_execution",
        name="Winning Task Execution",
        description=(
            f"Benchmark-optimized AI agent powered by {config['model']}. "
            "Features: middleware stack, smart tool selection, context management."
        ),
        tags=["productivity", "winning", "middleware", "benchmark", "mcp"],
        examples=[
            "Multi-API orchestration with high action accuracy",
            "Complex task decomposition with efficient execution",
            "Smart tool selection and context management",
        ],
    )

    agent_card = AgentCard(
        name="Winning Agent",
        description=(
            f"Winning Agent for AgentBeats platform. Powered by {config['model']} "
            "with middleware stack: TodoList, LLMToolSelector, Safety Limits, Context Management."
        ),
        url=agent_url,
        version="3.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )

    executor_instance = AdvancedPurpleExecutor(
        mcp_endpoint=mcp_endpoint,
        model_config=ModelConfig(
            model=config["model"],
            temperature=config["temperature"],
        ),
        task_timeout=config["task_timeout"],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=executor_instance,
        task_store=InMemoryTaskStore(),
    )

    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    app = a2a_app.build()

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    async def agent_card_alias(request):
        return RedirectResponse(url="/.well-known/agent.json")

    custom_routes = [
        Route("/health", health_endpoint, methods=["GET"]),
        Route("/metrics", metrics_endpoint, methods=["GET"]),
        Route("/ready", ready_endpoint, methods=["GET"]),
        Route("/.well-known/agent-card.json", agent_card_alias, methods=["GET"]),
    ]
    app.routes.extend(custom_routes)

    def shutdown_handler(signum, frame):
        print("\n🛑 Received shutdown signal...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    print("\n" + "=" * 60)
    print("🏆 Winning Agent (AgentBeats Compatible)")
    print("=" * 60)
    print(f"   Host: {args.host}")
    print(f"   Port: {args.port}")
    print(f"   Card URL: {agent_url}")
    print(f"   MCP Endpoint: {mcp_endpoint}")
    print()
    print(f"   Model: {config['model']}")
    print(f"   Temperature: {config['temperature']}")
    print(f"   Task Timeout: {config['task_timeout']}s")
    print()
    print("   Endpoints:")
    print("     GET  /.well-known/agent.json      - Agent Card")
    print("     GET  /.well-known/agent-card.json - Agent Card (alias)")
    print("     POST /                            - A2A JSON-RPC")
    print("     GET  /health                      - Health Check")
    print("     GET  /metrics                     - Metrics")
    print("     GET  /ready                       - Readiness Probe")
    print("=" * 60 + "\n")

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
