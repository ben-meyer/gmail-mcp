# ── Gmail + Calendar MCP Gateway — Docker image ───────────────────────────────
# Multi-stage build: keeps the final image small (no build tools, no cache).
#
# Build:  docker build -t gmail-mcp .
# Run:    docker run -p 8000:8000 \
#           -e GATEWAY_API_KEY=your-secret \
#           -v $(pwd)/data:/data \
#           -v $(pwd)/.gmail-mcp-oauth.json:/app/.gmail-mcp-oauth.json:ro \
#           gmail-mcp

FROM python:3.12-slim AS builder

WORKDIR /build
RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
# Copy lock file if present, otherwise uv will resolve from pyproject.toml
COPY uv.lock* ./
RUN uv export --no-dev --format requirements-txt > requirements.txt
RUN pip install --no-cache-dir -r requirements.txt --target /deps


FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /deps /usr/local/lib/python3.12/site-packages

# Copy application source
COPY *.py ./

# Persistent data volume — mount here to keep tokens across restarts
RUN mkdir -p /data
VOLUME ["/data"]

ENV DB_PATH=/data/tokens.db
ENV PORT=8000
ENV HOST=0.0.0.0
# GATEWAY_API_KEY must be provided at runtime — no default for security

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')"

CMD ["python", "server.py"]
