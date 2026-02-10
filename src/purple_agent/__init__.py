"""
Purple Agent - Advanced A2A Agent
==================================

Gelişmiş özelliklere sahip A2A uyumlu agent modülü.

Features:
- Multi-Model Support (GPT-4o, GPT-4o-mini, Claude)
- Retry Logic with Exponential Backoff
- Parallel Tool Execution
- Structured Output with Pydantic
- Memory Management (Sliding Window)
- Metrics Tracking
- Graceful Shutdown

Usage:
    # Start the server
    python -m src.purple_agent.server --host 0.0.0.0 --port 9000
    
    # Or use external_agent for standalone mode
    python -m src.purple_agent.external_agent

A2A Protocol:
    1. Agent Card: GET /.well-known/agent.json
    2. Messages: POST /a2a/message (or POST /)
    3. Health: GET /health
"""

from src.purple_agent.agent import AdvancedPurpleAgent
from src.purple_agent.executor import AdvancedPurpleExecutor

__all__ = ["AdvancedPurpleAgent", "AdvancedPurpleExecutor"]
