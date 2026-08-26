# Rakuten veille — single image, two entrypoints (collector CronJob OR dashboard server)
FROM python:3.13-alpine

WORKDIR /app

# pure stdlib — no pip install needed; keep image minimal and repeatable
COPY src/ ./src/

# default = dashboard server (port 8080); override CMD for the collector CronJob
ENV DB_PATH=/data/posts.db
ENV HOST=0.0.0.0
ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -q -O - http://127.0.0.1:${PORT}/healthz || exit 1

CMD ["python3", "src/server.py"]