FROM python:3.12-alpine

# Install curl for health checks, bash for script execution, and docker for Nginx reload
RUN apk add --no-cache curl bash docker

# Security: Create non-root user
RUN addgroup -S appuser && adduser -S appuser -G appuser

WORKDIR /app

# Copy files with ownership to appuser
COPY --chown=appuser:appuser monitor.py /app/monitor.py
COPY --chown=appuser:appuser static /app/static

RUN chmod 644 /app/monitor.py && chmod -R 755 /app/static

# Switch to non-root user
USER appuser

EXPOSE 8090

HEALTHCHECK --interval=5s --timeout=2s --retries=3 \
  CMD curl -sf http://127.0.0.1:8090/healthz || exit 1

CMD ["python", "/app/monitor.py"]
