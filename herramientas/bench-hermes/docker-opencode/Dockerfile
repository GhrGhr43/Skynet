# OpenCode (binario oficial de npm, versión fijada) en Linux, con lo mismo que tienen Skynet y Hermes en las
# pruebas: Python 3.14 + pytest, git, y el MCP `internet` de Skynet (OpenCode solo trae lectura de URLs, no
# buscador). El código del MCP se monta desde el repo de Skynet en /skynet.
FROM python:3.14-slim
ARG OPENCODE_VERSION=1.18.35
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL "https://registry.npmjs.org/opencode-linux-x64/-/opencode-linux-x64-${OPENCODE_VERSION}.tgz" \
    | tar -xz -C /opt && ln -s /opt/package/bin/opencode /usr/local/bin/opencode \
 && pip install --no-cache-dir "pytest==9.1.1" "mcp==2.3.0" "httpx==0.28.1" "ddgs==9.16.0" \
 && git config --system --add safe.directory '*' \
 && git config --system user.name bench && git config --system user.email bench@example.com
ENV PYTHONPATH=/skynet
WORKDIR /workspace
ENTRYPOINT ["opencode"]
