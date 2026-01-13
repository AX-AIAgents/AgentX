"""
AgentX Agents

This package contains the agent implementations for AgentX.

Architecture:
- AgentX evaluates ANY A2A-compatible agent via HTTP/JSON
- No code import required - agents run as separate servers
- ExternalAgent is an example A2A-compatible agent

Usage:
    # Start your A2A agent on any port
    python -m src.agents.external_agent  # Port 9000
    
    # Run evaluation
    python run.py --task-file tasks.jsonl --external-agent http://localhost:9000

A2A Protocol:
    1. Serve Agent Card at /.well-known/agent.json
    2. Accept messages at POST /a2a/message
    3. Return tool_calls or text responses
"""

# Note: ExternalAgent is a standalone server, not imported as a class
# The A2AClientAdapter in src/a2a_client_adapter.py handles communication

__all__ = []
