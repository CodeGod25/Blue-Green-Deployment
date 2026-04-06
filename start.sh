#!/usr/bin/env bash
# Project Titanium — Cross-platform Startup Script (Mac / Linux)
# Usage: chmod +x start.sh && ./start.sh

set -e
cd "$(dirname "$0")"

echo ""
echo "  ========================================"
echo "   Project Titanium — Blue-Green Platform"
echo "  ========================================"
echo ""

# [0.5/3] Prepare configuration
if [ ! -f ".env" ]; then
    echo "  Creating .env from template..."
    cp .env.example .env
fi

# [0.6/3] Initialize Nginx upstream (Crucial for fresh clones)
if [ ! -f "proxy/conf.d/active-upstream.conf" ]; then
    echo "  Initializing active-upstream.conf..."
    cat <<EOF > proxy/conf.d/active-upstream.conf
upstream active_backend {
  server blue:80 weight=100;
  keepalive 64;
}
EOF
fi

# Initial port choice
HTTP_PORT=$(grep HTTP_PORT .env | cut -d '=' -f2 || echo "80")
[ -z "$HTTP_PORT" ] && HTTP_PORT="80"

# [0.7/3] Port search logic
echo "  [0/2] Checking port availability..."
while lsof -Pi :$HTTP_PORT -sTCP:LISTEN -t >/dev/null 2>&1 || netstat -an | grep "\.$HTTP_PORT " >/dev/null 2>&1 || netstat -an | grep ":$HTTP_PORT " >/dev/null 2>&1; do
    echo "  Port $HTTP_PORT is busy by another application."
    if [ "$HTTP_PORT" -eq 80 ]; then
        HTTP_PORT=8080
    else
        HTTP_PORT=$((HTTP_PORT + 1))
    fi
    echo "  Trying next port: $HTTP_PORT..."
done

# Export for Docker Compose
export HTTP_PORT
echo "  [✓] Using port: $HTTP_PORT (Host) -> 80 (Container)"

# Check Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "  ERROR: Docker is not running."
    echo "  Please start Docker Desktop (or your Docker daemon) and try again."
    exit 1
fi
echo "  [✓] Docker is running."

# Tear down any previous run
echo ""
echo "  [1/3] Stopping any old containers..."
docker compose down 2>/dev/null || true

# Build and start all services
echo ""
echo "  [2/3] Building images and starting all services..."
echo "        (First run will take ~2 minutes to build the frontend — grab a coffee)"
docker compose up -d --build

echo ""
echo "  [3/3] Waiting for services to be healthy..."
sleep 8

echo ""
echo "  ========================================"
echo "   Platform is UP!"
echo ""
if [ "$HTTP_PORT" == "80" ]; then
    echo "   Open: http://localhost"
else
    echo "   Open: http://localhost:$HTTP_PORT"
fi
echo "  ========================================"
echo ""
echo "  Press Ctrl+C to stop the platform."
echo ""

# Wait and tail logs (Ctrl+C to exit)
trap 'echo ""; echo "  Stopping platform..."; docker compose down; echo "  Goodbye!"; exit 0' INT
docker compose logs -f --tail=20
