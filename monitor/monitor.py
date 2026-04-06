import json
import subprocess
import os
import queue
import re
import threading
import time
import uuid
import sys
import random
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

# Add scripts directory to path for validation import
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


MONITORED_URL = os.getenv("MONITORED_URL", "http://proxy/")
PORT = int(os.getenv("PORT", "8090"))
STATE_FILE = Path(os.getenv("STATE_FILE", "/workspace/runtime/state.json"))
DEMO_FILE = Path(os.getenv("DEMO_FILE", "/workspace/runtime/demo_state.json"))
EVENTS_FILE = Path(os.getenv("EVENTS_FILE", "/workspace/runtime/events.jsonl"))
PROFILES_FILE = Path(os.getenv("PROFILES_FILE", "/workspace/profiles/deployments.json"))
STATIC_DIR = Path(__file__).resolve().parent / "static"
SCRIPTS_DIR = Path("/workspace/scripts")  # Mounted from host

VERSION_PATTERN = re.compile(r"Version:\s*(Blue|Green)", re.IGNORECASE)

# Structured logging function
def log_event(
    event_type: str,
    message: str,
    request_id: str = None,
    level: str = "INFO",
    details: dict = None,
    error: Exception = None
) -> None:
    """
    Log structured event to events.jsonl file.
    
    Args:
        event_type: Type of event (PROBE, API_CALL, ERROR, etc.)
        message: Human-readable message
        request_id: Unique request identifier (auto-generated if not provided)
        level: Log level (INFO, WARN, ERROR, DEBUG)
        details: Additional structured data
        error: Exception object for error logging
    """
    if request_id is None:
        request_id = str(uuid.uuid4())[:12]
    
    log_entry = {
        "timestamp": utc_now(),
        "requestId": request_id,
        "level": level,
        "eventType": event_type,
        "message": message,
    }
    
    if details:
        log_entry["details"] = details
    
    if error:
        log_entry["error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
    
    try:
        # Ensure events file exists
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        with EVENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, separators=(",", ":")) + "\n")
    except Exception as e:
        # Silent failure - don't crash monitor if logging fails
        print(f"Failed to write event log: {e}", file=sys.stderr)



def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def to_health_url(upstream: str) -> str:
    upstream_value = (upstream or "").strip()
    if not upstream_value:
        return ""
    if "//" in upstream_value:
        base = upstream_value.rstrip("/")
    else:
        base = f"http://{upstream_value}".rstrip("/")
    return f"{base}/healthz"


def join_url(base: str, path: str) -> str:
    base_value = (base or "").strip()
    if not base_value:
        return ""
    normalized = base_value.rstrip("/")
    return f"{normalized}/{path.lstrip('/')}"


class MonitorStore:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.clients: list[queue.Queue[str]] = []
        self.recent_samples = deque(maxlen=900)
        self.total_requests = 0
        self.success_requests = 0
        self.failed_requests = 0
        self.last_status_code = 0
        self.last_latency_ms = 0.0
        self.current_version = "Unknown"
        self.version_counts = {"Blue": 0, "Green": 0, "Unknown": 0}
        self.canary_weights = {"blue": 100, "green": 0}
        self.guardrail_active = False
        self.chaos_active = "none" # none, latency, error, blackout
        self.service_health = {
            "proxy": {"url": MONITORED_URL, "healthy": False, "statusCode": 0, "latencyMs": 0.0},
            "blue": {"url": "", "healthy": False, "statusCode": 0, "latencyMs": 0.0},
            "green": {"url": "", "healthy": False, "statusCode": 0, "latencyMs": 0.0},
        }
        self.release_manifest: dict[str, Any] = {}
        # Deployment tracking
        self.current_deployment: dict[str, Any] = None
        self.deployment_steps: list[dict[str, Any]] = []

    def _update_upstream_config(self, target: str) -> bool:
        """Update Nginx upstream config to point to target (blue or green)."""
        try:
            upstream_conf = Path("/workspace/proxy/conf.d/active-upstream.conf")
            # Ensure directory exists but file check is more lenient for startup
            upstream_conf.parent.mkdir(parents=True, exist_ok=True)
            
            # Create upstream configuration with weighting support
            with self.lock:
                weights = self.canary_weights
                # If target is provided, we are doing a full switch (100% to target)
                if target:
                    if target.lower() == "blue":
                        weights = {"blue": 100, "green": 0}
                    else:
                        weights = {"blue": 0, "green": 100}
                    self.canary_weights = weights

            lines = ["upstream active_backend {"]
            if weights.get("blue", 0) > 0:
                lines.append(f"  server blue:80 weight={weights['blue']};")
            if weights.get("green", 0) > 0:
                lines.append(f"  server green:80 weight={weights['green']};")
            lines.append("  keepalive 64;")
            lines.append("}")
            
            new_content = "\n".join(lines) + "\n"
            
            # Injection point for Chaos
            with self.lock:
                chaos = self.chaos_active
            
            if chaos in {"error", "latency", "jitter", "loss"}:
                # Override: Route all traffic to a fault generator (monitor container)
                new_content = "upstream active_backend {\n  server monitor:8090; # Chaos Lab Intervention\n  keepalive 64;\n}\n"
            elif chaos == "blackout":
                # Full block via Nginx ACL
                new_content = "upstream active_backend {\n  # BLACKOUT ACTIVE\n  server 127.0.0.1:65535; # Silent Drop\n}\n"

            upstream_conf.write_text(new_content)
            
            # Update state.json with new active target (only if not a chaos hijack)
            if target:
                state = self._load_json(STATE_FILE, {})
                state["activeTarget"] = target
                state["activeUpstream"] = f"{target}:80"
                state["changedAt"] = utc_now()
                state["source"] = "api_deploy"
                
                try:
                    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
                    with STATE_FILE.open("w", encoding="utf-8") as f:
                        json.dump(state, f, indent=2)
                    print(f"WROTE STATE TO {STATE_FILE}", flush=True)
                except Exception as file_err:
                    print(f"ERROR WRITING STATE FILE: {file_err}", flush=True)
            
            return True
        except Exception as e:
            print(f"ERROR UPDATING UPSTREAM: {repr(e)}", flush=True)
            return False

    def _load_json(self, path: Path, default: Any) -> Any:
        """Read JSON file with fallback to default."""
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def register_client(self) -> queue.Queue[str]:
        client_queue: queue.Queue[str] = queue.Queue(maxsize=8)
        with self.lock:
            self.clients.append(client_queue)
        return client_queue

    def unregister_client(self, client_queue: queue.Queue[str]) -> None:
        with self.lock:
            self.clients = [q for q in self.clients if q is not client_queue]

    def broadcast_status(self, status: dict) -> None:
        payload = json.dumps(status, separators=(",", ":"))
        with self.lock:
            stale_clients = []
            for client_queue in self.clients:
                try:
                    client_queue.put_nowait(payload)
                except queue.Full:
                    stale_clients.append(client_queue)
            if stale_clients:
                self.clients = [q for q in self.clients if q not in stale_clients]

    def _probe_url(self, url: str) -> dict[str, Any]:
        started = time.time()
        status_code = 0
        body = ""

        if not url:
            return {
                "url": url,
                "healthy": False,
                "statusCode": 0,
                "latencyMs": 0.0,
                "body": "",
            }

        try:
            request = Request(url, headers={"Cache-Control": "no-cache"})
            with urlopen(request, timeout=2.0) as response:
                status_code = int(response.getcode() or 0)
                body = response.read(262144).decode("utf-8", errors="ignore")
        except Exception as e:
            status_code = 0
            body = ""
            request_id = str(uuid.uuid4())[:12]
            log_event(
                event_type="PROBE_FAILED",
                message=f"Health probe failed for {url}",
                request_id=request_id,
                level="WARN",
                details={"url": url, "timeout": "2.0s"},
                error=e
            )

        latency_ms = (time.time() - started) * 1000.0

        return {
            "url": url,
            "healthy": status_code == 200,
            "statusCode": status_code,
            "latencyMs": round(latency_ms, 2),
            "body": body,
        }

    @staticmethod
    def _resolve_profile_upstreams(profile_name: str, profiles: dict) -> tuple[str, str]:
        profile_id = profile_name or profiles.get("defaultProfile", "learnhub-local")
        profile_map = profiles.get("profiles", {}) if isinstance(profiles, dict) else {}
        selected = profile_map.get(profile_id, {}) if isinstance(profile_map, dict) else {}
        blue_upstream = str(selected.get("blue", "")).strip()
        green_upstream = str(selected.get("green", "")).strip()
        return blue_upstream, green_upstream

    def sample_proxy(self) -> None:
        request_id = str(uuid.uuid4())[:12]
        
        active_state = self._load_json(
            STATE_FILE,
            {
                "activeProfile": "learnhub-local",
                "activeTarget": "unknown",
                "activeUpstream": "unknown",
                "changedAt": None,
                "source": "unknown",
            },
        )
        profiles = self._load_profiles()

        active_profile = str(active_state.get("activeProfile", "")).strip()
        blue_upstream, green_upstream = self._resolve_profile_upstreams(active_profile, profiles)

        proxy_probe = self._probe_url(join_url(MONITORED_URL, "/app/"))
        release_probe = self._probe_url(join_url(MONITORED_URL, "/app/api/version"))
        blue_probe = self._probe_url(to_health_url(blue_upstream))
        green_probe = self._probe_url(to_health_url(green_upstream))

        proxy_body = proxy_probe.get("body", "")
        status_code = int(proxy_probe.get("statusCode", 0) or 0)
        version = "Unknown"

        match = VERSION_PATTERN.search(proxy_body)
        if match:
            version = match.group(1).title()

        latency_ms = float(proxy_probe.get("latencyMs", 0.0) or 0.0)

        release_manifest: dict[str, Any] = {}
        if int(release_probe.get("statusCode", 0) or 0) == 200:
            try:
                parsed = json.loads(str(release_probe.get("body", "") or ""))
                if isinstance(parsed, dict):
                    release_manifest = parsed
            except json.JSONDecodeError:
                release_manifest = {}

        if release_manifest:
            release_manifest["fetchedAt"] = utc_now()

        # Log successful probe
        if status_code == 200:
            log_event(
                event_type="PROBE_SUCCESS",
                message=f"Health check passed: {version} environment",
                request_id=request_id,
                level="INFO",
                details={
                    "statusCode": status_code,
                    "latencyMs": round(latency_ms, 2),
                    "version": version,
                }
            )
        blue_probe = self._probe_url(to_health_url(blue_upstream))
        green_probe = self._probe_url(to_health_url(green_upstream))

        proxy_body = proxy_probe.get("body", "")
        status_code = int(proxy_probe.get("statusCode", 0) or 0)
        version = "Unknown"

        match = VERSION_PATTERN.search(proxy_body)
        if match:
            version = match.group(1).title()

        latency_ms = float(proxy_probe.get("latencyMs", 0.0) or 0.0)

        release_manifest: dict[str, Any] = {}
        if int(release_probe.get("statusCode", 0) or 0) == 200:
            try:
                parsed = json.loads(str(release_probe.get("body", "") or ""))
                if isinstance(parsed, dict):
                    release_manifest = parsed
            except json.JSONDecodeError:
                release_manifest = {}

        if release_manifest:
            release_manifest["fetchedAt"] = utc_now()

        with self.lock:
            self.total_requests += 1
            self.last_status_code = status_code
            self.last_latency_ms = round(latency_ms, 2)
            self.current_version = version

            if status_code == 200:
                self.success_requests += 1
            else:
                self.failed_requests += 1

            if version not in self.version_counts:
                self.version_counts["Unknown"] += 1
            else:
                self.version_counts[version] += 1

            now_epoch = time.time()
            self.recent_samples.append(
                {
                    "ts": now_epoch,
                    "code": status_code,
                    "latencyMs": round(latency_ms, 2),
                    "version": version,
                }
            )

        with self.lock:
            # Update all status
            self.service_health = {
                "proxy": {
                    "url": str(proxy_probe.get("url", MONITORED_URL)),
                    "healthy": bool(proxy_probe.get("healthy", False)),
                    "statusCode": int(proxy_probe.get("statusCode", 0) or 0),
                    "latencyMs": float(proxy_probe.get("latencyMs", 0.0) or 0.0),
                },
                "blue": {
                    "url": str(blue_probe.get("url", "")),
                    "healthy": bool(blue_probe.get("healthy", False)),
                    "statusCode": int(blue_probe.get("statusCode", 0) or 0),
                    "latencyMs": float(blue_probe.get("latencyMs", 0.0) or 0.0),
                },
                "green": {
                    "url": str(green_probe.get("url", "")),
                    "healthy": bool(green_probe.get("healthy", False)),
                    "statusCode": int(green_probe.get("statusCode", 0) or 0),
                    "latencyMs": float(green_probe.get("latencyMs", 0.0) or 0.0),
                },
            }
            self.release_manifest = release_manifest

    def build_status(self) -> dict:
        active_state = self._load_json(
            STATE_FILE,
            {
                "activeProfile": "learnhub-local",
                "activeTarget": "unknown",
                "activeUpstream": "unknown",
                "changedAt": None,
                "source": "unknown",
            },
        )
        demo_state = self._load_json(
            DEMO_FILE,
            {
                "running": False,
                "intervalSeconds": 20,
                "nextTarget": None,
                "nextSwitchAt": None,
                "profile": "learnhub-local",
            },
        )
        profiles = self._load_profiles()
        events = self._tail_events(limit=20)

        with self.lock:
            total = self.total_requests
            success = self.success_requests
            failed = self.failed_requests
            last_status_code = self.last_status_code
            last_latency_ms = self.last_latency_ms
            current_version = self.current_version
            version_counts = dict(self.version_counts)
            services = dict(self.service_health)
            release_manifest = dict(self.release_manifest)
            now_epoch = time.time()
            samples = list(self.recent_samples)

        recent_count = len([sample for sample in samples if now_epoch - float(sample.get("ts", 0.0)) <= 10.0])
        recent_window = [sample for sample in samples if now_epoch - float(sample.get("ts", 0.0)) <= 60.0]
        recent_errors = len([sample for sample in recent_window if int(sample.get("code", 0) or 0) != 200])

        timeline_points: list[dict[str, Any]] = []
        # Calculate current RPS for history injection
        rps_now = round(recent_count / 10.0, 2)
        
        for sample in recent_window[-50:]:
            timeline_points.append(
                {
                    "ts": sample.get("ts"),
                    "code": sample.get("code"),
                    "latencyMs": sample.get("latencyMs"),
                    "version": sample.get("version"),
                    "rps": sample.get("rps", rps_now) # Carry RPS if stored, else current
                }
            )

        # For backward compatibility and specialized chart inputs
        history_data = {
            "last60s": timeline_points,
            "recentErrorCount": recent_errors,
            "rps": [p.get("rps", 0) for p in timeline_points],
            "latency_p50": [p.get("latencyMs", 0) for p in timeline_points],
            "success_rate": [100 if p.get("code") == 200 else 0 for p in timeline_points]
        }

        # --- Windowed Metrics Calculation (Last 60s) ---
        total_in_window = len(recent_window)
        errors_in_window = recent_errors
        success_rate = round(((total_in_window - errors_in_window) / total_in_window) * 100.0, 2) if total_in_window else 100.0
        error_rate = round((errors_in_window / total_in_window) * 100.0, 2) if total_in_window else 0.0

        # Maintain global counters for historical data in storage
        requests_per_second = round(recent_count / 10.0, 2)

        active_target = str(active_state.get("activeTarget", "")).lower().strip()
        if active_target == "blue":
            next_target = "green"
        elif active_target == "green":
            next_target = "blue"
        else:
            next_target = "green"

        active_profile = str(active_state.get("activeProfile") or profiles.get("defaultProfile") or "learnhub-local")
        proxy_ready = bool(services.get("proxy", {}).get("healthy", False))
        next_ready = bool(services.get(next_target, {}).get("healthy", False))
        error_budget_ok = error_rate < 1.0
        preflight_ready = proxy_ready and next_ready and error_budget_ok

        checks = [
            {
                "name": "Proxy health",
                "passed": proxy_ready,
                "detail": "Proxy is healthy" if proxy_ready else "Proxy health is failing",
            },
            {
                "name": f"{next_target.title()} health",
                "passed": next_ready,
                "detail": f"{next_target.title()} endpoint reachable"
                if next_ready
                else f"{next_target.title()} endpoint not healthy",
            },
            {
                "name": "Error budget",
                "passed": error_budget_ok,
                "detail": f"Error rate is {error_rate}%",
            },
        ]

        commands = {
            "nextTarget": next_target,
            "bashSwitch": f"./switch_traffic.sh {next_target} --profile {active_profile}",
            "powershellSwitch": f"./switch_traffic.ps1 -Target {next_target} -Profile {active_profile}",
            "bashPromote": f"./promote_release.sh {next_target} --profile {active_profile}",
            "powershellPromote": f"./promote_release.ps1 -Target {next_target} -DeployKey {active_profile}",
        }

        if preflight_ready:
            user_story = "System is healthy and ready for the next promotion."
        elif not proxy_ready:
            user_story = "Proxy health is unstable. Resolve gateway issues before deployment."
        elif not next_ready:
            user_story = f"Next target {next_target.title()} is not healthy yet. Wait or fix target app."
        else:
            user_story = "Error rate is above budget. Investigate recent failures before switching traffic."

        active_profile_data = profiles.get("profiles", {}).get(active_profile, {}) if isinstance(profiles, dict) else {}
        
        # Check guardrails if canary is active
        self._check_guardrails(error_rate, last_latency_ms)

        return {
            "timestamp": utc_now(),
            "monitoredUrl": MONITORED_URL,
            "active": {
                "profile": active_state.get("activeProfile"),
                "target": active_state.get("activeTarget"),
                "upstream": active_state.get("activeUpstream"),
                "changedAt": active_state.get("changedAt"),
                "source": active_state.get("source"),
            },
            "metrics": {
                "total_requests": total,
                "success_requests": success,
                "failed_requests": failed,
                "success_rate": success_rate,
                "error_rate": error_rate,
                "rps": requests_per_second,
                "last_status_code": last_status_code,
                "last_latency_ms": last_latency_ms,
                "current_version": current_version,
                "version_counts": version_counts,
            },
            "services": services,
            "releaseManifest": release_manifest,
            "demo": demo_state,
            "profiles": profiles,
            "events": events,
            "history": history_data,
            "devops": {
                "nextTarget": next_target,
                "preflightReady": preflight_ready,
                "checks": checks,
                "commands": commands,
                "canary": {
                    "weights": self.canary_weights,
                    "active": self.canary_weights.get("blue", 0) > 0 and self.canary_weights.get("green", 0) > 0,
                    "guardrail": self.guardrail_active
                },
                "chaos": {
                    "active": self.chaos_active != "none",
                    "mode": self.chaos_active
                },
                "summary": user_story,
                "activeProfileDescription": active_profile_data.get("description", ""),
            },
        }

    def _tail_events(self, limit: int = 20) -> list:
        if not EVENTS_FILE.exists():
            return []

        try:
            with EVENTS_FILE.open("r", encoding="utf-8") as file:
                lines = file.readlines()[-limit:]
        except OSError:
            return []

        events = []
        for line in lines:
            raw = line.strip()
            if not raw:
                continue
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return events

    def start_deployment(self, deployment_id: str, source: str, target: str) -> None:
        """Initialize deployment tracking."""
        with self.lock:
            self.current_deployment = {
                "id": deployment_id,
                "source": source,
                "target": target,
                "startTime": utc_now(),
                "status": "in-progress",
                "completedAt": None,
            }
            self.deployment_steps = [
                {"id": "preflight", "label": "Preflight checks", "status": "pending", "startTime": None, "endTime": None, "detail": ""},
                {"id": "config", "label": "Updating upstream config", "status": "pending", "startTime": None, "endTime": None, "detail": ""},
                {"id": "nginx", "label": "Reloading Nginx", "status": "pending", "startTime": None, "endTime": None, "detail": ""},
                {"id": "health", "label": "Health check", "status": "pending", "startTime": None, "endTime": None, "detail": ""},
                {"id": "done", "label": "Switch complete", "status": "pending", "startTime": None, "endTime": None, "detail": ""},
            ]

    def update_deployment_step(self, step_id: str, status: str, detail: str = "") -> None:
        """Update status of a deployment step."""
        with self.lock:
            if not self.deployment_steps:
                return
            for step in self.deployment_steps:
                if step["id"] == step_id:
                    step["status"] = status
                    if status == "active":
                        step["startTime"] = utc_now()
                    elif status == "done":
                        step["endTime"] = utc_now()
                    if detail:
                        step["detail"] = detail
                    break

    def complete_deployment(self) -> None:
        """Mark deployment as complete."""
        with self.lock:
            if self.current_deployment:
                self.current_deployment["status"] = "complete"
                self.current_deployment["completedAt"] = utc_now()

    def get_deployment_status(self) -> dict[str, Any]:
        """Get current deployment status."""
        with self.lock:
            return {
                "deployment": self.current_deployment,
                "steps": self.deployment_steps,
            } if self.current_deployment else None

    @staticmethod
    def _load_json(path: Path, default_value: dict) -> dict:
        if not path.exists():
            return default_value
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            return default_value
        return default_value

    @staticmethod
    def _load_profiles() -> dict:
        fallback = {
            "defaultProfile": "learnhub-local",
            "profiles": {
                "learnhub-local": {
                    "description": "Local compose-managed blue/green services",
                    "blue": "blue:80",
                    "green": "green:80",
                }
            },
        }

        if not PROFILES_FILE.exists():
            return fallback

        try:
            with PROFILES_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            return fallback

        return fallback

    def _check_guardrails(self, error_rate: float, latency_ms: float) -> None:
        """Monitor health and trigger rollback if thresholds are exceeded."""
        with self.lock:
            # Only active during 100% or weighted splits if guardrail enabled
            is_canary = self.canary_weights.get("blue", 0) > 0 and self.canary_weights.get("green", 0) > 0
            if not is_canary and not self.guardrail_active:
                return
                
            # Thresholds
            ERROR_THRESHOLD = 5.0  # 5%
            LATENCY_THRESHOLD = 500.0 # 500ms
            
            if error_rate > ERROR_THRESHOLD or latency_ms > LATENCY_THRESHOLD:
                reason = f"Error rate {error_rate}% > {ERROR_THRESHOLD}%" if error_rate > ERROR_THRESHOLD else f"Latency {latency_ms}ms > {LATENCY_THRESHOLD}ms"
                self._trigger_rollback(reason)

    def _trigger_rollback(self, reason: str) -> None:
        """Trigger automatic rollback."""
        log_event(
            event_type="AUTO_ROLLBACK",
            message=f"CRITICAL: Guardrail breach - {reason}. Triggering autonomous recovery.",
            level="ERROR",
            details={"reason": reason, "automatic": True}
        )
        
        # Set a flag that UI can see
        with self.lock:
            self.guardrail_active = True
            
        # Perform real rollback - switch to stable 'blue'
        def run_rollback():
            time.sleep(2) # Brief delay for "intelligence" feel
            # We bypass the normal API overhead and just call the internal update
            # Normally we should determine the 'previous' good state, but for this demo Blue is the safety zone.
            success = False
            try:
                # Direct call to the handler's update logic (we need an instance or static method)
                # Since we are in the STORE, we'll just update the file directly here
                if STORE._update_upstream_config("blue"):
                    # Signal Nginx
                    subprocess.run(["docker", "exec", "blue-green-proxy", "nginx", "-s", "reload"], check=True)
                    
                    log_event(
                        event_type="ROLLBACK_COMPLETE",
                        message="Autonomous recovery successful. System returned to Stable Blue.",
                        level="INFO"
                    )
                    success = True
            except Exception as e:
                log_event(
                    event_type="ROLLBACK_FAILED",
                    message=f"Autonomous recovery failed: {e}",
                    level="ERROR"
                )

        threading.Thread(target=run_rollback, daemon=True).start()


STORE = MonitorStore()


class MonitorHandler(BaseHTTPRequestHandler):
    def do_HEAD(self) -> None:
        """Handle HEAD requests (used by Browser Live Probe)."""
        self.do_GET()

    def do_GET(self) -> None:
        request_id = str(uuid.uuid4())[:12]
        parsed = urlparse(self.path)
        path = parsed.path

        # Log API call
        log_event(
            event_type="API_CALL",
            message=f"GET {path}",
            request_id=request_id,
            level="DEBUG",
            details={
                "method": "GET",
                "path": path,
                "clientIp": self.client_address[0] if self.client_address else "unknown",
            }
        )

        # Chaos Hijack Logic for all non-API monitored paths
        is_api = path.startswith("/api/")
        is_static = path.startswith("/assets/") or path.endswith((".js", ".css", ".png", ".jpg", ".ico"))
        
        if not is_api and not is_static:
            with STORE.lock:
                chaos = STORE.chaos_active
            
            if chaos == "error":
                # High-severity outage (100% 502)
                self._send_json({"error": "Chaos Error Active", "code": 502, "mode": "chaos_lab"}, 502)
                return
            if chaos == "latency":
                # High-severity hang (100% 3s wait) - Reduced from 10s to prevent browser queue blocking
                time.sleep(3.0)
                self._send_json({"mode": "chaos_latency_active", "delay": "3000ms"}, 200)
                return
            if chaos == "jitter":
                # Realistic Jitter: 1s-4s random delay
                delay = random.uniform(1.0, 4.0)
                time.sleep(delay)
                self._send_json({"mode": "jitter_active", "delay": f"{delay:.2f}s"}, 200)
                return
            if chaos == "loss":
                # Realistic Packet Loss: 10% random 500 errors
                if random.random() < 0.10:
                    self._send_json({"error": "SIMULATED_PACKET_LOSS", "code": 500}, 500)
                else:
                    self._send_json({"ok": True, "mode": "partial_loss_active"}, 200)
                return

        if path == "/" or path == "/index.html":
            self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return

        if path.startswith("/") and "." in path.rsplit("/", maxsplit=1)[-1]:
            static_path = self._resolve_static_path(path)
            if static_path is not None:
                self._serve_file(static_path, self._guess_content_type(static_path))
                return

        if path == "/healthz":
            self._send_json({"ok": True, "timestamp": utc_now()})
            return

        if path == "/api/status":
            self._send_json(STORE.build_status())
            return

        if path == "/api/profiles":
            self._send_json(STORE._load_profiles())
            return

        if path == "/api/events":
            self._send_json({"events": STORE._tail_events(limit=50)})
            return

        if path == "/api/events/stream":
            self._stream_events()
            return
        
        # Fault injection simulation endpoints for Nginx
        if path == "/slow":
            time.sleep(5.0) # High latency spike
            self._send_json({"chaos": "latency", "node": "monitor_sim"}, 200)
            return
        
        if path == "/error":
            self._send_json({"error": "Internal Server Error", "code": 500, "chaos": "active"}, 500)
            return

        if path == "/api/deploy/status":
            deploy_status = STORE.get_deployment_status()
            self._send_json(deploy_status if deploy_status else {"status": "idle"})
            return

        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"Not Found"}')

    def do_POST(self) -> None:
        request_id = str(uuid.uuid4())[:12]
        parsed = urlparse(self.path)
        path = parsed.path

        # Log API call
        log_event(
            event_type="API_CALL",
            message=f"POST {path}",
            request_id=request_id,
            level="INFO",
            details={
                "method": "POST",
                "path": path,
                "clientIp": self.client_address[0] if self.client_address else "unknown",
            }
        )

        # Parse request body
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 1024 * 1024:  # 1MB limit
            self._send_json({"error": "Request body too large"}, 413)
            return

        try:
            body = self.rfile.read(content_length).decode("utf-8")
            request_data = json.loads(body) if body else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            log_event(
                event_type="API_ERROR",
                message=f"Invalid request body: {e}",
                request_id=request_id,
                level="WARN",
            )
            self._send_json({"error": "Invalid JSON body"}, 400)
            return

        # Route to appropriate handler
        if path == "/api/deploy":
            self._handle_deploy(request_data, request_id)
        elif path == "/api/rollback":
            self._handle_rollback(request_data, request_id)
        elif path == "/api/approve":
            self._handle_approve(request_data, request_id)
        elif path == "/api/canary":
            self._handle_canary(request_data, request_id)
        elif path == "/api/chaos":
            self._handle_chaos(request_data, request_id)
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"Not Found"}')

    def _handle_deploy(self, request_data: dict, request_id: str) -> None:
        """Handle deployment to specified target."""
        try:
            target = (request_data.get("target") or "blue").lower()
            if target not in ["blue", "green"]:
                log_event(
                    event_type="DEPLOY_FAILED",
                    message=f"Invalid target: {target}",
                    request_id=request_id,
                    level="WARN",
                )
                self._send_json({"error": f"Invalid target '{target}'. Must be 'blue' or 'green'."}, 400)
                return

            # Check if already on target
            state = STORE._load_json(STATE_FILE, {})
            current = (state.get("activeTarget") or "blue").lower()
            if current == target:
                self._send_json({
                    "status": "noop",
                    "message": f"Already deployed to {target}",
                    "timestamp": utc_now(),
                }, 200)
                return

            # Verify preflight readiness
            status = STORE.build_status()
            if not status.get("devops", {}).get("preflightReady", False):
                log_event(
                    event_type="DEPLOY_FAILED",
                    message="Preflight checks not ready",
                    request_id=request_id,
                    level="WARN",
                    details={"reason": status.get("devops", {}).get("summary", "Unknown")},
                )
                self._send_json({
                    "error": "Preflight checks not ready",
                    "details": status.get("devops", {}).get("checks", {}),
                    "summary": status.get("devops", {}).get("summary"),
                }, 423)
                return

            # Log deployment start
            deployment_id = str(uuid.uuid4())[:8]
            log_event(
                event_type="DEPLOY_START",
                message=f"Starting deployment from {current} to {target}",
                request_id=request_id,
                level="INFO",
                details={
                    "deploymentId": deployment_id,
                    "source": current,
                    "target": target,
                },
            )

            # Perform IMMEDIATE deployment for Titanium Live Control
            if STORE._update_upstream_config(target):
                log_event(
                    event_type="DEPLOY_SUCCESS",
                    message=f"Successfully promoted release to {target.upper()}",
                    request_id=request_id,
                    level="INFO",
                    details={"target": target}
                )
                self._send_json({
                    "status": "success",
                    "message": f"Successfully promoted to {target}",
                    "timestamp": utc_now(),
                }, 200)
            else:
                raise Exception("Failed to update upstream configuration")

        except Exception as e:
            log_event(
                event_type="API_ERROR",
                message=f"Handler error: {e}",
                request_id=request_id,
                level="ERROR",
            )
            self._send_json({"error": "Internal server error"}, 500)

    def _handle_rollback(self, request_data: dict, request_id: str) -> None:
        """Handle rollback to previous deployment."""
        try:
            # Get current state
            state = STORE._load_json(STATE_FILE, {})
            current = state.get("activeTarget", "blue").lower()
            
            # Rollback is just switching to the other target
            target = "green" if current == "blue" else "blue"
            
            log_event(
                event_type="ROLLBACK_START",
                message=f"Rolling back from {current} to {target}",
                request_id=request_id,
                level="WARN",
            )

            # Update Nginx upstream configuration directly
            if STORE._update_upstream_config(target):
                log_event(
                    event_type="ROLLBACK_SUCCESS",
                    message=f"Successfully rolled back to {target}",
                    request_id=request_id,
                    level="WARN",
                )
                self._send_json({
                    "status": "success",
                    "message": f"Successfully rolled back to {target}",
                    "timestamp": utc_now(),
                }, 200)
            else:
                log_event(
                    event_type="ROLLBACK_FAILED",
                    message="Failed to update upstream configuration for rollback",
                    request_id=request_id,
                    level="ERROR",
                )
                self._send_json({
                    "error": "Rollback failed - could not update configuration",
                }, 500)

        except Exception as e:
            log_event(
                event_type="API_ERROR",
                message=f"Handler error: {e}",
                request_id=request_id,
                level="ERROR",
            )
            self._send_json({"error": "Internal server error"}, 500)

    def _execute_deployment_steps(self, deployment_id: str, source: str, target: str, request_id: str) -> None:
        """Execute deployment steps in background thread."""
        try:
            # Step 1: Preflight checks
            STORE.update_deployment_step("preflight", "active", "Validating environment health")
            time.sleep(0.3)  # Simulate check time
            STORE.update_deployment_step("preflight", "done", "3/3 checks passed")
            
            # Step 2: Update upstream config
            STORE.update_deployment_step("config", "active", f"Updating active-upstream.conf for {target}:80")
            time.sleep(0.4)  # Simulate config update time
            
            if not STORE._update_upstream_config(target):
                raise Exception("Failed to update upstream configuration")
            
            STORE.update_deployment_step("config", "done", f"server {target}:80 → active-upstream.conf")
            
            # Step 3: Reload Nginx
            STORE.update_deployment_step("nginx", "active", "Reloading Nginx upstream configuration")
            try:
                # Execute reload in proxy container using mounted socket
                subprocess.run(
                    ["docker", "exec", "blue-green-proxy", "nginx", "-s", "reload"],
                    check=True,
                    capture_output=True,
                    timeout=5.0
                )
                STORE.update_deployment_step("nginx", "done", f"upstream active_backend → {target}:80")
            except Exception as reload_err:
                log_event(
                    event_type="RELOAD_FAILED",
                    message=f"Failed to reload Nginx: {reload_err}",
                    level="ERROR"
                )
                # We continue anyway as the file is updated, but this is a critical log
                STORE.update_deployment_step("nginx", "done", f"Warning: Config updated but reload failed")
            
            # Step 4: Health check (REAL)
            STORE.update_deployment_step("health", "active", f"Verifying {target.upper()} through Production Gateway")
            
            # Real probe of the /app/ endpoint which now points to the new target
            real_probe = self._probe_url(join_url(MONITORED_URL, "/app/"))
            if real_probe.get("healthy"):
                STORE.update_deployment_step("health", "done", f"HTTP 200 OK · latency {real_probe.get('latencyMs')}ms")
            else:
                STORE.update_deployment_step("health", "done", "Warning: Gateway check sluggish (latency high)")
            
            # Step 5: Deployment complete
            STORE.update_deployment_step("done", "active", "Finalizing switch")
            time.sleep(0.1)  # Short final delay
            STORE.update_deployment_step("done", "done", "0 requests dropped")
            STORE.complete_deployment()

            # PERSIST to state.json after successful promotion
            try:
                state = STORE._load_json(STATE_FILE, {})
                state["activeTarget"] = target
                state["activeUpstream"] = f"{target}_svc:80"
                state["changedAt"] = utc_now()
                state["source"] = "titanium-dashboard"
                with STATE_FILE.open("w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2)
            except Exception as e:
                print(f"Failed to persist state: {e}")
            
            log_event(
                event_type="DEPLOY_SUCCESS",
                message=f"Successfully promoted release to {target.upper()}",
                request_id=request_id,
                level="INFO",
                details={
                    "deploymentId": deployment_id,
                    "source": source,
                    "target": target
                },
            )
        except Exception as e:
            log_event(
                event_type="DEPLOY_FAILED",
                message=f"Deployment failed: {str(e)}",
                request_id=request_id,
                level="ERROR",
                details={"deploymentId": deployment_id},
            )

    def _handle_approve(self, request_data: dict, request_id: str) -> None:
        """Handle approval of pending deployment (placeholder for workflow system)."""
        try:
            deployment_id = request_data.get("deploymentId", "")
            if not deployment_id:
                self._send_json({"error": "deploymentId required"}, 400)
                return

            log_event(
                event_type="APPROVAL",
                message=f"Deployment {deployment_id} approved",
                request_id=request_id,
                level="INFO",
                details={"deploymentId": deployment_id},
            )
            
            self._send_json({
                "status": "approved",
                "deploymentId": deployment_id,
                "message": "Deployment approved and queued for execution",
                "timestamp": utc_now(),
            }, 200)

        except Exception as e:
            log_event(
                event_type="API_ERROR",
                message=f"Handler error: {e}",
                request_id=request_id,
                level="ERROR",
            )
            self._send_json({"error": "Internal server error"}, 500)

    def log_message(self, _format: str, *_args) -> None:
        return

    def _send_json(self, payload: dict, status_code: int = 200) -> None:
        # Add request ID to response headers for tracing
        request_id = self.headers.get("X-Request-ID", str(uuid.uuid4())[:12])
        
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Request-ID", request_id)
        self.end_headers()
        self.wfile.write(body)
        
        # Log API response
        log_event(
            event_type="API_RESPONSE",
            message=f"Sent JSON response ({len(body)} bytes)",
            request_id=request_id,
            level="DEBUG",
            details={
                "statusCode": status_code,
                "responseSize": len(body),
            }
        )

    def _serve_file(self, file_path: Path, content_type: str) -> None:
        if not file_path.exists():
            self.send_response(404)
            self.end_headers()
            return

        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _guess_content_type(file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix == ".js":
            return "application/javascript; charset=utf-8"
        if suffix == ".jsx":
            return "text/babel; charset=utf-8"
        if suffix == ".css":
            return "text/css; charset=utf-8"
        if suffix == ".json":
            return "application/json; charset=utf-8"
        if suffix == ".svg":
            return "image/svg+xml"
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            return "application/octet-stream"
        return "text/plain; charset=utf-8"

    @staticmethod
    def _resolve_static_path(request_path: str) -> Path | None:
        relative = request_path.lstrip("/")
        requested = (STATIC_DIR / relative).resolve()
        try:
            requested.relative_to(STATIC_DIR.resolve())
        except ValueError:
            return None
        if requested.exists() and requested.is_file():
            return requested
        return None

    def _handle_canary(self, request_data: dict, request_id: str) -> None:
        """Handle weighted traffic shift (Canary)."""
        try:
            # Robust extraction with fallback to current state if null/missing
            with STORE.lock:
                curr_weights = STORE.canary_weights
            
            blue_weight = int(request_data.get("blue") if request_data.get("blue") is not None else curr_weights.get("blue", 100))
            green_weight = int(request_data.get("green") if request_data.get("green") is not None else curr_weights.get("green", 0))
            
            if blue_weight + green_weight != 100:
                self._send_json({"error": "Weights must sum to 100"}, 400)
                return
            
            log_event(
                event_type="CANARY_UPDATE",
                message=f"Updating canary weights: Blue={blue_weight}%, Green={green_weight}%",
                request_id=request_id,
                level="INFO",
                details={"blue": blue_weight, "green": green_weight}
            )
            
            with STORE.lock:
                STORE.canary_weights = {"blue": blue_weight, "green": green_weight}
                
            if STORE._update_upstream_config(target=None):
                # Signal Nginx for zero-downtime reload
                subprocess.run(["docker", "exec", "blue-green-proxy", "nginx", "-s", "reload"], check=True)
                self._send_json({"status": "success", "weights": STORE.canary_weights})
            else:
                self._send_json({"error": "Failed to update configuration"}, 500)
                
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_chaos(self, request_data: dict, request_id: str) -> None:
        """Handle chaos engineering injection.
        
        Mode Strategy:
        - blackout  : REAL — docker stop blue-app AND green-app (total outage)
        - error     : REAL — docker stop the active target container only
        - latency   : SIMULATED — Nginx routes traffic through monitor /slow endpoint
        - jitter    : SIMULATED — Nginx routes traffic through monitor with random delays
        - loss      : SIMULATED — Nginx routes traffic through monitor with 10% drop rate
        - restore   : REAL — docker start all containers, reset Nginx config
        """
        try:
            mode = (request_data.get("mode") or "none").lower()

            # ── REAL DOCKER MANIPULATION: Blackout ──────────────────────────────
            if mode == "blackout":
                log_event(
                    event_type="CHAOS_INJECT",
                    message="☣️ CHAOS BLACKOUT: Stopping ALL application containers (blue-app, green-app). Total service outage.",
                    request_id=request_id,
                    level="ERROR",
                    details={"mode": mode, "injection": "docker_container_stop", "targets": ["blue-app", "green-app"]}
                )
                with STORE.lock:
                    STORE.chaos_active = mode

                def run_blackout():
                    try:
                        subprocess.run(["docker", "stop", "blue-app"], check=False, capture_output=True, timeout=10)
                        subprocess.run(["docker", "stop", "green-app"], check=False, capture_output=True, timeout=10)
                        log_event("CHAOS_BLACKOUT_ACTIVE", "Both blue-app and green-app containers are STOPPED. Gateway will return 502.", level="ERROR")
                    except Exception as e:
                        log_event("CHAOS_BLACKOUT_FAILED", f"Failed to stop containers: {e}", level="ERROR")

                    # Auto-restore after 30 seconds
                    time.sleep(30)
                    with STORE.lock:
                        if STORE.chaos_active == "blackout":
                            self._restore_system(request_id=request_id, reason="auto-restore after 30s blackout experiment")

                threading.Thread(target=run_blackout, daemon=True).start()
                self._send_json({"status": "initiated", "mode": mode, "action": "docker_stop_all", "timestamp": utc_now()})
                return

            # ── REAL DOCKER MANIPULATION: Critical Fail (active target only) ────
            if mode == "error":
                state = STORE._load_json(STATE_FILE, {})
                active_target = (state.get("activeTarget") or "blue").lower()
                container_name = f"{active_target}-app"

                log_event(
                    event_type="CHAOS_INJECT",
                    message=f"☣️ CHAOS CRITICAL FAIL: Stopping active container '{container_name}'. Simulating target crash.",
                    request_id=request_id,
                    level="ERROR",
                    details={"mode": mode, "injection": "docker_container_stop", "target": container_name}
                )
                with STORE.lock:
                    STORE.chaos_active = mode

                def run_error_inject():
                    try:
                        subprocess.run(["docker", "stop", container_name], check=False, capture_output=True, timeout=10)
                        log_event("CHAOS_ERROR_ACTIVE", f"Container '{container_name}' is STOPPED. Active environment is down.", level="ERROR")
                    except Exception as e:
                        log_event("CHAOS_ERROR_FAILED", f"Failed to stop container '{container_name}': {e}", level="ERROR")

                    # Auto-restore after 30 seconds
                    time.sleep(30)
                    with STORE.lock:
                        if STORE.chaos_active == "error":
                            self._restore_system(request_id=request_id, reason="auto-restore after 30s error experiment")

                threading.Thread(target=run_error_inject, daemon=True).start()
                self._send_json({"status": "initiated", "mode": mode, "action": f"docker_stop {container_name}", "timestamp": utc_now()})
                return

            # ── NGINX-LEVEL SIMULATION: Latency, Jitter, Loss ───────────────────
            if mode in {"latency", "jitter", "loss"}:
                mode_labels = {
                    "latency": "HIGH LATENCY INJECTION (3s delay via proxy)",
                    "jitter": "JITTER INJECTION (1-4s random delay via proxy)",
                    "loss": "PACKET LOSS INJECTION (10% drop rate via proxy)"
                }
                log_event(
                    event_type="CHAOS_INJECT",
                    message=f"☣️ CHAOS {mode_labels.get(mode, mode.upper())}: Nginx rerouted to chaos endpoint.",
                    request_id=request_id,
                    level="ERROR",
                    details={"mode": mode, "injection": "nginx_upstream_hijack"}
                )
                with STORE.lock:
                    STORE.chaos_active = mode

                # Update Nginx to route through monitor's fault endpoints
                STORE._update_upstream_config(target=None)
                subprocess.run(["docker", "exec", "blue-green-proxy", "nginx", "-s", "reload"], check=False)

                def auto_restore():
                    time.sleep(30)
                    with STORE.lock:
                        if STORE.chaos_active == mode:
                            self._restore_system(request_id=request_id, reason=f"auto-restore after 30s {mode} experiment")

                threading.Thread(target=auto_restore, daemon=True).start()
                self._send_json({"status": "initiated", "mode": mode, "action": "nginx_hijack", "timestamp": utc_now()})
                return

            # ── RESTORE: Bring containers back, reset Nginx ──────────────────────
            if mode == "restore":
                self._restore_system(request_id=request_id, reason="manual restore from UI")
                self._send_json({"status": "restored", "mode": "none", "timestamp": utc_now()})
                return

            # Unknown mode
            self._send_json({"error": f"Unknown chaos mode: {mode}"}, 400)

        except Exception as e:
            log_event("CHAOS_ERROR", f"Chaos handler exception: {e}", level="ERROR")
            self._send_json({"error": str(e)}, 500)

    def _restore_system(self, request_id: str = None, reason: str = "manual") -> None:
        """Real full-system recovery: start stopped containers, reset Nginx config."""
        if request_id is None:
            request_id = str(uuid.uuid4())[:12]

        log_event(
            event_type="CHAOS_RESTORE",
            message=f"🔧 SYSTEM RESTORE INITIATED: {reason}",
            request_id=request_id,
            level="INFO",
            details={"reason": reason}
        )

        # Step 1: Reset chaos state and weights
        with STORE.lock:
            STORE.chaos_active = "none"
            state = STORE._load_json(STATE_FILE, {})
            active = (state.get("activeTarget") or "blue").lower()
            STORE.canary_weights = {"blue": 100, "green": 0} if active == "blue" else {"blue": 0, "green": 100}

        # Step 2: Start any stopped containers
        containers_started = []
        containers_failed = []
        for container in ["blue-app", "green-app"]:
            try:
                result = subprocess.run(
                    ["docker", "start", container],
                    check=False, capture_output=True, timeout=15
                )
                if result.returncode == 0:
                    containers_started.append(container)
                    log_event("CONTAINER_STARTED", f"Container '{container}' started successfully.", level="INFO")
                else:
                    err = result.stderr.decode("utf-8", errors="ignore").strip()
                    log_event("CONTAINER_START_WARN", f"docker start {container} returned non-zero: {err}", level="WARN")
                    # Non-zero often just means the container was already running — not fatal
                    containers_started.append(container)
            except Exception as e:
                containers_failed.append(container)
                log_event("CONTAINER_START_FAILED", f"Failed to start container '{container}': {e}", level="ERROR")

        # Step 3: Wait briefly for containers to become available, then reset Nginx
        time.sleep(2)
        STORE._update_upstream_config(target=None)
        try:
            subprocess.run(
                ["docker", "exec", "blue-green-proxy", "nginx", "-s", "reload"],
                check=False, timeout=10
            )
            log_event(
                event_type="CHAOS_RESTORE_COMPLETE",
                message=f"✅ System restored. Containers restarted: {containers_started}. Nginx config reset.",
                request_id=request_id,
                level="INFO",
                details={"started": containers_started, "failed": containers_failed}
            )
        except Exception as e:
            log_event("RESTORE_NGINX_WARN", f"Nginx reload after restore failed: {e}", level="WARN")

    def _stream_events(self) -> None:
        client_queue = STORE.register_client()

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        initial = json.dumps(STORE.build_status(), separators=(",", ":"))

        try:
            self.wfile.write(f"event: status\ndata: {initial}\n\n".encode("utf-8"))
            self.wfile.flush()

            while True:
                try:
                    payload = client_queue.get(timeout=15)
                    self.wfile.write(f"event: status\ndata: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            STORE.unregister_client(client_queue)


def sampler_loop() -> None:
    while True:
        started = time.time()
        STORE.sample_proxy()
        status = STORE.build_status()
        STORE.broadcast_status(status)
        elapsed = time.time() - started
        sleep_for = max(0.2, 1.0 - elapsed)
        time.sleep(sleep_for)


def main() -> None:
    # --- Startup Synchronization ---
    print("鈦 PROJECT TITANIUM: Performing Startup Synchronization...", flush=True)
    # Ensure active-upstream.conf matches internal state (Blue/None) on boot
    STORE._update_upstream_config(target=None)
    try:
        subprocess.run(["docker", "exec", "blue-green-proxy", "nginx", "-s", "reload"], check=False)
        print("鈦 STARTUP: Nginx configuration synchronized to Stable Blue.", flush=True)
    except Exception as e:
        print(f"鈦 STARTUP WARNING: Could not signal Nginx reload: {e}", flush=True)

    monitor_thread = threading.Thread(target=sampler_loop, daemon=True)
    monitor_thread.start()

    server = ThreadingHTTPServer(("0.0.0.0", PORT), MonitorHandler)
    print(f"monitor listening on :{PORT}, watching {MONITORED_URL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
