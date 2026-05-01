# etc-platform unified server — HTTP job API + MCP transports.
#
# Build:
#   docker build -t etc-platform .
#
# Run:
#   docker run -p 8001:8000 -v $(pwd)/data:/data etc-platform
#
# Endpoints:
#   POST /uploads             — multipart upload of content_data.json
#   POST /jobs                — create render job
#   GET  /jobs/{id}           — poll status
#   GET  /jobs/{id}/files/... — download outputs
#   /mcp                      — MCP streamable-http transport
#   /sse                      — MCP SSE transport (legacy)
#   /healthz, /readyz         — probes

FROM python:3.12-slim

LABEL maintainer="Công ty CP Hệ thống Công nghệ ETC"
LABEL description="etc-platform MCP Server (SSE transport)"

WORKDIR /app

# Install Node.js + Mermaid CLI (for rendering Mermaid diagrams to PNG)
# Plus Chromium deps since mermaid-cli uses puppeteer/headless browser
# Plus PlantUML + Graphviz + JRE for cleaner architecture/network/sequence diagrams
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates gnupg \
      # Chromium runtime deps for headless rendering
      chromium fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 \
      libc6 libcairo2 libcups2 libdbus-1-3 libexpat1 libfontconfig1 libgbm1 \
      libglib2.0-0 libgtk-3-0 libnspr4 libnss3 libpango-1.0-0 libx11-6 \
      libx11-xcb1 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
      libxrandr2 libxrender1 libxss1 libxtst6 xdg-utils \
      # PlantUML stack: jre headless + graphviz (dot) for layout engine
      default-jre-headless graphviz \
      # Vietnamese fonts so PlantUML/Mermaid render diacritics correctly
      fonts-dejavu fonts-noto-core fonts-noto-cjk \
      # cairosvg native deps (libcairo + libpango + libffi for SVG hero templates)
      libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi8 shared-mime-info \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @mermaid-js/mermaid-cli \
    # Download PlantUML jar (pinned version) — placed at /opt/plantuml/plantuml.jar
    && mkdir -p /opt/plantuml \
    && curl -fsSL -o /opt/plantuml/plantuml.jar \
        https://github.com/plantuml/plantuml/releases/download/v1.2024.7/plantuml-1.2024.7.jar \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Mermaid CLI (puppeteer) config — use system chromium
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    PLANTUML_JAR=/opt/plantuml/plantuml.jar \
    PLANTUML_LIMIT_SIZE=16384

# Install build deps
RUN pip install --no-cache-dir --upgrade pip

# Copy project files
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

# Bake immutable outlines (G1: NĐ 30/2020 outline templates) into image at
# /app/data/outlines so they ship with the container regardless of volume mounts.
# outlines.py falls back to this path when /data/outlines is empty (default
# member setup with `./data:/data` volume containing only _jobs/).
COPY data/ /app/data/

# Install etc-platform with serve (uvicorn) extra
RUN pip install --no-cache-dir ".[serve]"

# Non-root user for security
RUN useradd --create-home --shell /bin/bash docgen
USER docgen

EXPOSE 8000

# Health check — HTTP /healthz responds quickly without touching storage.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz', timeout=3).status==200 else 1)" \
    || exit 1

# Default: unified ASGI server (HTTP + MCP) on all interfaces.
ENTRYPOINT ["etc-platform-server"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
