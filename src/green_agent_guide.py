# =============================================================================
# CONVERSATIONAL GUIDE - No Tool Name Hints (Benchmark Safe)
# =============================================================================

from enum import Enum
from typing import Optional
import random


class TaskPhase(Enum):
    """Task progression phases."""
    INITIAL = "initial"
    GATHERING = "gathering"
    PROCESSING = "processing"
    CREATING = "creating"
    FINALIZING = "finalizing"
    COMPLETE = "complete"


class ActionType(Enum):
    """Abstract action types - NO tool names."""
    SEARCH = "search"
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    SEND = "send"
    ANALYZE = "analyze"


# Patterns to detect action types (internal use only)
_ACTION_PATTERNS = {
    ActionType.SEARCH: ["search", "query", "find", "list", "browse"],
    ActionType.READ: ["get", "read", "retrieve", "fetch", "download", "content", "transcript"],
    ActionType.CREATE: ["create", "post", "new", "add", "insert", "draft"],
    ActionType.UPDATE: ["update", "patch", "modify", "edit", "change"],
    ActionType.SEND: ["send", "email", "mail", "notify", "share"],
    ActionType.ANALYZE: ["analyze", "process", "extract", "parse"],
}

# Abstract guidance messages - NO tool names
PHASE_GUIDANCE = {
    TaskPhase.INITIAL: [
        "What information do you need to complete this task?",
        "Think about what resources you'll need first.",
        "What's the logical first step here?",
        "Consider what data you need before taking action.",
    ],
    TaskPhase.GATHERING: [
        "Are you finding the information you need?",
        "Is there more data you should collect?",
        "Do you have enough context to proceed?",
        "What else might be relevant to look up?",
    ],
    TaskPhase.PROCESSING: [
        "How can you use the information you've gathered?",
        "What's the most important data you found?",
        "Is there content you need to examine more closely?",
        "Do you need to extract specific details?",
    ],
    TaskPhase.CREATING: [
        "What output should you produce?",
        "How should you organize this information?",
        "What format would be most useful?",
        "Is it time to create something with this data?",
    ],
    TaskPhase.FINALIZING: [
        "Is there anyone who needs to see this?",
        "Should you share or distribute the results?",
        "What's the final deliverable?",
        "How should the output be communicated?",
    ],
}

# Workflow hints - Abstract, no tool names
WORKFLOW_HINTS = {
    (ActionType.SEARCH, ActionType.READ): 
        "You found some results. Consider examining the content more closely.",
    (ActionType.SEARCH, ActionType.ANALYZE): 
        "Good search. There might be media content worth analyzing.",
    (ActionType.READ, ActionType.CREATE): 
        "You have data now. What will you create with it?",
    (ActionType.READ, ActionType.SEND): 
        "Information gathered. Who needs to know about this?",
    (ActionType.ANALYZE, ActionType.CREATE): 
        "Analysis done. Time to produce an output?",
    (ActionType.CREATE, ActionType.SEND): 
        "Content ready. Should it be shared with someone?",
    (ActionType.CREATE, ActionType.UPDATE): 
        "Created something. Does anything need refinement?",
}

# Progress encouragements
ENCOURAGEMENTS = [
    "You're on the right track.",
    "Good progress so far.",
    "Keep going, you're doing well.",
    "Nice work on that step.",
    "That was a logical choice.",
]

# Gentle nudges when stuck
NUDGES = [
    "Think about what action would move you forward.",
    "What capability would help here?",
    "Consider the tools at your disposal.",
    "What's the next logical step?",
    "How would you approach this manually?",
]


class ConversationalGuide:
    """
    Generates benchmark-safe conversational responses.
    
    NEVER reveals:
    - Tool names
    - Exact parameters
    - Direct solutions
    
    ONLY provides:
    - Conceptual guidance
    - Socratic questions
    - Abstract workflow hints
    - Progress feedback
    """
    
    def __init__(self, current_task: dict):
        self.current_task = current_task
        self.questions_asked: list[str] = []
        
    def _classify_action(self, tool_name: str) -> ActionType:
        """Classify tool into abstract action type (internal only)."""
        name_lower = tool_name.lower()
        
        for action, patterns in _ACTION_PATTERNS.items():
            if any(p in name_lower for p in patterns):
                return action
        
        return ActionType.SEARCH  # Default fallback
    
    def _determine_phase(
        self,
        progress: int,
        total: int,
        called_tools: list[str]
    ) -> TaskPhase:
        """Determine task phase from progress."""
        if progress == 0:
            return TaskPhase.INITIAL
        
        if total == 0:
            return TaskPhase.INITIAL
            
        ratio = progress / total
        
        if ratio >= 1.0:
            return TaskPhase.COMPLETE
        
        # Analyze what types of actions have been taken
        actions = {self._classify_action(t) for t in called_tools}
        
        if ratio >= 0.8:
            return TaskPhase.FINALIZING
        elif ActionType.CREATE in actions or ActionType.UPDATE in actions:
            return TaskPhase.CREATING
        elif ActionType.READ in actions or ActionType.ANALYZE in actions:
            return TaskPhase.PROCESSING
        else:
            return TaskPhase.GATHERING
    
    def _get_question(self, phase: TaskPhase) -> str:
        """Get a non-repeating question for the phase."""
        options = PHASE_GUIDANCE.get(phase, NUDGES)
        available = [q for q in options if q not in self.questions_asked]
        
        if not available:
            self.questions_asked.clear()
            available = options
        
        question = random.choice(available)
        self.questions_asked.append(question)
        return question
    
    def _get_workflow_hint(
        self,
        called_tools: list[str],
        missing_tools: list[str]
    ) -> Optional[str]:
        """Get abstract workflow hint without revealing tool names."""
        if not called_tools or not missing_tools:
            return None
        
        last_action = self._classify_action(called_tools[-1])
        
        # Find what action type is likely next
        for missing in missing_tools:
            next_action = self._classify_action(missing)
            hint = WORKFLOW_HINTS.get((last_action, next_action))
            if hint:
                return hint
        
        return None
    
    def _create_progress_indicator(self, current: int, total: int) -> str:
        """Create abstract progress indicator."""
        if total == 0:
            return ""
        
        ratio = current / total
        
        if ratio == 0:
            return "🔵 Just starting"
        elif ratio < 0.3:
            return "🔵🔵 Early progress"
        elif ratio < 0.6:
            return "🔵🔵🔵 Making progress"
        elif ratio < 0.9:
            return "🔵🔵🔵🔵 Good progress"
        elif ratio < 1.0:
            return "🔵🔵🔵🔵🔵 Almost there"
        else:
            return "✅ All steps complete"
    
    def _extract_message(self, message: str) -> str:
        """Extract clean message without tool markers."""
        lines = [l for l in message.split('\n') if not l.strip().startswith('[TOOL:')]
        text = '\n'.join(lines).strip()
        return text[:100] + "..." if len(text) > 100 else text
    
    def generate_response(
        self,
        message: str,
        tool_calls: list,
        called_tools: list[str],
        matched_tools: list[str],
        required_tool_names: list[str],
        progress: int,
        total_required: int
    ) -> str:
        """
        Generate benchmark-safe conversational response.
        
        NO tool names, NO direct hints, only conceptual guidance.
        """
        missing = [t for t in required_tool_names if t not in called_tools]
        phase = self._determine_phase(progress, total_required, called_tools)
        agent_text = self._extract_message(message)
        
        # === INITIAL: Orient without revealing tools ===
        if phase == TaskPhase.INITIAL:
            # Try multiple possible keys for task description
            task_desc = (
                self.current_task.get("task") or 
                self.current_task.get("instruction") or 
                self.current_task.get("description") or
                "Complete the given task"
            )
            if len(task_desc) > 150:
                task_desc = task_desc[:150] + "..."
            
            return (
                f"Task: {task_desc}\n\n"
                f"Start working on this. Use the available tools to complete it.\n\n"
                f"*{self._get_question(phase)}*"
            )
        
        # === COMPLETE: Celebrate without details ===
        if phase == TaskPhase.COMPLETE:
            return (
                f"## ✅ Complete\n\n"
                f"You've completed all the required steps.\n\n"
                f"**Final check:**\n"
                f"- Does the output match the request?\n"
                f"- Is anything missing?\n\n"
                f"*Mark complete when ready.*"
            )
        
        # === ACTIVE PHASES: Guide abstractly ===
        sections = []
        
        # Acknowledge action taken (without naming tool)
        if tool_calls:
            sections.append(f"✓ *{random.choice(ENCOURAGEMENTS)}*")
        elif agent_text:
            sections.append(f"> {agent_text}")
        
        # Progress indicator
        progress_str = self._create_progress_indicator(progress, total_required)
        if progress_str:
            sections.append(f"\n{progress_str}")
        
        # Workflow hint (abstract)
        hint = self._get_workflow_hint(called_tools, missing)
        if hint:
            sections.append(f"\n💭 {hint}")
        
        # Socratic question
        question = self._get_question(phase)
        sections.append(f"\n---\n\n*{question}*")
        
        return "\n".join(sections)


# =============================================================================
# SIMPLE INTEGRATION
# =============================================================================

def _generate_conversational_response(
    current_task: dict,
    message: str,
    tool_calls: list,
    called_tools: list[str],
    matched_tools: list[str],
    required_tool_names: list[str],
    progress: int,
    total_required: int
) -> str:
    """Drop-in replacement for existing method."""
    
    guide = ConversationalGuide(current_task)
    
    return guide.generate_response(
        message=message,
        tool_calls=tool_calls,
        called_tools=called_tools,
        matched_tools=matched_tools,
        required_tool_names=required_tool_names,
        progress=progress,
        total_required=total_required
    )