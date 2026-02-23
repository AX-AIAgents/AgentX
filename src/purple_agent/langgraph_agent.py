"""
AgentX LangGraph Agent
======================
Plan-and-Execute graph:
  planner  → her zaman çalışır, tool olsa da olmasa da
  executor → planı uygular; tool varsa kullanır, yoksa muhakeme eder
"""

import asyncio
import json
import logging
import os
import re
import sys
import traceback
from typing import Annotated, Any, Dict, List, Literal, Optional, Sequence, Union

import httpx
from pydantic import BaseModel, Field, create_model
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.agents.middleware import (
    ContextEditingMiddleware,
    ClearToolUsesEdit,
    SummarizationMiddleware,
    ToolRetryMiddleware,
    before_model,
    wrap_tool_call,
)
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from a2a.server.tasks import TaskUpdater
from a2a.types import Message, Part, TaskState, TextPart
from a2a.utils import get_message_text, new_agent_text_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Runtime config — scenario.toml → Docker env → burası
# ---------------------------------------------------------------------------
# Nasıl ayarlanır (scenario.toml → participants.env):
#   AGENT_MAX_ITERATIONS = "25"   # create_agent iç loop sınırı (tool round-trip sayısı)
#   AGENT_TURN_TIMEOUT   = "60"   # turn başına max süre (saniye); AX-Bench ~70s
# ---------------------------------------------------------------------------
_MAX_ITERATIONS: int = int(os.getenv("AGENT_MAX_ITERATIONS", "50"))
_TURN_TIMEOUT: float = float(os.getenv("AGENT_TURN_TIMEOUT", "60"))

logger.info("Config | max_iterations=%d  turn_timeout=%.0fs", _MAX_ITERATIONS, _TURN_TIMEOUT)


# ---------------------------------------------------------------------------
# JSON Schema → Pydantic (args_schema — LLM'e zorunlu argümanları öğretir)
# ---------------------------------------------------------------------------

_TYPE_MAP: Dict[str, type] = {
    "string": str, "integer": int, "number": float,
    "boolean": bool, "array": list, "object": dict,
}


def _resolve_type(prop: Dict[str, Any]) -> type:
    """anyOf / type alanlarını Python tipine çevirir."""
    if "anyOf" in prop:
        # anyOf içindeki null olmayan ilk tipi al
        for sub in prop["anyOf"]:
            if sub.get("type") != "null":
                return _TYPE_MAP.get(sub.get("type", "string"), str)
        return str
    return _TYPE_MAP.get(prop.get("type", "string"), str)


# Pydantic model isimlerinde sadece alfanümerik + _ kullanılabilir
_INVALID_CHARS_RE = re.compile(r"[^a-zA-Z0-9_]")


def _to_pydantic(name: str, schema: Dict[str, Any]) -> Optional[type[BaseModel]]:
    props = schema.get("properties", {})
    if not props:
        return None
    required = set(schema.get("required", []))
    fields = {}
    for k, v in props.items():
        py_type = _resolve_type(v)
        desc = v.get("description", "")
        if k in required:
            fields[k] = (py_type, Field(..., description=desc))
        else:
            default = v.get("default", None)
            fields[k] = (Optional[py_type], Field(default, description=desc))
    safe_name = _INVALID_CHARS_RE.sub("_", name)
    return create_model(f"{safe_name}_args", **fields)


# ---------------------------------------------------------------------------
# MCP Tool Loader
# ---------------------------------------------------------------------------

class MCPToolLoader:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._cache: List[StructuredTool] = []

    async def _http(self) -> httpx.AsyncClient:
        if not self._client or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def load(self, force: bool = False) -> List[StructuredTool]:
        if self._cache and not force:
            return self._cache
        tools_url = f"{self.endpoint}/tools"
        call_url  = f"{self.endpoint}/tools/call"
        try:
            c = await self._http()
            r = await c.get(tools_url, timeout=10.0)
            if r.status_code != 200:
                logger.warning("Tool load HTTP %d", r.status_code)
                return self._cache  # keep previous if any
            raw = r.json().get("tools", [])
            self._cache = [_make_tool(t, call_url, self) for t in raw]
            logger.info("Loaded %d tools", len(self._cache))
        except Exception as e:
            logger.error("Tool load: %s", e)
        return self._cache


def _make_tool(raw: Dict, call_url: str, loader: MCPToolLoader) -> StructuredTool:
    name = raw.get("name", "")

    async def _run(**kwargs: Any) -> str:
        try:
            c = await loader._http()
            r = await c.post(call_url, json={"name": name, "arguments": kwargs})
            return json.dumps(r.json(), default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})

    return StructuredTool(
        name=name,
        description=raw.get("description", f"Execute {name}"),
        func=lambda **kw: asyncio.run(_run(**kw)),
        coroutine=_run,
        args_schema=_to_pydantic(name, raw.get("inputSchema", {})),
    )


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

@wrap_tool_call
def _on_tool_error(request, handler):
    try:
        return handler(request)
    except Exception as e:
        name = request.tool_call.get("name", "unknown")
        logger.warning("Tool error [%s]: %s", name, e)
        return ToolMessage(
            content=f"Tool '{name}' failed: {e}. Try different arguments or another tool.",
            tool_call_id=request.tool_call["id"],
        )


@before_model
def _log_llm(state, runtime) -> None:
    msgs = state.get("messages", [])
    tool_result_count = sum(1 for m in msgs if isinstance(m, ToolMessage))
    logger.info("LLM call | msgs=%d tool_results=%d", len(msgs), tool_result_count)

    # Eşiğe yaklaşınca modele "dur ve özetle" uyarısı enjekte et.
    # Bu sistem mesajı modelin bir sonraki çağrısında context'e girer.
    warning_threshold = max(1, _MAX_ITERATIONS // 3)
    if tool_result_count >= warning_threshold:
        remaining = _MAX_ITERATIONS // 3 - (tool_result_count - warning_threshold)
        logger.warning("⚠️ Tool call budget %d/%d — injecting stop warning", tool_result_count, _MAX_ITERATIONS // 3)
        return SystemMessage(
            content=(
                f"⚠️ BUDGET WARNING: You have made {tool_result_count} tool calls. "
                f"You must complete the task NOW. Stop calling tools and write your final answer summarizing what you have done."
            )
        )
    return None


def _build_middleware(summarizer: str) -> list:
    return [
        _log_llm,
        SummarizationMiddleware(
            model=summarizer,
            trigger=[("tokens", 80_000), ("messages", 40)],
            keep=("messages", 20),
        ),
        ToolRetryMiddleware(
            max_retries=3, backoff_factor=2.0,
            initial_delay=1.0, max_delay=30.0, jitter=True,
            retry_on=(ConnectionError, TimeoutError, httpx.HTTPError),
            on_failure="continue",
        ),
        _on_tool_error,
        ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=100_000, keep=5)]),
    ]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_PLANNER_PROMPT = """\
You are a strategic planner. Analyze the task and produce a concise step-by-step plan.

Rules:
- Keep the plan SHORT: maximum 6 steps. Combine related actions into one step.
- If tools are available, reference them by name in each step.
- If no tools are available, plan using reasoning only.
- Output ONLY a JSON array of step strings. No markdown, no extra text.

Example with tools:
["search Google Drive for project reports", "createGoogleDoc summarizing key findings",
 "draft_email to team with doc link"]

Example without tools:
["Analyze the question carefully", "Structure a clear and complete answer"]
"""

_EXECUTOR_PROMPT = """\
You are a precise execution engine. Follow the plan below exactly.

Plan:
{plan}

CRITICAL RULES:
1. Execute each step in order using the available tools.
2. SEARCH/LIST before using any ID or URL — never guess or hallucinate values.
   Chain outputs: use IDs/URLs from one tool's result as input to the next.
3. Always provide ALL required arguments to every tool call.
4. On error: try once with adjusted arguments, then move on.
5. BE EFFICIENT: complete the entire plan in at most {max_tool_calls} tool calls total.
   When you have completed all plan steps, STOP calling tools and write your final answer.
6. STOP CONDITION: After {max_tool_calls} tool calls, you MUST stop and summarize results.
"""


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    plan: List[str]


def _planner_node(model: BaseChatModel, tools: List[StructuredTool]):
    tool_catalog = (
        "\n".join(f"- {t.name}: {t.description[:120]}" for t in tools)
        if tools else "No tools available — plan using reasoning only."
    )

    async def planner(state: AgentState) -> Dict:
        # Tüm konuşma geçmişinden task mesajını çıkar
        history = list(state.get("messages", []))
        user_msg = next((m for m in reversed(history) if isinstance(m, HumanMessage)), None)
        if not user_msg:
            return {"plan": ["Answer the task directly."]}

        # Planner'a geçmiş konuşmayı + planning talimatını ver
        # Geçmiş: multi-turn context'i taşır (önceki AI yanıtları, tool sonuçları)
        planner_history = [
            *history,
            HumanMessage(content=(
                f"{_PLANNER_PROMPT}\n\nAvailable tools:\n{tool_catalog}"
                f"\n\nTask: {user_msg.content}"
            )),
        ]
        resp = await model.ainvoke(planner_history)

        try:
            plan = json.loads(resp.content)
            if not isinstance(plan, list):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            plan = [resp.content.strip()]

        logger.info("Plan (%d steps): %s", len(plan), plan)
        return {"plan": plan}

    return planner


def _executor_node(model: BaseChatModel, tools: List[StructuredTool], summarizer: str):
    middleware = _build_middleware(summarizer)

    async def executor(state: AgentState) -> Dict:
        plan = state.get("plan", [])
        plan_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(plan)) if plan else "No plan."

        agent = create_agent(
            model=model,
            tools=tools,
            system_prompt=_EXECUTOR_PROMPT.format(
                plan=plan_text,
                max_tool_calls=_MAX_ITERATIONS // 3,
            ),
            middleware=middleware,
        )

        history = list(state.get("messages", []))
        if not history:
            history = [HumanMessage(content="Complete the task.")]

        try:
            result = await agent.ainvoke(
                {"messages": history},
                config={"recursion_limit": _MAX_ITERATIONS},
            )
        except Exception as e:
            if "recursion" in str(e).lower() or "GRAPH_RECURSION_LIMIT" in str(e):
                logger.warning("Executor hit recursion limit — returning messages collected so far")
                # history zaten tüm toplanmış mesajları içeriyor; boş new_msgs dön
                return {"messages": []}
            raise

        history_ids = {id(m) for m in history}
        new_msgs = [m for m in result.get("messages", []) if id(m) not in history_ids]
        return {"messages": new_msgs}

    return executor


def build_graph(model: BaseChatModel, tools: List[StructuredTool], summarizer: str = "gpt-4o-mini"):
    g = StateGraph(AgentState)
    g.add_node("planner", _planner_node(model, tools))
    g.add_node("executor", _executor_node(model, tools, summarizer))
    g.set_entry_point("planner")
    g.add_edge("planner", "executor")
    g.add_edge("executor", END)
    return g.compile()


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

def _final_answer(messages: Sequence[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return "Task completed"


def _tool_calls(messages: Sequence[BaseMessage]) -> List[Dict]:
    return [
        {"name": tc.get("name", "unknown"), "arguments": tc.get("args", {})}
        for msg in messages
        if hasattr(msg, "tool_calls") and msg.tool_calls
        for tc in msg.tool_calls
    ]


# ---------------------------------------------------------------------------
# LangGraphAgent
# ---------------------------------------------------------------------------

class LangGraphAgent:
    def __init__(
        self,
        mcp_endpoint: str,
        model: Union[str, BaseChatModel] = "gpt-4o-mini",
        temperature: float = 0.0,
        model_provider: Literal["openai", "local"] = "openai",
    ):
        self.mcp_endpoint = mcp_endpoint
        self.temperature = temperature
        self.model_name = model if isinstance(model, str) else getattr(model, "model", "custom")
        self.model_provider = model_provider if isinstance(model, str) else "custom"
        self._model_instance: Optional[BaseChatModel] = None if isinstance(model, str) else model

        self.loader = MCPToolLoader(mcp_endpoint)
        self.graph = None
        self.tools: List[StructuredTool] = []
        self.total_tasks = 0
        self.successful_tasks = 0

    async def initialize(self, force: bool = False):
        """Load tools and (re)build graph. force=True skips cache."""
        self.tools = await self.loader.load(force=force)
        self.graph = build_graph(self._model(), self.tools)
        print(f"✅ Loaded {len(self.tools)} tools from MCP")
        logger.info("Agent ready — %d tools", len(self.tools))

    def _model(self) -> BaseChatModel:
        if self._model_instance:
            return self._model_instance
        if self.model_provider == "local":
            try:
                from pathlib import Path
                root = Path(__file__).resolve().parent.parent.parent
                if str(root) not in sys.path:
                    sys.path.insert(0, str(root))
                from custom_qwen import LocalModel
                return LocalModel(temperature=self.temperature)
            except ImportError as e:
                logger.warning("LocalModel unavailable, falling back to OpenAI: %s", e)
        return ChatOpenAI(model=self.model_name, temperature=self.temperature)

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        # Initialize if never done, OR re-init if tools failed to load last time
        if not self.graph or not self.tools:
            await self.initialize(force=True)

        self.total_tasks += 1
        await updater.update_status(TaskState.working, new_agent_text_message("Planning…"))

        try:
            result = await asyncio.wait_for(
                self.graph.ainvoke(
                    {"messages": [HumanMessage(content=get_message_text(message))], "plan": []},
                    config={
                        "configurable": {"thread_id": f"task-{self.total_tasks}"},
                        "recursion_limit": _MAX_ITERATIONS,
                    },
                ),
                timeout=_TURN_TIMEOUT,
            )
            msgs = result.get("messages", [])
            calls = _tool_calls(msgs)
            await updater.add_artifact(
                parts=[Part(root=TextPart(text=json.dumps({
                    "response": _final_answer(msgs),
                    "tool_calls": calls,
                    "tool_call_count": len(calls),
                    "metrics": self.get_metrics(),
                })))],
                name="Response",
            )
            self.successful_tasks += 1
            # Explicitly signal completion — required by A2A protocol
            await updater.complete()
        except asyncio.TimeoutError:
            logger.warning("Task %d timed out after %.0fs — returning partial result", self.total_tasks, _TURN_TIMEOUT)
            await updater.complete()
        except Exception as e:
            logger.error("Task failed: %s\n%s", e, traceback.format_exc())
            await updater.failed(new_agent_text_message(f"Error: {e}"))

    async def close(self):
        await self.loader.close()

    def get_metrics(self) -> Dict:
        total = max(self.total_tasks, 1)
        return {
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "success_rate": f"{self.successful_tasks / total * 100:.1f}%",
        }

    def reset(self):
        self.total_tasks = 0
        self.successful_tasks = 0


# ---------------------------------------------------------------------------
# Module-level exports
# ---------------------------------------------------------------------------

__all__ = ["LangGraphAgent", "MCPToolLoader"]
