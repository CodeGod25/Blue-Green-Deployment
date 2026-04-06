# Project Titanium — Blue-Green Deployment Control Plane

> A production-grade DevOps observatory with real zero-downtime deployments, a live Chaos Engineering lab, canary traffic steering, and autonomous safety guardrails.

---

## What is this?

**Project Titanium** is an interactive, fully containerised demonstration of industry-standard deployment engineering. It shows the mechanics behind services like Vercel, AWS CodeDeploy, and Kubernetes rolling updates — all running locally via Docker Compose.

Instead of updating a server in-place (causing downtime), two identical environments exist simultaneously — **Blue** (stable) and **Green** (next release). Traffic is managed at the Nginx proxy layer. The Titanium Control Plane dashboard lets you:

- Promote releases with zero dropped requests
- Steer traffic with weighted Canary splits
- Inject real and simulated chaos experiments
- Watch autonomous safety guardrails trigger rollbacks
- Monitor telemetry in real-time via SSE streaming

---

## Quick Start

### Prerequisites
- **Docker Desktop** installed and running on your machine.
- (Windows users) Powershell or Command Prompt.
- (Mac/Linux users) Bash or Zsh.

### 1. Run the Platform
The platform is designed to be "zero-configuration" and portable. 

**Windows:**
Double-click `START.bat`

**Mac/Linux:**
```bash
chmod +x start.sh && ./start.sh
```

- **Smart Port Detection**: If your default port (80) is busy, the script automatically finds the next available port (e.g., 8080) and uses it. No manual setup required.
- **Auto Environment**: Creates its own `.env` on first run.
- **Dashboard**: Opens the dashboard automatically at the correct address.
- **Cleans Up**: Press any key (Windows) or Ctrl+C (Mac/Linux) to stop and remove containers cleanly.

### 2. Manual Customization (Optional)
If you want to force a specific port:
1. Edit the `.env` file created by the script.
2. Change `HTTP_PORT=80` to your desired port.
3. Re-run the startup script.

---

## Architecture

```
http://localhost/
│
├── /                → Project Titanium React Dashboard
│   ├── Overview        — Live RPS, latency, success rate sparklines
│   ├── Infrastructure  — Service topology, canary slider, promotion controls
│   ├── Security        — Guardrail audit log, safety trigger history
│   ├── Chaos Lab       — Real & simulated fault injection
│   └── System Logs     — Live structured event stream
│
├── /app/            → Active application (Blue or Green via Nginx upstream)
│                       Routing written to: proxy/conf.d/active-upstream.conf
│
├── /blue/           → Blue environment (v1.0) — direct access for verification
├── /green/          → Green environment (v2.0) — direct access for verification
│
└── /api/            → Monitor API (port 8090 internally)
    ├── GET  /api/status          — Full system state snapshot
    ├── GET  /api/events/stream   — SSE telemetry stream
    ├── POST /api/deploy          — Promote to target environment
    ├── POST /api/canary          — Update weighted traffic split
    └── POST /api/chaos           — Inject/restore fault experiments
```

---

## Services

| Container              | Role                                              |
|------------------------|---------------------------------------------------|
| `blue-app`             | Blue environment (v1.0) — Nginx serving static app |
| `green-app`            | Green environment (v2.0) — Nginx serving static app |
| `blue-green-proxy`     | Nginx reverse proxy, port 80 — routes all traffic  |
| `blue-green-monitor`   | Python control plane API + SSE telemetry engine    |
| `blue-green-dashboard` | React/Vite dashboard served via Nginx              |

---

## Chaos Engineering Lab

The Chaos Lab provides two categories of fault injection:

### 🟢 Network Simulation (Proxy-level — no containers stopped)
| Mode | Mechanism | Impact |
|------|-----------|--------|
| **Latency Jitter** | Nginx routes through monitor `/slow` | 1–4s random delay per request |
| **Packet Loss** | Nginx routes through monitor — 10% random 500s | ~10% of requests fail |

### 🔴 Real Docker Manipulation (Actual container lifecycle)
| Mode | Mechanism | Impact |
|------|-----------|--------|
| **Critical Fail** | `docker stop <active-container>` | Active environment goes down, Health Grid turns red |
| **Net Blackout** | `docker stop blue-app green-app` | Total service outage, 502 from proxy |
| **Restore System** | `docker start blue-app green-app` + Nginx reload | Full recovery in ~2-3 seconds |

All chaos experiments auto-restore after 30 seconds. Manual restore is always available.

---

## Key Features

- **Zero-Downtime Promotion** — Atomic Nginx upstream swap with real health-gate enforcement
- **Canary Traffic Splitting** — Weighted Nginx upstreams (e.g. 80% Blue / 20% Green)
- **Autonomous Guardrails** — Auto-rollback if error rate > 5% or latency > 500ms
- **Real SSE Telemetry** — Server-Sent Events stream updates the dashboard live (polling fallback)
- **Structured Event Log** — JSONL audit trail of all system events

---

## Verifying Zero Downtime

The **Live Probe** counter in the top bar sends a HEAD request to `/app/` every 400ms and counts OK vs FAIL responses. Click any chaos mode or promotion — you'll see exactly how many (if any) requests dropped.

For Latency/Jitter/Loss modes: **success rate falls, containers stay up.**  
For Blackout/Critical Fail modes: **health grid goes red, containers are actually stopped.**  
After Restore: **health grid turns green, containers are running again.**

---

## Stack

- **Frontend:** React 18 + Vite, Vanilla CSS, Lucide icons
- **Backend:** Python 3.12 standard library HTTP server (no frameworks)
- **Proxy:** Nginx 1.27 Alpine
- **Container Runtime:** Docker Compose v2
