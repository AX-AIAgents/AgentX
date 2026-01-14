# ========================================
# AgentX Green Agent - Dockerfile
# ========================================
# AgentBeats Compatible Green Agent (Assessor)
# 
# Build:
#   docker build --platform linux/amd64 -t ghcr.io/USERNAME/agentx-green:v1 .
#
# Run:
#   docker run -p 8090:8090 -e OPENAI_API_KEY=xxx ghcr.io/USERNAME/agentx-green:v1
# ========================================

FROM --platform=linux/amd64 python:3.13-slim

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
COPY scenario.toml ./

# Create directories for logs and results
RUN mkdir -p results historical_trajectories

# Create Gmail OAuth directory and dummy credentials for MOCK_MODE
RUN mkdir -p /root/.gmail-mcp && \
    echo '{"web":{"client_id":"dummy-client-id","client_secret":"dummy-secret","redirect_uris":["http://localhost"],"auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token"}}' > /root/.gmail-mcp/gcp-oauth.keys.json && \
    echo '{"type":"authorized_user","client_id":"dummy-client-id","client_secret":"dummy-secret","refresh_token":"dummy-refresh-token"}' > /root/.gmail-mcp/credentials.json && \
    echo '{"access_token":"dummy-access-token","expires_in":3599,"refresh_token":"dummy-refresh-token","scope":"https://mail.google.com/","token_type":"Bearer"}' > /root/.gmail-mcp/token.json

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

# Dummy API keys for MCP servers (MOCK_MODE=true so not actually used)
ENV SERPER_API_KEY=dummy_serper_key_for_mock_mode
ENV NOTION_TOKEN=dummy_notion_token_for_mock_mode
ENV GOOGLE_DRIVE_OAUTH_CREDENTIALS=dummy_gdrive_oauth_for_mock_mode

# AgentBeats required: ENTRYPOINT with --host, --port, --card-url support
ENTRYPOINT ["uv", "run", "src/server.py"]
CMD ["--host", "0.0.0.0", "--port", "8090"]
