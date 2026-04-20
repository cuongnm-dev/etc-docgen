# etc-docgen MCP Server — SSE transport for remote IDE integration
#
# Build:
#   docker build -t etc-docgen-mcp .
#
# Run:
#   docker run -p 8000:8000 etc-docgen-mcp
#
# Connect from IDE:
#   SSE endpoint: http://localhost:8000/sse

FROM python:3.12-slim

LABEL maintainer="Công ty CP Hệ thống Công nghệ ETC"
LABEL description="etc-docgen MCP Server (SSE transport)"

WORKDIR /app

# Install Node.js + Mermaid CLI (for rendering Mermaid diagrams to PNG)
# Plus Chromium deps since mermaid-cli uses puppeteer/headless browser
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates gnupg \
      # Chromium runtime deps for headless rendering
      chromium fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 \
      libc6 libcairo2 libcups2 libdbus-1-3 libexpat1 libfontconfig1 libgbm1 \
      libglib2.0-0 libgtk-3-0 libnspr4 libnss3 libpango-1.0-0 libx11-6 \
      libx11-xcb1 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
      libxrandr2 libxrender1 libxss1 libxtst6 xdg-utils \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @mermaid-js/mermaid-cli \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Mermaid CLI (puppeteer) config — use system chromium
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# Install build deps
RUN pip install --no-cache-dir --upgrade pip

# Copy project files
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

# Install etc-docgen with serve (uvicorn) extra
RUN pip install --no-cache-dir ".[serve]"

# Non-root user for security
RUN useradd --create-home --shell /bin/bash docgen
USER docgen

EXPOSE 8000

# Health check — SSE endpoint responds
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/sse')" || exit 1

# Default: SSE on all interfaces
ENTRYPOINT ["etc-docgen-mcp"]
CMD ["--transport", "sse", "--host", "0.0.0.0", "--port", "8000"]
