# src/langgraph_agent.py
"""
AgentX LangGraph Agent - Single Graph (create_agent) + Raw MCP Tools
===================================================================

Goal: Use MCP tools "as-is" (no schema normalization/sanitization).
- Reads /tools from MCP HTTP server
- Calls /tools/call
- create_agent provides the LangGraph loop (single graph)

Important:
- No required/optional fixes
- No enum/nested schema improvements
- Tool functions are bound safely (no closure bug)
- LAZY INIT + retry/backoff (fixes CI/Docker startup race with MCP)
"""

import json
import asyncio
import random
from typing import Any, Dict, List, Optional, Union, Literal
from pathlib import Path

import httpx
import anyio
from pydantic import BaseModel, Field, create_model

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ToolRetryMiddleware,
    ContextEditingMiddleware,
    ClearToolUsesEdit,
    ToolCallLimitMiddleware,
    ModelCallLimitMiddleware,
)

from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart
from a2a.utils import get_message_text, new_agent_text_message


SYSTEM_PROMPT = """You are a highly capable AI assistant with access to a wide range of tools.

Your Goal: Complete the user's request accurately by chaining the necessary tools in the correct order.

Instructions:
1. PLAN: Before taking action, analyze the request. Break it down into logical steps.
2. SEARCH: If you need to find a resource, use the appropriate search tool first. Do not hallucinate IDs or paths.
3. EXECUTE: Call tools one by one. Check tool output before proceeding.
4. ARGUMENTS: Be precise with tool arguments. If a tool requires an ID, obtain it from a previous tool call.
5. RELIABILITY: Prefer small, verifiable steps. If a tool fails, retry or adapt.

Tools available: {tool_names}
Be persistent and thorough. Do not give up easily.
"""


# =============================================================================
# "Raw" schema -> minimal args_schema
# (NO normalization; just best-effort to help LangChain pass kwargs)
# =============================================================================

_JSON_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def raw_schema_to_args_schema(tool_name: str, raw_schema: Dict[str, Any]) -> type[BaseModel]:
    """
    Convert MCP inputSchema to a minimal Pydantic model WITHOUT modifying required/optional semantics.
    - If schema is missing/empty -> fallback to {"input": str}
    - Types are best-effort (no enum/nested recursion)
    """
    raw_schema = raw_schema or {}
    props: Dict[str, Any] = raw_schema.get("properties") or {}
    required: List[str] = raw_schema.get("required") or []

    if not props:
        return create_model(
            f"{tool_name}_Args",
            input=(str, Field(..., description="Tool input")),
        )  # type: ignore

    fields: Dict[str, Any] = {}
    for k, v in props.items():
        v = v or {}
        t = v.get("type", "string")
        py_t = _JSON_TYPE_MAP.get(t, Any)

        # Best-effort arrays (do not attempt item typing)
        if t == "array":
            py_t = list

        desc = v.get("description") or ""
        default = ... if (k in required) else None
        fields[k] = (py_t, Field(default=default, description=desc))

    return create_model(f"{tool_name}_Args", **fields)  # type: ignore


# =============================================================================
# MCP Tool Loader (HTTP)
# =============================================================================

class MCPToolLoader:
    """
    Loads MCP tools from an HTTP MCP server that exposes:
      GET  /tools      -> {"tools":[{name, description, inputSchema, ...}]}
      POST /tools/call -> {name, arguments} -> JSON result
    """

    def __init__(self, mcp_endpoint: str):
        self.mcp_endpoint = mcp_endpoint.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._tools_cache: List[StructuredTool] = []
        self.tools_url = f"{self.mcp_endpoint}/tools"
        self.call_url = f"{self.mcp_endpoint}/tools/call"

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _make_tool(self, name: str, description: str, args_schema: type[BaseModel]) -> StructuredTool:
        """
        Factory to avoid Python closure bugs in loops.
        Uses call_url fixed for this MCP server.
        """
        call_url = self.call_url

        async def _arun_tool(**kwargs) -> str:
            try:
                client = await self.get_client()
                r = await client.post(call_url, json={"name": name, "arguments": kwargs})
                r.raise_for_status()
                try:
                    return json.dumps(r.json(), ensure_ascii=False, default=str)
                except Exception:
                    return r.text
            except Exception as e:
                return json.dumps({"error": str(e), "tool": name}, ensure_ascii=False)

        def _run_tool(**kwargs) -> str:
            # Loop-safe: run async tool in anyio
            try:
                return anyio.from_thread.run(_arun_tool, **kwargs)
            except RuntimeError:
                return anyio.run(_arun_tool, **kwargs)

        return StructuredTool(
            name=name,
            description=description,
            args_schema=args_schema,
            func=_run_tool,
            coroutine=_arun_tool,
        )

    async def load_tools(self) -> List[StructuredTool]:
        if self._tools_cache:
            return self._tools_cache

        client = await self.get_client()
        r = await client.get(self.tools_url)
        r.raise_for_status()

        data = r.json()
        mcp_tools = data.get("tools") or []

        tools: List[StructuredTool] = []
        for t in mcp_tools:
            name = t.get("name") or ""
            description = t.get("description") or f"Execute {name}"
            raw_schema = t.get("inputSchema") or {}

            # Use schema as-is (no normalization)
            args_schema = raw_schema_to_args_schema(name, raw_schema)

            tools.append(self._make_tool(name, description, args_schema))

        self._tools_cache = tools
        return tools


# =============================================================================
# Agent
# =============================================================================

class LangGraphAgent:
    """
    Single graph agent using LangChain's create_agent (LangGraph loop).
    Tools are loaded as-is from MCP HTTP server.

    Key: LAZY INIT + retry/backoff to avoid CI/Docker race.
    """

    def __init__(
        self,
        mcp_endpoint: str,
        model: Union[str, BaseChatModel] = "gpt-4o-mini",
        temperature: float = 0.0,
        model_provider: Literal["openai", "local"] = "openai",
        enable_limits: bool = True,
        enable_context_editing: bool = True,
        enable_tool_retry: bool = True,
        debug: bool = False,
        # init/retry knobs
        init_max_attempts: int = 18,
        init_backoff_cap_s: float = 8.0,
    ):
        self.mcp_endpoint = mcp_endpoint
        self.temperature = temperature
        self.model_provider = model_provider
        self.debug = debug

        if isinstance(model, str):
            self.model_name = model
            self.model_instance = None
        else:
            self.model_name = getattr(model, "model", "custom-model")
            self.model_instance = model
            self.model_provider = "custom"

        self.tool_loader = MCPToolLoader(mcp_endpoint)
        self.tools: List[StructuredTool] = []
        self.graph = None
        self.model: Optional[BaseChatModel] = None

        self.enable_limits = enable_limits
        self.enable_context_editing = enable_context_editing
        self.enable_tool_retry = enable_tool_retry

        self.total_tasks = 0
        self.successful_tasks = 0

        # lazy init
        self._initialized = False
        self._init_lock = asyncio.Lock()

        # retry config
        self.init_max_attempts = init_max_attempts
        self.init_backoff_cap_s = init_backoff_cap_s

    async def ensure_initialized(self):
        if self._initialized and self.graph is not None:
            return

        async with self._init_lock:
            if self._initialized and self.graph is not None:
                return

            await self.initialize()
            self._initialized = True

    async def initialize(self):
        # 1) tools: retry/backoff for MCP readiness
        last_err: Optional[Exception] = None
        for attempt in range(1, self.init_max_attempts + 1):
            try:
                self.tools = await self.tool_loader.load_tools()
                if self.tools:
                    break
            except Exception as e:
                last_err = e

            # exponential backoff + small jitter
            sleep_s = min(2 ** (attempt - 1), self.init_backoff_cap_s) + random.uniform(0, 0.35)
            await asyncio.sleep(sleep_s)

        if not self.tools:
            raise RuntimeError(f"MCP tools not available after retries: {last_err}")

        # 2) model
        if self.model_instance:
            self.model = self.model_instance
        elif self.model_provider == "local":
            try:
                import sys
                project_root = Path(__file__).resolve().parent.parent.parent
                if str(project_root) not in sys.path:
                    sys.path.insert(0, str(project_root))
                from custom_qwen import LocalModel
                self.model = LocalModel(temperature=self.temperature)
            except Exception:
                self.model = ChatOpenAI(model=self.model_name, temperature=self.temperature)
        else:
            self.model = ChatOpenAI(model=self.model_name, temperature=self.temperature)

        # 3) middleware
        middleware = []

        if self.enable_tool_retry:
            middleware.append(
                ToolRetryMiddleware(
                    max_retries=3,
                    backoff_factor=2.0,
                    initial_delay=1.0,
                )
            )

        if self.enable_context_editing:
            middleware.append(
                ContextEditingMiddleware(
                    edits=[ClearToolUsesEdit(trigger=100000, keep=3)],
                )
            )

        if self.enable_limits:
            middleware.append(ModelCallLimitMiddleware(run_limit=25, exit_behavior="end"))
            middleware.append(ToolCallLimitMiddleware(run_limit=25, exit_behavior="continue"))

        # 4) prompt + graph
        tool_names = ", ".join([t.name for t in self.tools])
        formatted_prompt = SYSTEM_PROMPT.replace("{tool_names}", tool_names)

        self.graph = create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=formatted_prompt,
            middleware=middleware,
            debug=self.debug,
            name="agentx-purple-agent",
        )

    @staticmethod
    def _extract(messages: List[Any]) -> Dict[str, Any]:
        tool_calls: List[Dict[str, Any]] = []
        final_answer = ""

        for msg in messages:
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    tool_calls.append(
                        {
                            "name": tc.get("name", "unknown"),
                            "arguments": tc.get("args", {}),
                        }
                    )

        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and (msg.content or "").strip() and not getattr(msg, "tool_calls", None):
                final_answer = msg.content
                break

        if not final_answer:
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and (msg.content or "").strip():
                    final_answer = msg.content
                    break

        return {"final_answer": final_answer or "Task completed", "tool_calls": tool_calls}

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        await self.ensure_initialized()

        self.total_tasks += 1
        task_text = get_message_text(message)

        await updater.update_status(TaskState.working, new_agent_text_message("Processing..."))

        try:
            result = await asyncio.to_thread(
                self.graph.invoke,  # type: ignore[union-attr]
                {"messages": [HumanMessage(content=task_text)]},
                {"configurable": {"thread_id": str(self.total_tasks)}},
            )

            messages = result.get("messages", []) if isinstance(result, dict) else []
            extracted = self._extract(messages)

            response_data = {
                "response": extracted["final_answer"],
                "tool_calls": extracted["tool_calls"],
                "tool_call_count": len(extracted["tool_calls"]),
                "metrics": {
                    "total_tasks": self.total_tasks,
                    "success_rate": f"{(self.successful_tasks / max(self.total_tasks, 1)) * 100:.1f}%",
                },
            }

            await updater.add_artifact(
                parts=[Part(root=TextPart(text=json.dumps(response_data, ensure_ascii=False)))],
                name="Response",
            )

            self.successful_tasks += 1

        except Exception as e:
            await updater.update_status(TaskState.failed, new_agent_text_message(f"Error: {e}"))
            raise

    async def close(self):
        await self.tool_loader.close()

    def get_metrics(self) -> Dict[str, Any]:
        return {
            "initialized": self._initialized,
            "tools_count": len(self.tools),
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "success_rate": f"{(self.successful_tasks / max(self.total_tasks, 1)) * 100:.1f}%",
        }

    def reset(self):
        self.total_tasks = 0
        self.successful_tasks = 0


# =============================================================================
# Exports for imports (NO import-time init)
# =============================================================================

agent = LangGraphAgent(
    mcp_endpoint="http://localhost:8091",
    model="gpt-4o-mini",
    temperature=0.0,
    enable_limits=True,
    enable_context_editing=True,
    enable_tool_retry=True,
    debug=False,
)

# Some frameworks want "graph" symbol; we keep it None (lazy init fills agent.graph)
graph = None

__all__ = ["LangGraphAgent", "MCPToolLoader", "agent", "graph"]
