# ========================================
# AgentX Green Agent - Dockerfile
# ========================================
# Phase 1 Teslimat: Green Agent (Assessor) + MCP Server
# AgentBeats Competition Ready
# ========================================

FROM python:3.13-slim

# Metadata
LABEL maintainer="AgentX Team"
LABEL description="AgentX Green Agent - A2A Protocol Evaluator for AgentBeats"
LABEL version="1.0.0"

# Prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Working directory
WORKDIR /app

# Install system dependencies + Node.js (for MCP servers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Verify installations
RUN node --version && npm --version && python --version

# Install uv for faster package management
RUN pip install --no-cache-dir uv

# Install npx globally (comes with npm, but ensure it's available)
RUN npm install -g npm@latest

# Copy dependency files first (for better caching)
COPY pyproject.toml uv.lock README.md ./

# Install Python dependencies
RUN uv sync --frozen --no-dev

# Copy application code (includes src/data with task_definitions.jsonl)
COPY src/ ./src/
COPY run.sh scenario.toml ./

# Make scripts executable
RUN chmod +x run.sh

# Create directories for logs and results
RUN mkdir -p results historical_trajectories

# Expose ports
# 8090: Green Agent (A2A) - controlled by AGENT_PORT env var
# 8091: MCP Server (Tools)
EXPOSE 8090 8091

# Health check - uses dynamic port from AGENT_PORT
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8090}/health || exit 1

# Environment variables
ENV PYTHONPATH=/app
ENV MCP_PORT=8091
ENV MOCK_MODE=true

# Start with run.sh (respects AGENT_PORT from AgentBeats Controller)
CMD ["./run.sh"]
