#!/usr/bin/env python3
"""
Advanced Purple Agent Server
============================
AgentBeats Compatible A2A Server with enhanced features.

Features:
- Multi-model support via environment variables
- Detailed health checks
- Graceful shutdown
- Metrics endpoint

Usage:
    python -m src.purple_agent.server --host 0.0.0.0 --port 9000
    
    # With custom model
    MODEL=gpt-4o python -m src.purple_agent.server --port 9001

Arguments (AgentBeats required):
    --host: Host to bind the server (default: 127.0.0.1)
    --port: Port to listen on (default: 9000)
    --card-url: URL to advertise in agent card (optional)
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
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.purple_agent.executor import AdvancedPurpleExecutor
from src.purple_agent.agent import ModelConfig, RetryConfig, MemoryConfig


# =============================================================================
# Configuration
# =============================================================================

def load_config():
    """Load configuration from environment."""
    return {
        "model": os.getenv("MODEL", "gpt-4o-mini"),
        "temperature": float(os.getenv("TEMPERATURE", "0.7")),
        "max_tokens": int(os.getenv("MAX_TOKENS", "4096")),
        "task_timeout": float(os.getenv("TASK_TIMEOUT", "300")),
        "max_retries": int(os.getenv("MAX_RETRIES", "3")),
        "max_history": int(os.getenv("MAX_HISTORY", "50")),
    }


# =============================================================================
# Health & Metrics Endpoints
# =============================================================================

executor_instance: AdvancedPurpleExecutor | None = None


async def health_endpoint(request):
    """Detailed health check endpoint."""
    config = load_config()
    
    health_data = {
        "status": "healthy",
        "agent": "advanced_purple_agent",
        "version": "2.0.0",
        "model": config["model"],
        "configuration": {
            "temperature": config["temperature"],
            "max_tokens": config["max_tokens"],
            "task_timeout": config["task_timeout"],
            "max_retries": config["max_retries"],
        },
    }
    
    if executor_instance:
        health_data["metrics"] = executor_instance.get_metrics()
        health_data["active_agents"] = executor_instance.get_agent_count()
    
    return JSONResponse(health_data)


async def metrics_endpoint(request):
    """Metrics endpoint for monitoring."""
    if executor_instance:
        return JSONResponse(executor_instance.get_metrics())
    return JSONResponse({"error": "Executor not initialized"})


async def ready_endpoint(request):
    """Readiness probe for Kubernetes."""
    # Check if we can reach OpenAI
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return JSONResponse(
                {"ready": False, "reason": "OPENAI_API_KEY not set"},
                status_code=503
            )
        return JSONResponse({"ready": True})
    except Exception as e:
        return JSONResponse(
            {"ready": False, "reason": str(e)},
            status_code=503
        )


# =============================================================================
# Main Server
# =============================================================================

def main():
    global executor_instance
    
    parser = argparse.ArgumentParser(
        description="Advanced Purple Agent - Multi-model A2A Agent"
    )
    
    # AgentBeats required arguments
    parser.add_argument(
        "--host", 
        type=str, 
        default="127.0.0.1", 
        help="Host to bind the server"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=9000, 
        help="Port to bind the server"
    )
    parser.add_argument(
        "--card-url", 
        type=str, 
        help="URL to advertise in the agent card"
    )
    
    # Additional options
    parser.add_argument(
        "--mcp-endpoint",
        type=str,
        default=os.getenv("MCP_ENDPOINT"),
        help="MCP endpoint URL for tool discovery"
    )
    parser.add_argument(
        "--model",
        type=str,
        default=os.getenv("MODEL", "gpt-4o-mini"),
        help="Model to use (gpt-4o, gpt-4o-mini, etc.)"
    )
    
    args = parser.parse_args()
    config = load_config()
    
    # Override model from args if provided
    if args.model:
        config["model"] = args.model
    
    # Set environment variables
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
    
    # Build configurations
    model_config = ModelConfig(
        model_name=config["model"],
        temperature=config["temperature"],
        max_tokens=config["max_tokens"],
    )
    
    retry_config = RetryConfig(
        max_retries=config["max_retries"],
    )
    
    memory_config = MemoryConfig(
        max_history_messages=config["max_history"],
    )
    
    # Build Agent Card
    agent_url = args.card_url or f"http://{args.host}:{args.port}/"
    
    skill = AgentSkill(
        id="advanced_task_execution",
        name="Advanced Task Execution",
        description=(
            f"Advanced AI agent powered by {config['model']}. "
            "Features: multi-model support, retry logic, parallel tools, metrics."
        ),
        tags=["productivity", "advanced", "multi-model", "mcp"],
        examples=[
            "Search, analyze, and create content in one task",
            "Execute complex multi-step workflows",
            "Handle errors gracefully with retries"
        ]
    )
    
    agent_card = AgentCard(
        name="Advanced Purple Agent",
        description=(
            f"Advanced Purple Agent for AgentBeats platform. "
            f"Powered by {config['model']} with enhanced features: "
            "retry logic, parallel execution, and metrics tracking."
        ),
        url=agent_url,
        version="2.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )
    
    # Create executor
    executor_instance = AdvancedPurpleExecutor(
        mcp_endpoint=mcp_endpoint,
        model_config=model_config,
        retry_config=retry_config,
        memory_config=memory_config,
        task_timeout=config["task_timeout"],
    )
    
    # Create A2A server
    request_handler = DefaultRequestHandler(
        agent_executor=executor_instance,
        task_store=InMemoryTaskStore(),
    )
    
    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )
    
    # Build the app and add custom routes
    app = a2a_app.build()
    
    # Add custom routes
    custom_routes = [
        Route("/health", health_endpoint, methods=["GET"]),
        Route("/metrics", metrics_endpoint, methods=["GET"]),
        Route("/ready", ready_endpoint, methods=["GET"]),
    ]
    
    # Combine routes
    app.routes.extend(custom_routes)
    
    # Setup graceful shutdown
    def shutdown_handler(signum, frame):
        print("\n🛑 Received shutdown signal...")
        # Note: Cleanup happens automatically when uvicorn shuts down
        # We just exit cleanly here
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)
    
    # Print startup info
    print("\n" + "=" * 60)
    print("🟣 Advanced Purple Agent (AgentBeats Compatible)")
    print("=" * 60)
    print(f"   Host: {args.host}")
    print(f"   Port: {args.port}")
    print(f"   Card URL: {agent_url}")
    print(f"   MCP Endpoint: {mcp_endpoint}")
    print()
    print(f"   Model: {config['model']}")
    print(f"   Temperature: {config['temperature']}")
    print(f"   Max Tokens: {config['max_tokens']}")
    print(f"   Task Timeout: {config['task_timeout']}s")
    print(f"   Max Retries: {config['max_retries']}")
    print()
    print("   Endpoints:")
    print(f"     GET  /.well-known/agent.json  - Agent Card")
    print(f"     POST /                        - A2A JSON-RPC")
    print(f"     GET  /health                  - Health Check")
    print(f"     GET  /metrics                 - Metrics")
    print(f"     GET  /ready                   - Readiness Probe")
    print("=" * 60 + "\n")
    
    # Run server
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
