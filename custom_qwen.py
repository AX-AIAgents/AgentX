
from typing import List, Dict, Any, Optional, Iterator, Sequence
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage, ToolMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableBinding
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field, PrivateAttr
import json

class LocalModel(BaseChatModel):
    """Local Qwen model with native tool support (no OpenAI dependency)"""
    
    base_url: str = Field(default="http://127.0.0.1:8001/v1")
    model: str = Field(default="/gpfs/scratch/ehpc142/models/Qwen3-235B-A22B-Instruct-2507")
    temperature: float = Field(default=0.7)
    max_tokens: int = Field(default=2048)
    
    # Private attributes
    _tools: List[Dict] = PrivateAttr(default_factory=list)
    _tool_choice: Optional[str] = PrivateAttr(default=None)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tools = []
        self._tool_choice = None
    
    @property
    def _llm_type(self) -> str:
        return "local-qwen"
    
    @property
    def _identifying_params(self) -> Dict[str, Any]:
        params = {
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
        }
        # Include tools in identifying params for serialization
        if self._tools:
            params["tools"] = self._tools
        return params
    
    def _convert_messages(self, messages: List[BaseMessage]) -> List[Dict]:
        """Convert LangChain messages to OpenAI format"""
        result = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                result.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                m = {"role": "assistant", "content": msg.content or ""}
                if msg.tool_calls:
                    m["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["args"]) if isinstance(tc["args"], dict) else tc["args"]
                            }
                        }
                        for tc in msg.tool_calls
                    ]
                result.append(m)
            elif isinstance(msg, SystemMessage):
                result.append({"role": "system", "content": msg.content})
            elif isinstance(msg, ToolMessage):
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content
                })
        return result
    
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs
    ) -> ChatResult:
        """Generate using curl (SSH tunnel compatible)"""
        import subprocess
        
        openai_messages = self._convert_messages(messages)
        
        # Add system message if missing
        has_system = any(m.get("role") == "system" for m in openai_messages)
        if not has_system:
            openai_messages.insert(0, {
                "role": "system",
                "content": "You are a helpful assistant with access to tools."
            })
        
        request_body = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        
        # Add tools if bound
        if self._tools:
            request_body["tools"] = self._tools
            # vLLM only supports "auto" or "required", not "any"
            choice = self._tool_choice or "auto"
            if choice == "any":
                choice = "required"  # "any" → "required" for vLLM compatibility
            request_body["tool_choice"] = choice
        
        # Debug log
        print(f"[LocalModel] Request to {self.model}:")
        print(f"  tools count: {len(self._tools) if self._tools else 0}")
        print(f"  tool_choice: {request_body.get('tool_choice', 'not set')}")
        
        if stop:
            request_body["stop"] = stop
        
        # Use curl for compatibility
        curl_cmd = [
            "curl", "-s", "-X", "POST",
            f"{self.base_url}/chat/completions",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(request_body)
        ]
        
        result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            raise RuntimeError(f"curl failed: {result.stderr}")
        
        try:
            response_data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON response: {result.stdout[:500]}")
        
        if "error" in response_data:
            raise RuntimeError(f"API error: {response_data['error']}")
        
        choice = response_data["choices"][0]
        message = choice["message"]
        
        # Debug log
        content = message.get("content") or ""
        print(f"[LocalModel] Response received:")
        print(f"  content: {content[:100] if content else '(none)'}...")
        print(f"  tool_calls: {message.get('tool_calls', [])}")
        print(f"  finish_reason: {choice.get('finish_reason')}")
        
        # Parse tool calls
        tool_calls = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                tool_calls.append({
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "args": json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                })
        
        ai_message = AIMessage(
            content=content,
            tool_calls=tool_calls if tool_calls else []
        )
        
        return ChatResult(generations=[ChatGeneration(message=ai_message)])
    
    def bind_tools(
        self,
        tools: Sequence[BaseTool | Dict[str, Any]],
        *,
        tool_choice: Optional[str] = None,
        **kwargs
    ) -> "LocalModel":
        """Bind tools to the model for function calling"""
        # Create a copy with tools
        new_model = LocalModel(
            base_url=self.base_url,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
        # Convert tools to OpenAI format
        converted_tools = []
        for t in tools:
            if isinstance(t, dict):
                converted_tools.append(t)
            else:
                converted_tools.append(convert_to_openai_tool(t))
        new_model._tools = converted_tools
        new_model._tool_choice = tool_choice
        return new_model
    
    @property
    def bound_tools(self) -> List[Dict]:
        """Return the list of bound tools (for LangGraph introspection)"""
        return self._tools
    
    def bind(self, **kwargs) -> "LocalModel":
        """Bind additional kwargs to the model"""
        # Handle tools if passed via bind
        tools = kwargs.pop("tools", None)
        tool_choice = kwargs.pop("tool_choice", None)
        
        if tools:
            return self.bind_tools(tools, tool_choice=tool_choice, **kwargs)
        
        # For other bindings, create a copy
        new_model = LocalModel(
            base_url=self.base_url,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
        new_model._tools = self._tools.copy() if self._tools else []
        new_model._tool_choice = self._tool_choice
        return new_model
    
    def model_dump(self, **kwargs) -> Dict[str, Any]:
        """Serialize model including tools"""
        data = super().model_dump(**kwargs)
        if self._tools:
            data["tools"] = self._tools
        return data
