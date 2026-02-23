"""
AgentX LangGraph Agent
======================
Benchmark-optimized agent powered by LangChain's create_agent.

Architecture:
- create_agent provides the compiled LangGraph graph with built-in tool loop
- MCPToolLoader handles discovery and conversion of MCP tools
- Middleware stack: retry, summarization, error handling, logging
- LangGraphAgent orchestrates initialization, execution, and lifecycle
"""

import json
import asyncio
import logging
import os
import re
import sys
import traceback
from typing import List, Dict, Any, Optional, Union, Literal

import httpx
from pydantic import BaseModel, Field, create_model
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.agents.middleware import (
    ToolRetryMiddleware,
    ContextEditingMiddleware,
    ClearToolUsesEdit,
    SummarizationMiddleware,
    wrap_tool_call,
    before_model,
)

from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart
from a2a.utils import get_message_text, new_agent_text_message

logger = logging.getLogger(__name__)


# =============================================================================
# MCP Tool Loading
# =============================================================================


class MCPToolLoader:
    """Discover and load MCP tools, converting them to LangChain Tool format.

    Uses Agent Discovery protocol (/.well-known/agent.json) to find tool endpoints,
    with fallback to standard /tools path.
    """

    _TOOL_KEYWORDS = frozenset(["mcp", "tool", "function", "skill"])
    _TOOLS_URL_PATTERN = re.compile(r'https?://[^\s"]+/tools')

    def __init__(self, mcp_endpoint: str):
        self.mcp_endpoint = mcp_endpoint.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._tools_cache: List[StructuredTool] = []
        self.tools_endpoint: Optional[str] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ----- Discovery -----

    async def _discover_tools_endpoint(self) -> str:
        """Resolve the tools endpoint URL via agent card or fallback."""
        client = await self.get_client()

        try:
            resp = await client.get(f"{self.mcp_endpoint}/.well-known/agent.json")
            if resp.status_code == 200:
                card = resp.json()
                print(f"✅ Agent Card: {card.get('name', 'Unknown')}")

                # Explicit tools_url field
                if card.get("tools_url"):
                    return card["tools_url"]

                # Scan card text for tool URLs
                card_text = str(card)
                url_match = self._TOOLS_URL_PATTERN.search(card_text)
                if url_match:
                    return url_match.group(0)

                # Keyword heuristic
                if any(k in card_text.lower() for k in self._TOOL_KEYWORDS):
                    return f"{self.mcp_endpoint}/tools"
            else:
                print(f"⚠️ No Agent Card (HTTP {resp.status_code}), using default /tools")
        except Exception as e:
            print(f"⚠️ Discovery error: {e}")

        return f"{self.mcp_endpoint}/tools"

    # ----- Tool Loading -----

    async def load_tools(self) -> List[StructuredTool]:
        """Fetch MCP tools and convert to LangChain StructuredTools."""
        if self._tools_cache:
            return self._tools_cache

        if not self.tools_endpoint:
            self.tools_endpoint = await self._discover_tools_endpoint()

        url = (
            self.tools_endpoint
            if "://" in self.tools_endpoint
            else f"{self.mcp_endpoint}/{self.tools_endpoint.lstrip('/')}"
        )

        print(f"📥 Loading tools from: {url}")
        client = await self.get_client()

        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                print(f"⚠️ Failed to load tools: HTTP {resp.status_code}")
                return []

            mcp_tools = resp.json().get("tools", [])
            print(f"✅ Loaded {len(mcp_tools)} MCP tools")

            self._tools_cache = [
                self._create_langchain_tool(t, url) for t in mcp_tools
            ]
            return self._tools_cache
        except Exception as e:
            print(f"❌ Error loading tools: {e}")
            return []

    def _create_langchain_tool(self, mcp_tool: Dict, endpoint_url: str) -> StructuredTool:
        """Convert MCP tool definition → LangChain StructuredTool with Pydantic args_schema.

        args_schema exposes the tool's input contract to the LLM so it knows
        exactly which arguments to pass — this is the key driver of argument_score.
        """
        name = mcp_tool.get("name", "")
        description = mcp_tool.get("description", f"Execute {name}")
        input_schema = mcp_tool.get("inputSchema", {})
        call_url = f"{endpoint_url}/call"
        loader = self

        # Build Pydantic model from JSON Schema so LLM sees typed fields
        args_schema = _schema_to_pydantic(name, input_schema)

        async def _execute_async(**kwargs: Any) -> str:
            try:
                client = await loader.get_client()
                resp = await client.post(
                    call_url, json={"name": name, "arguments": kwargs}
                )
                return json.dumps(resp.json(), default=str)
            except Exception as e:
                return json.dumps({"error": str(e)})

        def _execute_sync(**kwargs: Any) -> str:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                # Already inside an event loop (Jupyter / LangGraph) — run in thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, _execute_async(**kwargs))
                    return future.result()
            return asyncio.run(_execute_async(**kwargs))

        return StructuredTool(
            name=name,
            description=description,
            func=_execute_sync,
            coroutine=_execute_async,
            args_schema=args_schema,
        )


def _schema_to_pydantic(tool_name: str, schema: Dict[str, Any]) -> Optional[type[BaseModel]]:
    """Build a Pydantic model from a JSON Schema dict for use as args_schema.

    This is what tells the LLM the exact argument names and types for each tool,
    directly driving argument_score in the benchmark.
    """
    props = schema.get("properties", {})
    if not props:
        # Zero-arg tool: return an empty Pydantic model so LLM sees a valid schema
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", tool_name)
        try:
            return create_model(f"{safe}_args")
        except Exception:
            return None

    required = set(schema.get("required", []))
    _type_map = {"string": str, "integer": int, "number": float, "boolean": bool, "array": list, "object": dict}

    fields: Dict[str, Any] = {}
    for field_name, field_def in props.items():
        # Resolve type — handle anyOf (nullable)
        raw_type = field_def.get("type", "string")
        if "anyOf" in field_def:
            raw_type = next(
                (s.get("type", "string") for s in field_def["anyOf"] if s.get("type") != "null"),
                "string",
            )
        py_type = _type_map.get(raw_type, str)
        desc = field_def.get("description", "")
        default = field_def.get("default", None)

        if field_name in required:
            fields[field_name] = (py_type, Field(..., description=desc))
        else:
            fields[field_name] = (Optional[py_type], Field(default, description=desc))

    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", tool_name)
    try:
        return create_model(f"{safe_name}_args", **fields)
    except Exception:
        return None


# =============================================================================
# Custom Middleware: Tool Error Handler
# =============================================================================


@wrap_tool_call
def _handle_tool_errors(request, handler):
    """Catch tool exceptions and return model-friendly error messages.

    Instead of raw stack traces the LLM sees a short, actionable hint so it
    can retry with different arguments or choose an alternative tool.
    """
    try:
        return handler(request)
    except Exception as e:
        tool_name = request.tool_call.get("name", "unknown")
        error_msg = (
            f"Tool '{tool_name}' failed: {e}. "
            "Check your arguments and try again, or use an alternative approach."
        )
        logger.warning("Tool error [%s]: %s", tool_name, e)
        return ToolMessage(
            content=error_msg,
            tool_call_id=request.tool_call["id"],
        )


# =============================================================================
# Custom Middleware: Observability Logger + Focus Injector
# =============================================================================


@before_model
def _log_model_call(state, runtime):
    """Log context size and inject a dynamic focus reminder before each LLM call.

    - Call 0 (no tool results yet): motivational kickoff
    - Calls 1–N: progress nudge — summarize what's done, push to finish
    - Returns a SystemMessage that gets prepended to the next LLM invocation.
    """
    messages = state.get("messages", [])
    tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
    tool_count = len(tool_msgs)

    logger.info("🧠 LLM call: %d messages (%d tool results)", len(messages), tool_count)

    if tool_count == 0:
        # İlk çağrı — görevi anla ve harekete geç
        hint = (
            "🎯 FOCUS: You are starting a new task. "
            "Read the task carefully, identify exactly what needs to be done, "
            "inspect your available tools, and execute the minimal steps required. "
            "Be precise, be efficient, and deliver a complete result."
        )
    else:
        # Sonraki çağrılar — ne yaptığını özetle, bitirebilirsen bitir
        done = ", ".join(
            dict.fromkeys(  # unique, sıralı
                m.name for m in messages
                if hasattr(m, "name") and m.name and isinstance(m, ToolMessage)
            )
        ) or "some tools"
        hint = (
            f"⚡ PROGRESS ({tool_count} tool call{'s' if tool_count > 1 else ''} so far): "
            f"You have already used: {done}. "
            "Review what you have collected, determine if the task is complete, "
            "and if so write your final answer NOW. "
            "If steps remain, execute only what is strictly necessary — no redundant calls."
        )

    return SystemMessage(content=hint)


# =============================================================================
# System Prompt
# =============================================================================

SYSTEM_PROMPT = """You are a general-purpose AI agent. You may or may not have tools available.

## How to approach any task

1. **Understand first** — read the task carefully. Identify what outcome is expected.
2. **Decide if tools are needed** — if the task requires interacting with external systems (files, emails, APIs, databases, web), use the available tools. If it is a reasoning, writing, math, or knowledge task, answer directly without tools.
3. **Plan minimally** — identify the smallest set of actions needed to complete the task. Do not over-engineer.
4. **Execute precisely**:
   - Always look up IDs, URLs, and resource names using search/list tools before using them — never fabricate values.
   - Pass ALL required arguments to every tool call. Check the tool's schema.
   - Chain outputs: use results from one tool as inputs to the next.
5. **Do not repeat yourself** — if a tool call succeeded, do not call it again with the same arguments. If a resource was already created, do not create it again.
6. **Recover gracefully** — if a tool fails, try once with adjusted arguments. If it fails again, move on and note the failure in your answer.
7. **Stop when done** — once the task is complete, write a clear final answer summarizing what was done and stop calling tools.

## Core principles
- Prefer fewer, targeted actions over many broad ones.
- Never hallucinate data (IDs, emails, URLs, file names). Discover them via tools.
- If no tools are available or needed, reason and answer directly."""


# =============================================================================
# Main Agent Class
# =============================================================================


class LangGraphAgent:
    """LangGraph agent backed by LangChain's create_agent.

    create_agent returns a compiled LangGraph graph with its own internal
    tool-calling loop. We use it *directly* — no extra StateGraph wrapper.

    Features:
    - Single compiled graph (no graph-in-graph nesting)
    - MCP tool discovery and loading
    - Supports OpenAI, local, and custom model backends
    - A2A protocol integration via ``run()``
    """

    def __init__(
        self,
        mcp_endpoint: str,
        model: Union[str, BaseChatModel] = "gpt-4o-mini",
        temperature: float = 0.0,
        model_provider: Literal["openai", "local"] = "openai",
    ):
        self.mcp_endpoint = mcp_endpoint
        self.temperature = temperature

        # Resolve model name & instance
        if isinstance(model, str):
            self.model_name = model
            self.model_instance = None
            self.model_provider = model_provider
        else:
            self.model_name = getattr(model, "model", "custom-model")
            self.model_instance = model
            self.model_provider = "custom"

        self.tool_loader = MCPToolLoader(mcp_endpoint)
        self.graph = None  # CompiledGraph from create_agent
        self.tools: List[StructuredTool] = []

        # Metrics
        self.total_tasks = 0
        self.successful_tasks = 0

    # ----- Initialization -----

    async def initialize(self):
        """Load MCP tools, resolve model, and build the agent graph."""
        print(f"🔧 Initializing LangGraph Agent...")
        print(f"   Model: {self.model_name} ({self.model_provider})")
        print(f"   MCP: {self.mcp_endpoint}")

        self.tools = await self.tool_loader.load_tools()
        print(f"✅ Loaded {len(self.tools)} tools")

        model = self._resolve_model()
        self.graph = self._build_graph(model, self.tools)
        print("✅ Agent ready")

    def _resolve_model(self) -> BaseChatModel:
        """Return the chat model instance based on provider config."""
        if self.model_instance:
            return self.model_instance

        if self.model_provider == "local":
            return self._try_local_model()

        return ChatOpenAI(
            model=self.model_name,
            temperature=self.temperature,
        )

    def _try_local_model(self) -> BaseChatModel:
        """Attempt to load LocalModel (Qwen), fallback to OpenAI."""
        try:
            from pathlib import Path

            project_root = Path(__file__).resolve().parent.parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))

            from custom_qwen import LocalModel

            print("   Using LocalModel (Qwen)")
            return LocalModel(temperature=self.temperature)
        except ImportError as e:
            print(f"⚠️ LocalModel not available, falling back to OpenAI: {e}")
            return ChatOpenAI(
                model=self.model_name,
                temperature=self.temperature,
            )

    @staticmethod
    def _build_graph(model: BaseChatModel, tools: List[StructuredTool]):
        """Create the compiled LangGraph graph via create_agent.

        Middleware stack (executed in order):
        1. _log_model_call      — observability: log context size before each LLM call
        2. SummarizationMiddleware — compress long conversations to stay within context
        3. ToolRetryMiddleware   — retry failed tool calls with jitter + backoff
        4. _handle_tool_errors   — catch unrecoverable tool errors, return friendly msg
        5. ContextEditingMiddleware — prune old tool uses if context grows extreme
        """
        prompt = SYSTEM_PROMPT

        return create_agent(
            model=model,
            tools=tools,
            system_prompt=prompt,
            middleware=[
                _log_model_call,
                SummarizationMiddleware(
                    model="gpt-4o-mini",
                    trigger=[
                        ("tokens", 80_000),
                        ("messages", 50),
                    ],
                    keep=("messages", 20),
                ),
                ToolRetryMiddleware(
                    max_retries=3,
                    backoff_factor=2.0,
                    initial_delay=1.0,
                    max_delay=30.0,
                    jitter=True,
                    retry_on=(ConnectionError, TimeoutError, httpx.HTTPError),
                    on_failure="continue",
                ),
                _handle_tool_errors,
                ContextEditingMiddleware(
                    edits=[
                        ClearToolUsesEdit(trigger=100_000, keep=5),
                    ],
                ),
            ],
        )

    # ----- A2A Execution -----

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        """Execute agent task (A2A interface)."""
        if self.graph is None:
            await self.initialize()

        self.total_tasks += 1
        task_text = get_message_text(message)

        await updater.update_status(
            TaskState.working, new_agent_text_message("Processing...")
        )

        try:
            result = await self.graph.ainvoke(
                {"messages": [HumanMessage(content=task_text)]},
                config={"configurable": {"thread_id": str(self.total_tasks)}},
            )

            final_answer, tool_results = self._extract_results(result)

            response_data = {
                "response": final_answer,
                "tool_calls": tool_results,
                "tool_call_count": len(tool_results),
                "metrics": self.get_metrics(),
            }

            await updater.add_artifact(
                parts=[Part(root=TextPart(text=json.dumps(response_data)))],
                name="Response",
            )
            self.successful_tasks += 1

        except Exception as e:
            logger.error("Task failed: %s\n%s", e, traceback.format_exc())
            await updater.failed(new_agent_text_message(f"Error: {e}"))

    # ----- Result Extraction -----

    @staticmethod
    def _extract_results(result: Dict) -> tuple[str, List[Dict]]:
        """Extract final answer and tool call info from graph output."""
        messages = result.get("messages", [])
        tool_results: List[Dict] = []
        final_answer = ""

        for msg in messages:
            # tool_calls: LangChain returns list of dicts or ToolCall objects
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    if isinstance(tc, dict):
                        name = tc.get("name", "unknown")
                        args = tc.get("args", tc.get("arguments", {}))
                    else:
                        name = getattr(tc, "name", "unknown")
                        args = getattr(tc, "args", {})
                    tool_results.append({"name": name, "arguments": args})

            # Track last non-empty text content as final answer
            content = getattr(msg, "content", None)
            if content and isinstance(content, str) and content.strip():
                final_answer = content
            elif content and isinstance(content, list):
                # Some models return content as list of blocks
                text = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in content
                ).strip()
                if text:
                    final_answer = text

        return final_answer or "Task completed", tool_results

    # ----- Lifecycle -----

    async def close(self):
        """Release resources."""
        await self.tool_loader.close()

    def get_metrics(self) -> Dict:
        total = max(self.total_tasks, 1)
        return {
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "success_rate": f"{(self.successful_tasks / total) * 100:.1f}%",
        }

    def reset(self):
        self.total_tasks = 0
        self.successful_tasks = 0


# =============================================================================
# Exports
# =============================================================================

__all__ = ["LangGraphAgent", "MCPToolLoader", "graph"]


# =============================================================================
# Graph Instance for LangGraph Server
# =============================================================================

graph = None

_is_test_run = any("test" in arg for arg in sys.argv)
if os.getenv("SKIP_AGENT_INIT") != "true" and not _is_test_run:
    try:
        try:
            _loop = asyncio.get_running_loop()
        except RuntimeError:
            _loop = None

        if _loop is None or not _loop.is_running():
            _agent = LangGraphAgent(
                mcp_endpoint="http://localhost:8091",
                model="gpt-4o-mini",
                temperature=0.0,
            )
            asyncio.run(_agent.initialize())
            graph = _agent.graph
    except Exception as e:
        print(f"⚠️ Agent initialization skipped or failed: {e}")
