FROM nousresearch/hermes-agent:v2026.7.20

USER root

# Keep the OpenAkita shared gateway inside the image. Coolify builds from a
# temporary checkout under /artifacts; runtime bind mounts to that checkout can
# disappear after deployment cleanup and make the container restart forever.
RUN mkdir -p /opt/openakita /opt/openakita/agents
COPY --chown=hermes:hermes deploy/hermes/shared_gateway.py /opt/openakita/shared_gateway.py
RUN chmod 0755 /opt/openakita/shared_gateway.py

ENV OPENAKITA_HERMES_AGENT_ROOT=/opt/data/openakita-agents \
    API_SERVER_HOST=0.0.0.0 \
    API_SERVER_PORT=8642 \
    HERMES_SHARED_MAX_AGENTS=32

EXPOSE 8642

# Preserve the upstream /init + main-wrapper ENTRYPOINT. The wrapper recognizes
# the absolute Python executable and drops privileges to the hermes user after
# s6 has initialized /opt/data.
CMD ["/opt/hermes/.venv/bin/python", "/opt/openakita/shared_gateway.py"]
