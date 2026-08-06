FROM nousresearch/hermes-agent:latest

USER root
RUN python -m pip install --no-cache-dir "fastapi>=0.110,<1" "uvicorn[standard]>=0.27" "httpx>=0.27"

COPY shared_gateway.py /opt/openakita/shared_gateway.py
RUN chmod 0755 /opt/openakita/shared_gateway.py && mkdir -p /opt/openakita/agents

ENV OPENAKITA_HERMES_AGENT_ROOT=/opt/openakita/agents \
    API_SERVER_HOST=0.0.0.0 \
    API_SERVER_PORT=8642 \
    HERMES_SHARED_MAX_AGENTS=32

EXPOSE 8642
ENTRYPOINT ["python", "/opt/openakita/shared_gateway.py"]
