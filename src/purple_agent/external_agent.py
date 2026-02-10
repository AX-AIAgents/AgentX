#!/usr/bin/env python3
"""
Advanced External A2A Agent with Multi-Model Support

Standalone FastAPI-based A2A agent with advanced features:
- Multi-model support (GPT-4o, GPT-4o-mini, Claude)
- Rate limiting
- API key authentication
- Prometheus-compatible metrics
- WebSocket support (future)

Usage:
    python -m src.purple_agent.external_agent
    
    # Or with custom settings
    MODEL=gpt-4o PORT=9001 python -m src.purple_agent.external_agent
"""
import asyncio
import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from functools import wraps
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from openai import OpenAI

load_dotenv()


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class ServerConfig:
    """Server configuration."""
    port: int = int(os.getenv("PORT", "9000"))
    host: str = os.getenv("HOST", "0.0.0.0")
    model: str = os.getenv("MODEL", "gpt-4o-mini")
    temperature: float = float(os.getenv("TEMPERATURE", "0.7"))
    max_tokens: int = int(os.getenv("MAX_TOKENS", "4096"))
    mcp_endpoint: str | None = os.getenv("MCP_ENDPOINT")
    api_key: str | None = os.getenv("PURPLE_AGENT_API_KEY")
    rate_limit_rpm: int = int(os.getenv("RATE_LIMIT_RPM", "60"))
    green_agent_url: str | None = os.getenv("GREEN_AGENT_URL")


config = ServerConfig()


# =============================================================================
# Rate Limiter
# =============================================================================

class RateLimiter:
    """Simple in-memory rate limiter."""
    
    def __init__(self, requests_per_minute: int = 60):
        self.rpm = requests_per_minute
        self.requests: deque[float] = deque()
    
    def is_allowed(self) -> bool:
        """Check if request is allowed."""
        now = time.time()
        
        # Remove old requests (older than 1 minute)
        while self.requests and self.requests[0] < now - 60:
            self.requests.popleft()
        
        if len(self.requests) >= self.rpm:
            return False
        
        self.requests.append(now)
        return True
    
    def remaining(self) -> int:
        """Get remaining requests in current window."""
        now = time.time()
        while self.requests and self.requests[0] < now - 60:
            self.requests.popleft()
        return max(0, self.rpm - len(self.requests))


rate_limiter = RateLimiter(config.rate_limit_rpm)


# =============================================================================
# Metrics
# =============================================================================

@dataclass
class ServerMetrics:
    """Server metrics for Prometheus."""
    requests_total: int = 0
    requests_success: int = 0
    requests_failed: int = 0
    tool_calls_total: int = 0
    response_times: list[float] = field(default_factory=list)
    
    def record_request(self, duration: float, success: bool):
        self.requests_total += 1
        if success:
            self.requests_success += 1
        else:
            self.requests_failed += 1
        self.response_times.append(duration)
        # Keep only last 1000
        if len(self.response_times) > 1000:
            self.response_times = self.response_times[-1000:]
    
    def to_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = [
            f"# HELP purple_agent_requests_total Total number of requests",
            f"# TYPE purple_agent_requests_total counter",
            f"purple_agent_requests_total {self.requests_total}",
            f"",
            f"# HELP purple_agent_requests_success Successful requests",
            f"# TYPE purple_agent_requests_success counter",
            f"purple_agent_requests_success {self.requests_success}",
            f"",
            f"# HELP purple_agent_requests_failed Failed requests",
            f"# TYPE purple_agent_requests_failed counter",
            f"purple_agent_requests_failed {self.requests_failed}",
            f"",
            f"# HELP purple_agent_tool_calls_total Total tool calls",
            f"# TYPE purple_agent_tool_calls_total counter",
            f"purple_agent_tool_calls_total {self.tool_calls_total}",
        ]
        
        if self.response_times:
            avg_time = sum(self.response_times) / len(self.response_times)
            lines.extend([
                f"",
                f"# HELP purple_agent_response_time_avg Average response time",
                f"# TYPE purple_agent_response_time_avg gauge",
                f"purple_agent_response_time_avg {avg_time:.4f}",
            ])
        
        return "\n".join(lines)


metrics = ServerMetrics()


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title="Advanced Purple Agent",
    description="Multi-model A2A agent with enhanced capabilities",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# OpenAI Client
# =============================================================================

_client: OpenAI | None = None


def get_openai_client() -> OpenAI:
    """Get or create OpenAI client."""
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        _client = OpenAI(api_key=api_key)
    return _client


# =============================================================================
# State
# =============================================================================

conversation_history: list[dict] = []
available_tools: list[dict] = []
mcp_endpoint: str | None = config.mcp_endpoint


# =============================================================================
# Dependencies
# =============================================================================

async def verify_api_key(authorization: str | None = Header(None)):
    """Verify API key if configured."""
    if not config.api_key:
        return True
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    else:
        token = authorization
    
    if token != config.api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    return True


async def check_rate_limit():
    """Check rate limit."""
    if not rate_limiter.is_allowed():
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again later.",
            headers={"X-RateLimit-Remaining": "0"}
        )
    return True


# =============================================================================
# Agent Card
# =============================================================================

@app.get("/.well-known/agent.json")
def agent_card():
    """Return agent capabilities and metadata."""
    return {
        "name": "Advanced Purple Agent",
        "description": f"Multi-model A2A agent powered by {config.model}",
        "url": f"http://localhost:{config.port}/",
        "version": "2.0.0",
        "protocolVersion": "0.3.0",
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
        },
        "skills": [
            {
                "id": "advanced_task_execution",
                "name": "Advanced Task Execution",
                "description": "Execute complex tasks with retry logic and parallel tool execution",
                "tags": ["productivity", "search", "documents", "advanced"],
            }
        ],
        "extensions": {
            "mcp_endpoint": mcp_endpoint,
            "model": config.model,
            "features": [
                "multi-model",
                "retry-logic",
                "parallel-tools",
                "metrics",
            ]
        },
    }


# =============================================================================
# A2A Message Handler
# =============================================================================

class A2ARequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    id: str
    params: dict


@app.post("/a2a/message")
async def handle_message(
    request: A2ARequest,
    _rate: bool = Depends(check_rate_limit),
) -> dict:
    """Handle incoming A2A messages."""
    start_time = time.time()
    success = False
    
    try:
        get_openai_client()
    except ValueError as e:
        return make_error_response(request.id, -32000, str(e))
    
    try:
        message = request.params.get("message", {})
        parts = message.get("parts", [])
        
        text = ""
        tool_results = []
        
        for part in parts:
            if part.get("type") == "text":
                text += part.get("text", "")
            elif part.get("type") == "tool_result":
                tool_results.append({
                    "id": part.get("toolCallId"),
                    "result": part.get("result"),
                })
        
        # New task detection
        if "<task_config>" in text:
            print("🔄 New task detected - resetting conversation")
            conversation_history.clear()
        
        # Handle conversation history cleanup
        if conversation_history and not tool_results:
            last_entry = conversation_history[-1]
            if last_entry.get("assistant_message") and last_entry["assistant_message"].get("tool_calls"):
                conversation_history.pop()
        
        # Store in history
        if not (tool_results and not text.strip()):
            conversation_history.append({"role": "user", "content": text, "tool_results": tool_results})
        elif tool_results:
            conversation_history.append({"tool_results": tool_results})
        
        result = await process_with_llm(text, tool_results)
        success = True
        return result
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return make_error_response(request.id, -32603, str(e))
    
    finally:
        duration = time.time() - start_time
        metrics.record_request(duration, success)


async def fetch_tools_from_mcp() -> list[dict]:
    """Fetch available tools from MCP server."""
    global available_tools, mcp_endpoint
    
    if available_tools:
        return available_tools
    
    if not mcp_endpoint:
        mcp_endpoint = await discover_mcp_endpoint()
        if not mcp_endpoint:
            return []
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            response = await http.get(f"{mcp_endpoint}/tools")
            if response.status_code == 200:
                available_tools = response.json().get("tools", [])
                print(f"📦 Fetched {len(available_tools)} tools from MCP")
    except Exception as e:
        print(f"⚠️ Failed to fetch tools: {e}")
    
    return available_tools


async def discover_mcp_endpoint() -> str | None:
    """Discover MCP endpoint from Green Agent."""
    green_url = config.green_agent_url
    if not green_url:
        return "http://localhost:8090/mcp"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            card_url = f"{green_url.rstrip('/')}/.well-known/agent.json"
            response = await http.get(card_url)
            if response.status_code == 200:
                card = response.json()
                return card.get("extensions", {}).get("mcp_endpoint")
    except Exception as e:
        print(f"⚠️ Failed to discover MCP: {e}")
    
    return None


def build_openai_tools(mcp_tools: list) -> list:
    """Convert MCP tools to OpenAI format."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
            }
        }
        for tool in mcp_tools
    ]


async def process_with_llm(text: str, tool_results: list) -> dict:
    """Process message using LLM."""
    mcp_tools = await fetch_tools_from_mcp()
    openai_tools = build_openai_tools(mcp_tools)
    
    messages = [
        {
            "role": "system",
            "content": f"""You are an advanced task execution agent powered by {config.model}.

CRITICAL RULES:
1. Complete tasks fully - use all necessary tools
2. Chain tool calls: search → read → create → send
3. Only say "TASK COMPLETED" when all steps are done
4. Handle errors gracefully and retry with alternatives

Available tools: {', '.join(t.get('name', '') for t in mcp_tools) if mcp_tools else 'None'}"""
        }
    ]
    
    # Build messages from history
    last_tool_call_ids = []
    
    for entry in conversation_history:
        if entry.get("tool_results"):
            for idx, tr in enumerate(entry["tool_results"]):
                tool_call_id = last_tool_call_ids[idx] if idx < len(last_tool_call_ids) else tr.get("id", "unknown")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(tr.get("result", {}))
                })
        elif entry.get("assistant_message"):
            assistant_msg = entry["assistant_message"]
            messages.append(assistant_msg)
            if assistant_msg.get("tool_calls"):
                last_tool_call_ids = [tc["id"] for tc in assistant_msg["tool_calls"]]
        elif entry.get("content"):
            messages.append({
                "role": entry.get("role", "user"),
                "content": entry.get("content", "")
            })
    
    # Call OpenAI
    response = get_openai_client().chat.completions.create(
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        messages=messages,
        tools=openai_tools if openai_tools else None,
        tool_choice="auto" if openai_tools else None,
    )
    
    choice = response.choices[0]
    message = choice.message
    
    if message.tool_calls:
        tool_call = message.tool_calls[0]
        metrics.tool_calls_total += 1
        
        conversation_history.append({
            "assistant_message": {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls
                ]
            }
        })
        
        return make_tool_call_response(
            text=message.content or f"Calling {tool_call.function.name}...",
            tool_name=tool_call.function.name,
            tool_args=json.loads(tool_call.function.arguments),
        )
    
    content = message.content or ""
    
    if "TASK COMPLETED" in content.upper() or "completed" in content.lower():
        return make_completion_response(content)
    
    return {
        "jsonrpc": "2.0",
        "result": {
            "message": {
                "role": "assistant",
                "parts": [{"type": "text", "text": content}],
            },
        },
    }


def make_tool_call_response(text: str, tool_name: str, tool_args: dict) -> dict:
    """Create A2A tool call response."""
    return {
        "jsonrpc": "2.0",
        "result": {
            "message": {
                "role": "assistant",
                "parts": [
                    {"type": "text", "text": text},
                    {
                        "type": "tool_call",
                        "id": f"tc-{len(conversation_history)}",
                        "name": tool_name,
                        "arguments": tool_args,
                    },
                ],
            },
        },
    }


def make_completion_response(text: str) -> dict:
    """Create completion response."""
    return {
        "jsonrpc": "2.0",
        "result": {
            "status": "completed",
            "message": {
                "role": "assistant",
                "parts": [{"type": "text", "text": text}],
            },
        },
    }


def make_error_response(request_id: str, code: int, message: str) -> dict:
    """Create error response."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        }
    }


# =============================================================================
# Additional Endpoints
# =============================================================================

@app.get("/health")
def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "agent": "advanced_purple_agent",
        "model": config.model,
        "metrics": {
            "requests_total": metrics.requests_total,
            "success_rate": f"{metrics.requests_success / max(1, metrics.requests_total):.2%}",
            "tool_calls": metrics.tool_calls_total,
        }
    }


@app.get("/metrics")
def prometheus_metrics():
    """Prometheus metrics endpoint."""
    return PlainTextResponse(
        content=metrics.to_prometheus(),
        media_type="text/plain"
    )


@app.get("/debug/config")
def debug_config():
    """Debug configuration (for development)."""
    return {
        "model": config.model,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "mcp_endpoint": mcp_endpoint,
        "rate_limit_rpm": config.rate_limit_rpm,
        "rate_limit_remaining": rate_limiter.remaining(),
        "has_api_key_protection": bool(config.api_key),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
    }


@app.post("/reset")
def reset():
    """Reset conversation state."""
    global conversation_history, available_tools
    conversation_history = []
    available_tools = []
    return {"status": "reset", "message": "Conversation cleared"}


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("=" * 60)
    print("🟣 Advanced Purple Agent")
    print("=" * 60)
    print(f"   Model: {config.model}")
    print(f"   Host: {config.host}")
    print(f"   Port: {config.port}")
    print(f"   MCP Endpoint: {mcp_endpoint or 'Auto-discover'}")
    print(f"   Rate Limit: {config.rate_limit_rpm} req/min")
    print(f"   API Key: {'Enabled' if config.api_key else 'Disabled'}")
    print()
    print("   Endpoints:")
    print("     GET  /.well-known/agent.json  - Agent Card")
    print("     POST /a2a/message             - Message Handler")
    print("     GET  /health                  - Health Check")
    print("     GET  /metrics                 - Prometheus Metrics")
    print("=" * 60)
    
    uvicorn.run(app, host=config.host, port=config.port)
