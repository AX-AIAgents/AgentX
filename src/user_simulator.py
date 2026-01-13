"""
User Simulator - Hybrid Adversarial User Behavior

**Architecture Philosophy (AgentBeats Standard):**
- TRIGGERS: Rule-based (deterministic, reproducible)
- MESSAGES: Can be static or LLM-enhanced (realistic)
- SCORING: NEVER LLM (always state-based)

This follows τ²-bench "Dual-Control" paradigm:
1. Deterministic trigger logic (when to interject)
2. Natural language variation (what to say)
3. Ground truth validation (state matching for scoring)

Based on AgentBeats requirements and τ²-bench best practices.
"""
import logging
import os
from typing import Any
from dotenv import load_dotenv
load_dotenv()
logger = logging.getLogger("UserSimulator")


class UserSimulator:
    """
    Hybrid User Simulator: Rule-based triggers + Optional LLM messages.
    
    **Design Principles:**
    1. Triggers are DETERMINISTIC (rule-based if/else logic)
    2. Messages can be STATIC (from task) or DYNAMIC (LLM-generated)
    3. Scoring is SEPARATE (state-based, never LLM-as-judge)
    
    **Trigger Types:**
    - Tool-based: "on_tool:cancel_order" → fires when agent calls tool
    - Turn-based: "on_turn:3" → fires on specific turn
    - State-based: "on_state_change:orders.ORD-123.status=cancelled"
    - Message-based: "on_message_contains:refund" → agent says keyword
    
    **Message Modes:**
    - Static: Use pre-defined message from task definition
    - LLM-Enhanced: Generate natural variation using LLM (optional)
    
    Example task event:
    {
        "trigger": "on_tool:cancel_order",
        "reaction_type": "objection",
        "message": "Wait! I changed my mind!",  # Static fallback
        "llm_enhance": false,  # Set true for LLM generation
        "once": true
    }
    """
    
    def __init__(
        self, 
        events: list[dict[str, Any]] | None = None,
        enable_llm: bool = False,
        llm_model: str = "gpt-4o-mini"
    ):
        """
        Initialize user simulator.
        
        Args:
            events: List of simulation events from task definition
            enable_llm: Enable LLM message enhancement (default: False for reproducibility)
            llm_model: LLM model to use if enable_llm=True
        """
        self.events = events or []
        self.triggered = set()
        self.turn_count = 0
        self.conversation_history: list[dict[str, str]] = []
        
        # LLM enhancement (optional)
        self.enable_llm = enable_llm
        self.llm_model = llm_model
        self._llm_client = None
        
        if self.enable_llm:
            try:
                from openai import OpenAI
                self._llm_client = OpenAI()
                logger.info(f"LLM enhancement enabled: {llm_model}")
            except Exception as e:
                logger.warning(f"LLM initialization failed: {e}")
                logger.warning("Falling back to static messages")
                self.enable_llm = False
        
        logger.info(f"User Simulator initialized: {len(self.events)} events, LLM={self.enable_llm}")
    
    def check_trigger(
        self, 
        tool_name: str, 
        tool_args: dict[str, Any],
        agent_message: str = "",
        state: dict[str, Any] | None = None
    ) -> str | None:
        """
        Check if any event should trigger (DETERMINISTIC LOGIC).
        
        This is the RULE-BASED BRAIN of the simulator.
        Returns message if triggered, None otherwise.
        """
        for idx, event in enumerate(self.events):
            event_id = f"event_{idx}"
            
            # Skip if already triggered and once=true
            if event.get("once", True) and event_id in self.triggered:
                continue
            
            trigger = event.get("trigger", "")
            
            # DETERMINISTIC CHECK: Rule-based if/else logic
            triggered = self._check_trigger_condition(
                trigger, tool_name, tool_args, agent_message, state
            )
            
            if triggered:
                self.triggered.add(event_id)
                reaction_type = event.get("reaction_type", "interjection")
                
                # Get message (static or LLM-enhanced)
                message = self._generate_message(event, tool_name, agent_message)
                
                logger.info(f"🎭 User: {reaction_type} triggered by {trigger}")
                
                # Track in conversation history
                self.conversation_history.append({
                    "turn": self.turn_count,
                    "trigger": trigger,
                    "reaction": reaction_type,
                    "message": message,
                    "enhanced": self.enable_llm and event.get("llm_enhance", False)
                })
                
                return message
        
        return None
    
    def _generate_message(
        self, 
        event: dict[str, Any], 
        tool_name: str,
        agent_message: str
    ) -> str:
        """
        Generate user message (STATIC or LLM-ENHANCED).
        
        Priority:
        1. If llm_enhance=true and LLM available → generate natural variation
        2. Otherwise → use static message from task definition
        """
        static_message = event.get("message", "")
        
        # If LLM enhancement not requested or not available, return static
        if not event.get("llm_enhance", False) or not self.enable_llm:
            return static_message
        
        # LLM-ENHANCED: Generate natural variation
        try:
            reaction_type = event.get("reaction_type", "interjection")
            context = event.get("context", "")
            
            enhanced = self._llm_enhance_message(
                reaction_type=reaction_type,
                base_message=static_message,
                tool_name=tool_name,
                agent_message=agent_message,
                context=context
            )
            return enhanced or static_message  # Fallback to static if LLM fails
        
        except Exception as e:
            logger.warning(f"LLM enhancement failed: {e}, using static message")
            return static_message
    
    def _llm_enhance_message(
        self,
        reaction_type: str,
        base_message: str,
        tool_name: str,
        agent_message: str,
        context: str
    ) -> str | None:
        """
        Use LLM to generate natural variation of message.
        
        This is OPTIONAL enhancement for realism.
        Falls back to static message if fails.
        """
        if not self._llm_client:
            return None
        
        prompt = f"""You are simulating a customer in a support conversation.

Reaction Type: {reaction_type}
Tool Agent Just Called: {tool_name}
Agent's Last Message: {agent_message}
Context: {context or "N/A"}
Base Message Intent: {base_message}

Generate a natural, realistic customer message that:
1. Matches the reaction type ({reaction_type})
2. Is appropriate for the context
3. Sounds like a real person (casual, not robotic)
4. Keeps the same intent as base message

Return ONLY the customer message, no explanations."""

        try:
            response = self._llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=100
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"LLM generation failed: {e}")
            return None
    
    def _check_trigger_condition(
        self,
        trigger: str,
        tool_name: str,
        tool_args: dict[str, Any],
        agent_message: str,
        state: dict[str, Any] | None
    ) -> bool:
        """
        DETERMINISTIC RULE-BASED LOGIC.
        
        This is the BRAIN - must be reproducible.
        Checks if trigger condition is met using if/else logic.
        """
        # Tool-based triggers (most common)
        if trigger.startswith("on_tool:") or trigger.startswith("on_tool_success:"):
            target_tool = trigger.split(":", 1)[1]
            return tool_name == target_tool
        
        # Simple tool name match (backward compatibility)
        if trigger == tool_name:
            return True
        
        # Turn-based triggers (temporal logic)
        if trigger.startswith("on_turn:"):
            target_turn = int(trigger.split(":", 1)[1])
            return self.turn_count == target_turn
        
        # Message-based triggers (keyword detection)
        if trigger.startswith("on_message_contains:"):
            keyword = trigger.split(":", 1)[1].lower()
            return keyword in agent_message.lower()
        
        # State-based triggers (ground truth checks)
        if trigger.startswith("on_state_change:") and state:
            condition = trigger.split(":", 1)[1]
            return self._check_state_condition(condition, state)
        
        return False
    
    def _check_state_condition(self, condition: str, state: dict[str, Any]) -> bool:
        """
        Check state using JSON path notation.
        
        Format: "path.to.key=expected_value"
        Example: "orders.ORD-123.status=cancelled"
        
        This is DETERMINISTIC state validation.
        """
        if "=" not in condition:
            return False
        
        path, expected = condition.split("=", 1)
        keys = path.split(".")
        
        # Navigate nested dict
        current = state
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return False
        
        return str(current) == expected
    
    def increment_turn(self) -> None:
        """Increment turn counter (call at start of each turn)."""
        self.turn_count += 1
    
    def reset(self) -> None:
        """Reset simulator state for new evaluation."""
        self.triggered.clear()
        self.turn_count = 0
        self.conversation_history.clear()
        logger.info("User Simulator reset")
    
    def get_statistics(self) -> dict[str, Any]:
        """
        Get simulation statistics for analysis.
        
        Useful for post-evaluation debugging and metrics.
        """
        return {
            "total_events": len(self.events),
            "triggered_events": len(self.triggered),
            "trigger_rate": len(self.triggered) / len(self.events) if self.events else 0,
            "turns_elapsed": self.turn_count,
            "llm_enabled": self.enable_llm,
            "conversation_history": self.conversation_history,
        }


# ============================================================
# Factory Functions
# ============================================================

def create_static_simulator(events: list[dict[str, Any]]) -> UserSimulator:
    """
    Create simulator with STATIC messages only (reproducible).
    
    Recommended for benchmarking and official evaluation.
    """
    return UserSimulator(events=events, enable_llm=False)


def create_llm_simulator(
    events: list[dict[str, Any]], 
    model: str = "gpt-4o-mini"
) -> UserSimulator:
    """
    Create simulator with LLM-enhanced messages (realistic but non-deterministic).
    
    Recommended for testing and development only.
    Set llm_enhance=true in event definitions to enable per-event.
    """
    return UserSimulator(events=events, enable_llm=True, llm_model=model)


# ============================================================
# Example Usage & Testing
# ============================================================

def example_static_simulator():
    """Example: Static (reproducible) simulator for benchmarking."""
    print("\n=== STATIC SIMULATOR (Reproducible) ===")
    
    events = [
        {
            "trigger": "on_tool:cancel_order",
            "reaction_type": "objection",
            "message": "Wait! I changed my mind. Don't cancel it!",
            "once": True
        },
        {
            "trigger": "on_turn:3",
            "reaction_type": "escalation",
            "message": "This is taking too long!",
            "once": True
        }
    ]
    
    sim = create_static_simulator(events)
    
    # Simulate turns
    for turn in range(1, 5):
        sim.increment_turn()
        
        if turn == 2:
            msg = sim.check_trigger("cancel_order", {})
            if msg:
                print(f"Turn {turn}: {msg}")
        
        if turn == 3:
            msg = sim.check_trigger("", {})
            if msg:
                print(f"Turn {turn}: {msg}")
    
    print(f"Stats: {sim.get_statistics()}")


def example_llm_simulator():
    """Example: LLM-enhanced simulator for realistic testing."""
    print("\n=== LLM-ENHANCED SIMULATOR (Realistic) ===")
    
    events = [
        {
            "trigger": "on_tool:cancel_order",
            "reaction_type": "objection",
            "message": "Wait! I changed my mind.",
            "llm_enhance": True,  # Enable LLM variation
            "context": "Customer is hesitant about cancelling expensive order",
            "once": True
        }
    ]
    
    sim = create_llm_simulator(events)
    
    sim.increment_turn()
    msg = sim.check_trigger("cancel_order", {}, agent_message="I will cancel your order now.")
    if msg:
        print(f"LLM-Enhanced: {msg}")
    else:
        print("LLM not available, would use static message")
    
    print(f"Stats: {sim.get_statistics()}")


if __name__ == "__main__":
    print("=" * 60)
    print("User Simulator - Hybrid Architecture Demo")
    print("Rule-based Triggers + Optional LLM Messages")
    print("=" * 60)
    
    example_static_simulator()
    example_llm_simulator()
