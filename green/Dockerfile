FROM nginx:1.27.0-alpine

# Security: Create non-root user
RUN addgroup -S appuser && adduser -S appuser -G appuser

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY html/ /usr/share/nginx/html/

# Create necessary cache directories with proper ownership
# Modify nginx.conf to use /tmp for pid and comment out user directive
RUN mkdir -p /var/cache/nginx/client_temp /var/cache/nginx/proxy_temp /var/cache/nginx/uwsgi_temp && \
    chown -R appuser:appuser /var/cache/nginx /usr/share/nginx && \
    chmod -R 755 /usr/share/nginx/html /var/cache/nginx && \
    sed -i 's,pid        /var/run/nginx.pid;,pid        /tmp/nginx.pid;,' /etc/nginx/nginx.conf && \
    sed -i 's,^user  nginx;,# user nginx;,' /etc/nginx/nginx.conf

USER appuser

EXPOSE 80

HEALTHCHECK --interval=5s --timeout=2s --retries=3 \
  CMD wget -qO- http://127.0.0.1/healthz || exit 1
