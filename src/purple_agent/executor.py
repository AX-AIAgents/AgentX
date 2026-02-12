"""
Advanced Purple Agent Executor
==============================
A2A AgentExecutor with enhanced capabilities.

Features:
- Metrics tracking
- Configurable timeouts
- Graceful shutdown handling
- Optional LangGraph agent (USE_LANGGRAPH env var)
"""
import asyncio
import os
import signal
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    TaskState,
    UnsupportedOperationError,
    InvalidRequestError,
)
from a2a.utils.errors import ServerError
from a2a.utils import new_agent_text_message, new_task

from src.purple_agent.agent import AdvancedPurpleAgent, ModelConfig, RetryConfig, MemoryConfig
# from langgraph_agent import LangGraphAgent
# Optional LangGraph support
try:
    from langgraph_agent import LangGraphAgent
    LANGGRAPH_AVAILABLE = False
except ImportError:
    LANGGRAPH_AVAILABLE = False
    LangGraphAgent = None


# =============================================================================
# Metrics
# =============================================================================

@dataclass
class ExecutorMetrics:
    """Executor-level metrics."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    active_tasks: int = 0
    total_processing_time: float = 0.0
    request_times: list[float] = field(default_factory=list)
    
    @property
    def avg_processing_time(self) -> float:
        if not self.request_times:
            return 0.0
        return sum(self.request_times) / len(self.request_times)
    
    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests
    
    def to_dict(self) -> dict:
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": f"{self.success_rate:.2%}",
            "active_tasks": self.active_tasks,
            "avg_processing_time_ms": f"{self.avg_processing_time * 1000:.2f}",
        }


# =============================================================================
# Terminal States
# =============================================================================

TERMINAL_STATES = {
    TaskState.completed,
    TaskState.canceled,
    TaskState.failed,
    TaskState.rejected
}


# =============================================================================
# Advanced Executor
# =============================================================================

class AdvancedPurpleExecutor(AgentExecutor):
    """
    Advanced A2A Executor for Purple Agent.
    
    Features:
    - Per-context agent management
    - Metrics tracking
    - Configurable timeouts
    - Graceful shutdown
    """
    
    def __init__(
        self,
        mcp_endpoint: str | None = None,
        model_config: ModelConfig | None = None,
        retry_config: RetryConfig | None = None,
        memory_config: MemoryConfig | None = None,
        task_timeout: float = 300.0,  # 5 minutes default
    ):
        self.mcp_endpoint = mcp_endpoint
        self.model_config = model_config
        self.retry_config = retry_config
        self.memory_config = memory_config
        self.task_timeout = task_timeout
        
        # Use LangGraph if available
        self.use_langgraph = LANGGRAPH_AVAILABLE
        
        if self.use_langgraph:
            print("✅ Using LangGraph Agent (Router Pattern)")
        else:
            print("⚠️ LangGraph not available, using basic agent")
        
        self.agents: dict[str, Any] = {}  # Can hold either type
        self.metrics = ExecutorMetrics()
        self._shutdown_event = asyncio.Event()
        self._active_tasks: set[asyncio.Task] = set()
    
    def _create_agent(self):
        """Create a new agent instance with current configuration."""
        if self.use_langgraph and LANGGRAPH_AVAILABLE:
            # Create LangGraph agent
            model_name = self.model_config.model_name if self.model_config else "gpt-4o-mini"
            temperature = self.model_config.temperature if self.model_config else 0.0
            
            return LangGraphAgent(
                mcp_endpoint=self.mcp_endpoint,
                model=model_name,
                temperature=temperature,
            )
        else:
            # Fallback to basic agent
            return AdvancedPurpleAgent(
                mcp_endpoint=self.mcp_endpoint,
                model_config=self.model_config,
                retry_config=self.retry_config,
                memory_config=self.memory_config,
            )
    
    @asynccontextmanager
    async def _track_request(self):
        """Context manager to track request metrics."""
        start_time = time.time()
        self.metrics.total_requests += 1
        self.metrics.active_tasks += 1
        
        try:
            yield
            self.metrics.successful_requests += 1
        except Exception:
            self.metrics.failed_requests += 1
            raise
        finally:
            elapsed = time.time() - start_time
            self.metrics.total_processing_time += elapsed
            self.metrics.request_times.append(elapsed)
            self.metrics.active_tasks -= 1
            
            # Keep only last 100 request times
            if len(self.metrics.request_times) > 100:
                self.metrics.request_times = self.metrics.request_times[-100:]
    
    async def execute(
        self, 
        context: RequestContext, 
        event_queue: EventQueue
    ) -> None:
        """Execute agent logic with timeout and tracking."""
        async with self._track_request():
            await self._execute_with_timeout(context, event_queue)
    
    async def _execute_with_timeout(
        self,
        context: RequestContext,
        event_queue: EventQueue
    ) -> None:
        """Execute with timeout wrapper."""
        msg = context.message
        if not msg:
            raise ServerError(
                error=InvalidRequestError(message="Missing message in request")
            )
        
        task = context.current_task
        
        if task and task.status.state in TERMINAL_STATES:
            raise ServerError(
                error=InvalidRequestError(
                    message=f"Task {task.id} already processed"
                )
            )
        
        if not task:
            task = new_task(msg)
            await event_queue.enqueue_event(task)
        
        context_id = task.context_id
        
        # Get or create agent
        agent = self.agents.get(context_id)
        if not agent:
            agent = self._create_agent()
            self.agents[context_id] = agent
        
        updater = TaskUpdater(event_queue, task.id, context_id)
        
        await updater.start_work()
        
        try:
            # Run with timeout
            await asyncio.wait_for(
                agent.run(msg, updater),
                timeout=self.task_timeout
            )
            
            if not updater._terminal_state_reached:
                await updater.complete()
                
        except asyncio.TimeoutError:
            print(f"⏰ Task {task.id} timed out after {self.task_timeout}s")
            await updater.failed(
                new_agent_text_message(
                    f"Task timed out after {self.task_timeout} seconds",
                    context_id=context_id,
                    task_id=task.id
                )
            )
        except Exception as e:
            print(f"❌ Task failed: {e}")
            await updater.failed(
                new_agent_text_message(
                    f"Agent error: {e}",
                    context_id=context_id,
                    task_id=task.id
                )
            )
    
    async def cancel(
        self, 
        context: RequestContext, 
        event_queue: EventQueue
    ) -> None:
        """Cancel a running task."""
        # For now, just raise unsupported
        # Future: implement actual cancellation
        raise ServerError(error=UnsupportedOperationError())
    
    async def cleanup_agent(self, context_id: str):
        """Cleanup agent resources for a context."""
        if context_id in self.agents:
            agent = self.agents.pop(context_id)
            await agent.close()
            print(f"🧹 Cleaned up agent for context: {context_id}")
    
    async def shutdown(self):
        """Graceful shutdown of all agents."""
        print("🛑 Initiating graceful shutdown...")
        self._shutdown_event.set()
        
        # Close all agents
        for context_id, agent in list(self.agents.items()):
            try:
                await agent.close()
            except Exception as e:
                print(f"⚠️ Error closing agent {context_id}: {e}")
        
        self.agents.clear()
        print("✅ Shutdown complete")
    
    def get_metrics(self) -> dict:
        """Get executor metrics."""
        return {
            "executor": self.metrics.to_dict(),
            "agents": {
                ctx_id: agent.get_metrics() 
                for ctx_id, agent in self.agents.items()
            }
        }
    
    def get_agent_count(self) -> int:
        """Get number of active agents."""
        return len(self.agents)
