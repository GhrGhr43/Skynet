# Hermes oficial + lo que su imagen no trae: ddgs para buscar sin claves (el mismo buscador que usa
# Skynet, misma versión), el navegador agent-browser con Chromium y pytest. Sin tocar nada más.
FROM nousresearch/hermes-agent:latest
USER root
WORKDIR /opt/hermes
# El venv no trae pip: se instala con el uv que la propia imagen lleva fijado. pytest, porque las tareas
# lo usan y Skynet lo tiene en su entorno (misma versión).
RUN /opt/hermes/tools/uv-0.12.3-linux-x64/uv pip install --python .venv/bin/python --no-cache "ddgs==9.16.0" "pytest==9.1.1"
# El repo montado pertenece a otro uid: sin esto git lo rechaza («dubious ownership»). En Windows Skynet no lo sufre.
RUN git config --system --add safe.directory '*'
RUN .venv/bin/hermes pm install agent-browser || echo "agent-browser no se pudo instalar: Hermes irá sin navegador"
