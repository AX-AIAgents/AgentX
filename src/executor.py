"""
AgentX Executor
===============
A2A AgentExecutor implementation for Green Agent.
Based on AgentBeats green-agent-template.
"""
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    Task,
    TaskState,
    UnsupportedOperationError,
    InvalidRequestError,
)
from a2a.utils.errors import ServerError
from a2a.utils import new_agent_text_message, new_task

from src.agent import Agent


TERMINAL_STATES = {
    TaskState.completed,
    TaskState.canceled,
    TaskState.failed,
    TaskState.rejected
}


class Executor(AgentExecutor):
    """
    A2A Executor for AgentX Green Agent.
    
    Manages agent instances per context and handles task lifecycle.
    """
    
    def __init__(self, task_file: str | None = None, mcp_port: int = 8091):
        """
        Initialize executor.
        
        Args:
            task_file: Path to task definitions JSONL file
            mcp_port: Port where MCP server is running
        """
        self.agents: dict[str, Agent] = {}  # context_id -> agent instance
        self.task_file = task_file
        self.mcp_port = mcp_port
        self.mcp_endpoint = f"http://localhost:{mcp_port}"
        
        # Load task loader if file provided
        self.task_loader = None
        if task_file:
            try:
                from src.tools.task_loader import TaskLoader
                self.task_loader = TaskLoader(task_file)
                self.task_loader.load_all()
                print(f"✅ Loaded {len(self.task_loader.tasks)} tasks from {task_file}")
            except Exception as e:
                print(f"⚠️ Could not load tasks: {e}")
    
    async def execute(
        self, 
        context: RequestContext, 
        event_queue: EventQueue
    ) -> None:
        """
        Execute agent logic for incoming request.
        
        Args:
            context: Request context with message and task info
            event_queue: Queue for sending events back to client
        """
        msg = context.message
        if not msg:
            raise ServerError(
                error=InvalidRequestError(message="Missing message in request")
            )
        
        task = context.current_task
        
        # Check if task is already in terminal state
        if task and task.status.state in TERMINAL_STATES:
            raise ServerError(
                error=InvalidRequestError(
                    message=f"Task {task.id} already processed (state: {task.status.state})"
                )
            )
        
        # Create new task if needed
        if not task:
            task = new_task(msg)
            await event_queue.enqueue_event(task)
        
        context_id = task.context_id
        
        # Get or create agent instance
        agent = self.agents.get(context_id)
        if not agent:
            agent = Agent()
            # Inject task loader and MCP endpoint
            agent.task_loader = self.task_loader
            agent.mcp_endpoint = self.mcp_endpoint
            self.agents[context_id] = agent
        
        # Create task updater
        updater = TaskUpdater(event_queue, task.id, context_id)
        
        # Run agent
        await updater.start_work()
        try:
            await agent.run(msg, updater)
            if not updater._terminal_state_reached:
                await updater.complete()
        except Exception as e:
            print(f"❌ Task failed with agent error: {e}")
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
        """Cancel is not supported."""
        raise ServerError(error=UnsupportedOperationError())
