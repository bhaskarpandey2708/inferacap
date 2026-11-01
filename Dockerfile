# InferaCap: The Economically-Aware Multi-Region Inference Load Balancer
# Minimal Multi-Stage Hardened Container

FROM python:3.11-slim AS builder

WORKDIR /build
COPY . /build/

# Remove cache and temporary test logs
RUN find . -type d -name "__pycache__" -exec rm -rf {} + && \
    find . -type f -name "*.pyc" -delete

FROM python:3.11-slim AS runtime

# Security hardening: Create unprivileged user
RUN groupadd -g 10001 inferacap && \
    useradd -u 10001 -g inferacap -s /bin/sh -d /app inferacap && \
    mkdir -p /app/gateway /app/data && \
    chown -R inferacap:inferacap /app

WORKDIR /app

# Copy application files
COPY --chown=inferacap:inferacap --from=builder /build/*.py /app/
COPY --chown=inferacap:inferacap --from=builder /build/*.html /app/
COPY --chown=inferacap:inferacap --from=builder /build/*.js /app/
COPY --chown=inferacap:inferacap --from=builder /build/*.json /app/
COPY --chown=inferacap:inferacap --from=builder /build/gateway /app/gateway/

USER 10001:10001

# Expose Gateway (8765) and Web UI (8764)
EXPOSE 8765 8764

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8765/health")' || exit 1

ENTRYPOINT ["python3", "demo_inferacap.py"]
