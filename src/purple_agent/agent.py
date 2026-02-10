"""
Advanced Purple Agent
=====================
Multi-model AI agent with enhanced capabilities.

Features:
- Multi-model support (GPT-4o, GPT-4o-mini, Claude)
- Retry logic with exponential backoff
- Parallel tool execution
- Structured outputs with Pydantic
- Sliding window memory management
- Error recovery with fallback strategies
"""
import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart
from a2a.utils import get_message_text, new_agent_text_message

load_dotenv()


# =============================================================================
# Configuration Models
# =============================================================================

class ModelProvider(str, Enum):
    """Supported model providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class ModelConfig(BaseModel):
    """Model configuration."""
    provider: ModelProvider = ModelProvider.OPENAI
    model_name: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 4096
    

class RetryConfig(BaseModel):
    """Retry configuration."""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0


class MemoryConfig(BaseModel):
    """Memory/context management configuration."""
    max_history_messages: int = 50
    sliding_window_size: int = 20
    summarize_threshold: int = 40


@dataclass
class ToolCallMetrics:
    """Metrics for tool call tracking."""
    tool_name: str
    start_time: float
    end_time: float = 0.0
    success: bool = False
    error: str | None = None
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time if self.end_time else 0.0


@dataclass
class AgentMetrics:
    """Overall agent metrics."""
    total_tool_calls: int = 0
    successful_tool_calls: int = 0
    failed_tool_calls: int = 0
    total_retries: int = 0
    tool_call_history: list[ToolCallMetrics] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        if self.total_tool_calls == 0:
            return 0.0
        return self.successful_tool_calls / self.total_tool_calls
    
    def to_dict(self) -> dict:
        return {
            "total_tool_calls": self.total_tool_calls,
            "successful_tool_calls": self.successful_tool_calls,
            "failed_tool_calls": self.failed_tool_calls,
            "success_rate": f"{self.success_rate:.2%}",
            "total_retries": self.total_retries,
            "avg_tool_duration": self._avg_duration(),
        }
    
    def _avg_duration(self) -> float:
        if not self.tool_call_history:
            return 0.0
        return sum(tc.duration for tc in self.tool_call_history) / len(self.tool_call_history)


# =============================================================================
# Advanced Purple Agent
# =============================================================================

class AdvancedPurpleAgent:
    """
    Advanced Purple Agent with enhanced capabilities.
    
    Features:
    - Multi-model support (OpenAI, Anthropic)
    - Retry logic with exponential backoff
    - Parallel tool execution
    - Sliding window memory management
    - Metrics tracking
    """
    
    def __init__(
        self,
        mcp_endpoint: str | None = None,
        model_config: ModelConfig | None = None,
        retry_config: RetryConfig | None = None,
        memory_config: MemoryConfig | None = None,
    ):
        self.mcp_endpoint = mcp_endpoint
        self.model_config = model_config or self._load_model_config()
        self.retry_config = retry_config or RetryConfig()
        self.memory_config = memory_config or MemoryConfig()
        
        self.conversation_history: list[dict] = []
        self.available_tools: list[dict] = []
        self.metrics = AgentMetrics()
        
        self._openai_client: OpenAI | None = None
        self._http_client: httpx.AsyncClient | None = None
    
    def _load_model_config(self) -> ModelConfig:
        """Load model config from environment."""
        model_name = os.getenv("MODEL", "gpt-4o-mini")
        temperature = float(os.getenv("TEMPERATURE", "0.7"))
        max_tokens = int(os.getenv("MAX_TOKENS", "4096"))
        
        return ModelConfig(
            provider=ModelProvider.OPENAI,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    
    @property
    def openai_client(self) -> OpenAI:
        """Lazy initialization of OpenAI client."""
        if self._openai_client is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable not set")
            self._openai_client = OpenAI(api_key=api_key)
        return self._openai_client
    
    async def get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=60.0)
        return self._http_client
    
    async def close(self):
        """Cleanup resources."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
    
    # =========================================================================
    # Tool Discovery & Execution
    # =========================================================================
    
    async def discover_tools(self) -> list[dict]:
        """Discover available tools from MCP endpoint."""
        if not self.mcp_endpoint:
            return []
        
        try:
            client = await self.get_http_client()
            response = await client.get(f"{self.mcp_endpoint}/tools")
            if response.status_code == 200:
                data = response.json()
                tools = data.get("tools", [])
                print(f"✅ Discovered {len(tools)} tools from MCP")
                return tools
        except Exception as e:
            print(f"⚠️ Failed to discover tools: {e}")
        
        return []
    
    async def call_tool_with_retry(
        self, 
        tool_name: str, 
        arguments: dict
    ) -> dict:
        """Execute a tool with retry logic."""
        metrics = ToolCallMetrics(tool_name=tool_name, start_time=time.time())
        
        last_error = None
        for attempt in range(self.retry_config.max_retries):
            try:
                result = await self._execute_tool(tool_name, arguments)
                
                # Check if result is an error
                if "error" in result and attempt < self.retry_config.max_retries - 1:
                    raise Exception(result["error"])
                
                metrics.end_time = time.time()
                metrics.success = True
                self.metrics.successful_tool_calls += 1
                self.metrics.total_tool_calls += 1
                self.metrics.tool_call_history.append(metrics)
                
                return result
                
            except Exception as e:
                last_error = str(e)
                self.metrics.total_retries += 1
                
                if attempt < self.retry_config.max_retries - 1:
                    delay = min(
                        self.retry_config.base_delay * (self.retry_config.exponential_base ** attempt),
                        self.retry_config.max_delay
                    )
                    print(f"⚠️ Tool call failed, retrying in {delay:.1f}s (attempt {attempt + 1}/{self.retry_config.max_retries})")
                    await asyncio.sleep(delay)
        
        # All retries failed
        metrics.end_time = time.time()
        metrics.success = False
        metrics.error = last_error
        self.metrics.failed_tool_calls += 1
        self.metrics.total_tool_calls += 1
        self.metrics.tool_call_history.append(metrics)
        
        return {"error": f"Tool call failed after {self.retry_config.max_retries} attempts: {last_error}"}
    
    async def _execute_tool(self, tool_name: str, arguments: dict) -> dict:
        """Execute a single tool call."""
        if not self.mcp_endpoint:
            return {"error": "No MCP endpoint configured"}
        
        client = await self.get_http_client()
        response = await client.post(
            f"{self.mcp_endpoint}/tools/call",
            json={"name": tool_name, "arguments": arguments}
        )
        return response.json()
    
    async def execute_tools_parallel(
        self, 
        tool_calls: list[dict]
    ) -> list[dict]:
        """Execute multiple tools in parallel."""
        tasks = [
            self.call_tool_with_retry(tc["name"], tc["arguments"])
            for tc in tool_calls
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Convert exceptions to error dicts
        processed_results = []
        for result in results:
            if isinstance(result, Exception):
                processed_results.append({"error": str(result)})
            else:
                processed_results.append(result)
        
        return processed_results
    
    # =========================================================================
    # Memory Management
    # =========================================================================
    
    def _apply_sliding_window(self):
        """Apply sliding window to conversation history."""
        if len(self.conversation_history) > self.memory_config.max_history_messages:
            # Keep system message (if any) and recent messages
            keep_count = self.memory_config.sliding_window_size
            self.conversation_history = self.conversation_history[-keep_count:]
            print(f"📝 Applied sliding window, kept {keep_count} messages")
    
    def convert_tools_to_openai_format(self, tools: list[dict]) -> list[dict]:
        """Convert MCP tool format to OpenAI function format."""
        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                }
            })
        return openai_tools
    
    # =========================================================================
    # Main Agent Logic
    # =========================================================================
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for the agent."""
        return """You are an advanced AI assistant designed to complete tasks efficiently using available tools.

EXECUTION GUIDELINES:
1. Analyze the task requirements thoroughly before acting
2. Use tools strategically - prefer parallel execution when possible
3. Handle errors gracefully and retry with alternative approaches
4. Report progress clearly and summarize results

TOOL USAGE:
- Call multiple independent tools in parallel for efficiency
- Chain dependent tool calls in sequence
- Validate tool results before proceeding
- If a tool fails, try alternative approaches

COMPLETION CRITERIA:
- Verify all task requirements are met
- Provide a clear summary of actions taken
- Report any issues or partial completions

You have access to various MCP tools. Use them effectively to complete the user's request."""

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        """
        Main agent execution loop.
        
        Args:
            message: Incoming A2A message with task instruction
            updater: TaskUpdater for reporting progress
        """
        input_text = get_message_text(message)
        
        # Check for new task indicator
        if "<task_config>" in input_text or not self.conversation_history:
            self.conversation_history.clear()
            self.metrics = AgentMetrics()  # Reset metrics
            if self.mcp_endpoint:
                self.available_tools = await self.discover_tools()
        
        await updater.update_status(
            TaskState.working,
            new_agent_text_message(f"Processing with {self.model_config.model_name}...")
        )
        
        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": input_text
        })
        
        # Apply memory management
        self._apply_sliding_window()
        
        # Convert tools to OpenAI format
        openai_tools = self.convert_tools_to_openai_format(self.available_tools)
        
        try:
            # Call LLM
            response = self.openai_client.chat.completions.create(
                model=self.model_config.model_name,
                temperature=self.model_config.temperature,
                max_tokens=self.model_config.max_tokens,
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    *self.conversation_history
                ],
                tools=openai_tools if openai_tools else None,
                tool_choice="auto" if openai_tools else None,
            )
            
            assistant_message = response.choices[0].message
            
            # Handle tool calls
            if assistant_message.tool_calls:
                await self._handle_tool_calls(assistant_message, updater, openai_tools)
            else:
                # No tool calls, just text response
                response_text = assistant_message.content or ""
                self.conversation_history.append({
                    "role": "assistant",
                    "content": response_text
                })
                
                # Include metrics in response
                response_with_metrics = {
                    "response": response_text,
                    "metrics": self.metrics.to_dict(),
                }
                
                await updater.add_artifact(
                    parts=[Part(root=TextPart(text=json.dumps(response_with_metrics)))],
                    name="Response",
                )
                
        except Exception as e:
            await updater.update_status(
                TaskState.failed,
                new_agent_text_message(f"Error: {e}")
            )
            raise
    
    async def _handle_tool_calls(
        self, 
        assistant_message, 
        updater: TaskUpdater,
        openai_tools: list[dict]
    ):
        """Handle tool calls from assistant."""
        tool_calls = assistant_message.tool_calls
        
        # Prepare tool calls for parallel execution
        parallel_calls = [
            {"name": tc.function.name, "arguments": json.loads(tc.function.arguments)}
            for tc in tool_calls
        ]
        
        await updater.update_status(
            TaskState.working,
            new_agent_text_message(f"Executing {len(parallel_calls)} tool(s) in parallel...")
        )
        
        # Execute tools in parallel
        results = await self.execute_tools_parallel(parallel_calls)
        
        # Build tool results for message history
        tool_results = []
        for i, (tc, result) in enumerate(zip(tool_calls, results)):
            tool_results.append({
                "tool_call_id": tc.id,
                "role": "tool",
                "content": json.dumps(result)
            })
        
        # Add assistant message with tool calls
        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in tool_calls
            ]
        })
        
        # Add tool results
        for tr in tool_results:
            self.conversation_history.append(tr)
        
        # Get final response
        final_response = self.openai_client.chat.completions.create(
            model=self.model_config.model_name,
            temperature=self.model_config.temperature,
            messages=[
                {"role": "system", "content": self._get_system_prompt()},
                *self.conversation_history
            ],
        )
        
        final_text = final_response.choices[0].message.content or ""
        self.conversation_history.append({
            "role": "assistant",
            "content": final_text
        })
        
        # Build response with tool calls for scoring
        tool_calls_for_scoring = [
            {"name": tc.function.name, "arguments": json.loads(tc.function.arguments)}
            for tc in tool_calls
        ]
        
        response_with_tools = {
            "response": final_text,
            "tool_calls": tool_calls_for_scoring,
            "tool_results": results,
            "metrics": self.metrics.to_dict(),
        }
        
        await updater.add_artifact(
            parts=[Part(root=TextPart(text=json.dumps(response_with_tools)))],
            name="Response",
        )
    
    def reset(self):
        """Reset agent state."""
        self.conversation_history.clear()
        self.available_tools.clear()
        self.metrics = AgentMetrics()
    
    def get_metrics(self) -> dict:
        """Get current agent metrics."""
        return self.metrics.to_dict()
