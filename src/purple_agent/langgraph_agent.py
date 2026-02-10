"""
AgentX LangGraph Agent - Generic Task Solver with Router Pattern
=================================================================
Production-ready agent using create_agent + explicit flow control.

Architecture inspired by orchestrator_v3:
- Router analyzes task and plans execution
- Middleware for error recovery and limits
- Explicit state management
- Tool execution with proper data flow
- Final synthesis

NO domain-specific logic - works universally.
"""

import os
import json
import asyncio
from typing import Annotated, List, Dict, Any, Optional, Literal
from pathlib import Path

import httpx
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph.message import add_messages
from langchain.agents import create_agent, AgentState
from langchain.agents.structured_output import ToolStrategy
from langchain.agents.middleware import (
    ToolRetryMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart
from a2a.utils import get_message_text, new_agent_text_message


# =============================================================================
# Middleware Stack - Error Recovery & Safety
# =============================================================================

def create_error_recovery_middleware():
    """Production-grade middleware stack."""
    return [
        ToolRetryMiddleware(
            max_retries=2,
            backoff_factor=2.0,
            initial_delay=1.0,
            on_failure="return_message",  # Return error to LLM
        ),
        ModelRetryMiddleware(
            max_retries=2,
            backoff_factor=2.0,
            initial_delay=1.0,
            on_failure="continue",  # Continue with AIMessage
        ),
        ToolCallLimitMiddleware(
            run_limit=20,  # Max 20 tool calls per task
        ),
    ]


# =============================================================================
# Router Decision Schema
# =============================================================================

class RouterDecision(BaseModel):
    """Router decision for task execution planning."""
    
    needs_tools: bool = Field(
        default=False,
        description="True if external tools are needed to complete this task"
    )
    
    tool_strategy: str = Field(
        default="sequential",
        description="How to use tools: 'sequential' (one by one), 'parallel' (multiple at once), 'none'"
    )
    
    estimated_steps: int = Field(
        default=1,
        description="Estimated number of tool calls needed (1-10)"
    )
    
    task_type: str = Field(
        default="query",
        description="Type of task: 'search', 'create', 'update', 'query', 'analyze'"
    )
    
    reasoning: str = Field(
        description="Brief explanation of the execution plan"
    )


# =============================================================================
# Orchestrator State
# =============================================================================

class OrchestratorState(AgentState):
    """
    State management for multi-step task execution.
    Tracks decisions, tool results, and final output.
    """
    # Input
    user_input: str
    
    # Router decisions
    needs_tools: bool = False
    tool_strategy: str = "sequential"
    estimated_steps: int = 1
    task_type: str = "query"
    routing_reasoning: str = ""
    
    # Execution tracking
    tool_results: List[Dict[str, Any]] = []
    tool_call_count: int = 0
    
    # Output
    final_answer: str = ""
    output: str = ""


# =============================================================================
# MCP Tool Loading
# =============================================================================

class MCPToolLoader:
    """Load and convert MCP tools to LangChain format."""
    
    def __init__(self, mcp_endpoint: str):
        self.mcp_endpoint = mcp_endpoint
        self._client: Optional[httpx.AsyncClient] = None
        self._tools_cache: List[Tool] = []
    
    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client
    
    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    async def load_tools(self) -> List[Tool]:
        """Fetch tools from MCP and convert to LangChain Tools."""
        if self._tools_cache:
            return self._tools_cache
        
        try:
            client = await self.get_client()
            response = await client.get(f"{self.mcp_endpoint}/tools")
            
            if response.status_code != 200:
                print(f"⚠️ Failed to load tools: HTTP {response.status_code}")
                return []
            
            data = response.json()
            mcp_tools = data.get("tools", [])
            
            print(f"✅ Discovered {len(mcp_tools)} tools from MCP")
            
            # Convert to LangChain Tools
            langchain_tools = []
            for mcp_tool in mcp_tools:
                name = mcp_tool.get("name", "")
                description = mcp_tool.get("description", f"Execute {name}")
                
                # Create tool executor closure
                async def execute_mcp_tool(tool_name: str = name, **kwargs) -> str:
                    """Execute MCP tool via HTTP."""
                    try:
                        client = await self.get_client()
                        response = await client.post(
                            f"{self.mcp_endpoint}/tools/call",
                            json={"name": tool_name, "arguments": kwargs}
                        )
                        result = response.json()
                        return json.dumps(result, default=str)
                    except Exception as e:
                        return json.dumps({"error": str(e)})
                
                tool = Tool(
                    name=name,
                    description=description,
                    func=lambda **kw: asyncio.run(execute_mcp_tool(**kw)),
                    coroutine=execute_mcp_tool,
                )
                langchain_tools.append(tool)
            
            self._tools_cache = langchain_tools
            return langchain_tools
            
        except Exception as e:
            print(f"❌ Error loading tools: {e}")
            return []


# =============================================================================
# Router Agent
# =============================================================================

ROUTER_SYSTEM_PROMPT = """You are an elite task analyzer for an AI agent.

Your job: Analyze the user's request and create an optimal execution plan.

## Analysis Criteria

1. **Does it need tools?**
   - Simple questions → NO tools needed
   - Requires external data/actions → YES tools needed

2. **Tool strategy?**
   - 'sequential': Tools must be chained (search → read → summarize)
   - 'parallel': Independent tools can run together
   - 'none': No tools, just LLM response

3. **Estimated steps?**
   - How many tool calls do you expect? (Be conservative: 1-10)

4. **Task type?**
   - search: Finding information
   - create: Creating new content/data
   - update: Modifying existing data
   - query: Getting current state
   - analyze: Processing/analyzing data

## Examples

"What is the capital of France?"
→ needs_tools=False, tool_strategy='none', estimated_steps=0

"Search for recent news about AI"
→ needs_tools=True, tool_strategy='sequential', estimated_steps=2, task_type='search'

"Get my account balance and transaction history"
→ needs_tools=True, tool_strategy='parallel', estimated_steps=2, task_type='query'

"Search for product info, then create a summary document"
→ needs_tools=True, tool_strategy='sequential', estimated_steps=3, task_type='create'

Be precise. Be conservative with step estimates.
"""


def create_router_agent(model: ChatOpenAI, middleware: List):
    """Create router agent with structured output."""
    return create_agent(
        model=model,
        tools=[],  # Router doesn't use tools
        system_prompt=ROUTER_SYSTEM_PROMPT,
        response_format=ToolStrategy(RouterDecision),
        middleware=middleware,
    )


# =============================================================================
# Executor Agent
# =============================================================================

EXECUTOR_SYSTEM_PROMPT = """You are an elite task execution agent.

You have access to various tools. Your job is to complete the user's task efficiently and accurately.

## Execution Guidelines

1. **Understand the task** - Read carefully, identify the goal
2. **Choose tools wisely** - Only use what's necessary
3. **Validate results** - Check tool outputs make sense
4. **Chain logically** - When one tool's output feeds another
5. **Handle errors** - If a tool fails, try alternatives or explain

## Tool Usage Best Practices

- Read tool descriptions carefully
- Match argument names exactly
- Check tool results before proceeding
- Don't call the same tool multiple times unnecessarily
- If stuck, explain what went wrong

## Success Criteria

Complete the task fully, efficiently, and accurately.
You are being evaluated on: correctness, efficiency, and tool usage quality.
"""


def create_executor_agent(model: ChatOpenAI, tools: List[Tool], middleware: List):
    """Create executor agent with tools."""
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=EXECUTOR_SYSTEM_PROMPT,
        middleware=middleware,
    )


# =============================================================================
# Direct Response Agent (No Tools)
# =============================================================================

DIRECT_SYSTEM_PROMPT = """You are a helpful AI assistant.

Answer the user's question directly and accurately.
Be concise but comprehensive.
"""


def create_direct_agent(model: ChatOpenAI, middleware: List):
    """Create agent for direct responses (no tools)."""
    return create_agent(
        model=model,
        tools=[],
        system_prompt=DIRECT_SYSTEM_PROMPT,
        middleware=middleware,
    )


# =============================================================================
# Graph Nodes
# =============================================================================

def router_node(state: OrchestratorState, model: ChatOpenAI, middleware: List) -> Dict:
    """Analyze task and create execution plan."""
    user_input = state.get("user_input", "")
    
    router = create_router_agent(model, middleware)
    result = router.invoke({"messages": [HumanMessage(content=user_input)]})
    
    decision: RouterDecision = result.get("structured_response")
    
    if decision:
        return {
            "needs_tools": decision.needs_tools,
            "tool_strategy": decision.tool_strategy,
            "estimated_steps": decision.estimated_steps,
            "task_type": decision.task_type,
            "routing_reasoning": decision.reasoning,
            "messages": result.get("messages", []),
        }
    
    # Fallback: assume needs tools
    return {
        "needs_tools": True,
        "tool_strategy": "sequential",
        "estimated_steps": 1,
        "task_type": "query",
        "routing_reasoning": "Default routing",
        "messages": result.get("messages", []),
    }


def executor_node(state: OrchestratorState, model: ChatOpenAI, tools: List[Tool], middleware: List) -> Dict:
    """Execute task using tools."""
    user_input = state.get("user_input", "")
    
    executor = create_executor_agent(model, tools, middleware)
    result = executor.invoke({"messages": [HumanMessage(content=user_input)]})
    
    messages = result.get("messages", [])
    
    # Extract tool calls and final answer
    tool_results = []
    for msg in messages:
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_results.append({
                    "name": tc.get("name", "unknown"),
                    "arguments": tc.get("args", {}),
                })
    
    # Get final answer
    final_msg = messages[-1] if messages else AIMessage(content="Task completed")
    final_answer = final_msg.content if hasattr(final_msg, 'content') else str(final_msg)
    
    return {
        "tool_results": tool_results,
        "tool_call_count": len(tool_results),
        "final_answer": final_answer,
        "output": final_answer,
        "messages": messages,
    }


def direct_node(state: OrchestratorState, model: ChatOpenAI, middleware: List) -> Dict:
    """Handle simple queries without tools."""
    user_input = state.get("user_input", "")
    
    direct_agent = create_direct_agent(model, middleware)
    result = direct_agent.invoke({"messages": [HumanMessage(content=user_input)]})
    
    messages = result.get("messages", [])
    final_msg = messages[-1] if messages else AIMessage(content="Response generated")
    final_answer = final_msg.content if hasattr(final_msg, 'content') else str(final_msg)
    
    return {
        "tool_call_count": 0,
        "final_answer": final_answer,
        "output": final_answer,
        "messages": messages,
    }


# =============================================================================
# Edge Functions
# =============================================================================

def after_router(state: OrchestratorState) -> Literal["executor", "direct"]:
    """Route after analyzing task."""
    if state.get("needs_tools", False):
        return "executor"
    return "direct"


# =============================================================================
# Graph Builder
# =============================================================================

def build_agent_graph(model: ChatOpenAI, tools: List[Tool], middleware: List):
    """Build the orchestration graph."""
    graph = StateGraph(OrchestratorState)
    
    # Add nodes with dependencies
    graph.add_node("router", lambda s: router_node(s, model, middleware))
    graph.add_node("executor", lambda s: executor_node(s, model, tools, middleware))
    graph.add_node("direct", lambda s: direct_node(s, model, middleware))
    
    # Entry point
    graph.set_entry_point("router")
    
    # Conditional routing
    graph.add_conditional_edges(
        "router",
        after_router,
        {
            "executor": "executor",
            "direct": "direct",
        }
    )
    
    # End states
    graph.add_edge("executor", END)
    graph.add_edge("direct", END)
    
    return graph.compile(checkpointer=MemorySaver())


# =============================================================================
# Main Agent Class
# =============================================================================

class LangGraphAgent:
    """
    Generic task-solving agent using LangGraph with router pattern.
    
    Features:
    - Task analysis and planning (router)
    - Error recovery middleware
    - Explicit state management
    - Tool execution with tracking
    - Works with ANY green agent
    """
    
    def __init__(
        self,
        mcp_endpoint: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
    ):
        self.mcp_endpoint = mcp_endpoint
        self.model_name = model
        self.temperature = temperature
        
        self.tool_loader = MCPToolLoader(mcp_endpoint)
        self.graph = None
        self.tools = []
        self.middleware = create_error_recovery_middleware()
        
        # Metrics
        self.total_tasks = 0
        self.successful_tasks = 0
    
    async def initialize(self):
        """Load tools and build graph."""
        print(f"🔧 Initializing LangGraph Agent (Router Pattern)...")
        print(f"   Model: {self.model_name}")
        print(f"   MCP: {self.mcp_endpoint}")
        
        # Load tools
        self.tools = await self.tool_loader.load_tools()
        print(f"✅ Loaded {len(self.tools)} tools")
        
        # Create model
        model = ChatOpenAI(model=self.model_name, temperature=self.temperature)
        
        # Build graph
        self.graph = build_agent_graph(model, self.tools, self.middleware)
        print(f"✅ Agent graph compiled")
    
    async def run(self, message: Message, updater: TaskUpdater) -> None:
        """Execute agent (A2A interface)."""
        if self.graph is None:
            await self.initialize()
        
        self.total_tasks += 1
        task_text = get_message_text(message)
        
        await updater.update_status(
            TaskState.working,
            new_agent_text_message(f"Analyzing task...")
        )
        
        try:
            # Invoke graph
            config = {"configurable": {"thread_id": "main"}}
            result = await asyncio.to_thread(
                self.graph.invoke,
                {"user_input": task_text, "messages": [HumanMessage(content=task_text)]},
                config
            )
            
            # Extract results
            final_answer = result.get("final_answer", result.get("output", "Task completed"))
            tool_results = result.get("tool_results", [])
            tool_call_count = result.get("tool_call_count", 0)
            
            # Build response
            response_data = {
                "response": final_answer,
                "tool_calls": tool_results,
                "tool_call_count": tool_call_count,
                "routing": {
                    "needs_tools": result.get("needs_tools", False),
                    "strategy": result.get("tool_strategy", "none"),
                    "reasoning": result.get("routing_reasoning", ""),
                },
                "metrics": {
                    "total_tasks": self.total_tasks,
                    "success_rate": f"{(self.successful_tasks / max(self.total_tasks, 1)) * 100:.1f}%",
                }
            }
            
            await updater.add_artifact(
                parts=[Part(root=TextPart(text=json.dumps(response_data)))],
                name="Response",
            )
            
            self.successful_tasks += 1
            
        except Exception as e:
            print(f"❌ Agent error: {e}")
            import traceback
            traceback.print_exc()
            await updater.update_status(
                TaskState.failed,
                new_agent_text_message(f"Error: {e}")
            )
            raise
    
    async def close(self):
        """Cleanup."""
        await self.tool_loader.close()
    
    def get_metrics(self) -> Dict:
        """Get metrics."""
        return {
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "success_rate": f"{(self.successful_tasks / max(self.total_tasks, 1)) * 100:.1f}%",
        }
    
    def reset(self):
        """Reset metrics."""
        self.total_tasks = 0
        self.successful_tasks = 0


# =============================================================================
# Exports
# =============================================================================

__all__ = ["LangGraphAgent", "MCPToolLoader", "OrchestratorState", "RouterDecision"]
