FROM nousresearch/hermes-agent:latest

USER root

# The official Hermes image already installs Hermes and its Python dependencies
# into /opt/hermes/.venv. Reuse that environment instead of trying to mutate a
# separate system Python installation.
COPY shared_gateway.py /opt/openakita/shared_gateway.py
RUN chmod 0755 /opt/openakita/shared_gateway.py && mkdir -p /opt/openakita/agents

ENV OPENAKITA_HERMES_AGENT_ROOT=/opt/data/openakita-agents \
    API_SERVER_HOST=0.0.0.0 \
    API_SERVER_PORT=8642 \
    HERMES_SHARED_MAX_AGENTS=32

EXPOSE 8642

# Keep the upstream /init + main-wrapper ENTRYPOINT. Hermes uses it to run
# cont-init hooks, initialize s6 supervision, and fix /opt/data ownership.
CMD ["/opt/hermes/.venv/bin/python", "/opt/openakita/shared_gateway.py"]
