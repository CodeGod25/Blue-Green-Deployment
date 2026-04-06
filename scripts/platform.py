#!/usr/bin/env python3
"""
Platform CLI - Blue-Green Deployment Management Tool
Provides a user-friendly command-line interface for deployment operations.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError
import subprocess
import os

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

# Icons
class Icons:
    SUCCESS = '✓'
    FAILURE = '✗'
    INFO = 'ℹ'
    WARNING = '⚠'
    ARROW = '→'
    SPINNER = '◌'

# Configuration
DEFAULT_MONITOR_URL = "http://localhost:8090"
MONITOR_URL = os.getenv("MONITOR_URL", DEFAULT_MONITOR_URL)


def print_header(text: str) -> None:
    """Print a formatted header."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}╔═══════════════════════════════════════╗{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}║  {text:<35}  ║{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}╚═══════════════════════════════════════╝{Colors.END}\n")


def print_success(msg: str) -> None:
    """Print success message."""
    print(f"{Colors.GREEN}{Icons.SUCCESS}{Colors.END}  {Colors.GREEN}{msg}{Colors.END}")


def print_info(msg: str) -> None:
    """Print info message."""
    print(f"{Colors.BLUE}{Icons.INFO}{Colors.END}  {Colors.BLUE}{msg}{Colors.END}")


def print_warning(msg: str) -> None:
    """Print warning message."""
    print(f"{Colors.YELLOW}{Icons.WARNING}{Colors.END}  {Colors.YELLOW}{msg}{Colors.END}")


def print_error(msg: str) -> None:
    """Print error message."""
    print(f"{Colors.RED}{Icons.FAILURE}{Colors.END}  {Colors.RED}{msg}{Colors.END}")


def api_request(endpoint: str, method: str = "GET", body: Optional[dict] = None) -> Tuple[int, dict]:
    """
    Make an HTTP request to the monitor API.
    
    Returns: (status_code, response_dict)
    """
    url = f"{MONITOR_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    
    req_body = None
    if body:
        req_body = json.dumps(body).encode('utf-8')
    
    try:
        req = Request(url, data=req_body, headers=headers, method=method)
        with urlopen(req) as response:
            data = response.read().decode('utf-8')
            return response.status, json.loads(data)
    except URLError as e:
        if hasattr(e, 'code'):
            try:
                data = e.read().decode('utf-8')
                return e.code, json.loads(data)
            except:
                return e.code, {"error": str(e)}
        return 0, {"error": f"Connection failed: {e.reason}"}
    except json.JSONDecodeError:
        return 0, {"error": "Invalid JSON response"}
    except Exception as e:
        return 0, {"error": str(e)}


def get_status() -> Optional[dict]:
    """Get current system status."""
    status_code, response = api_request("/api/status")
    if status_code == 200:
        return response
    return None


def confirm(prompt: str, default: bool = False) -> bool:
    """Get user confirmation."""
    default_str = "[Y/n]" if default else "[y/N]"
    response = input(f"{prompt} {default_str}: ").lower().strip()
    
    if not response:
        return default
    return response in ('y', 'yes')


def deploy(target: str, skip_confirm: bool = False) -> bool:
    """Execute deployment to target."""
    if target not in ["blue", "green"]:
        print_error(f"Invalid target: {target}. Must be 'blue' or 'green'.")
        return False
    
    # Check system status first
    print_info("Checking system status...")
    status = get_status()
    if not status:
        print_error("Failed to connect to monitor service")
        return False
    
    current = status.get("active", {}).get("target", "unknown").lower()
    preflight = status.get("devops", {}).get("preflightReady", False)
    summary = status.get("devops", {}).get("summary", "No info")
    
    print_info(f"Current target: {Colors.BOLD}{current}{Colors.END}")
    print_info(f"Target deployment: {Colors.BOLD}{target}{Colors.END}")
    print_info(f"Preflight status: {'Ready' if preflight else 'Not Ready'}")
    
    if not preflight:
        print_warning(f"Preflight checks not passed: {summary}")
        if not skip_confirm and not confirm("Continue anyway?", False):
            print_warning("Deployment cancelled")
            return False
    
    if current.lower() == target.lower():
        print_info(f"Already deployed to {target}")
        return True
    
    if not skip_confirm:
        if not confirm(f"Deploy to {Colors.BOLD}{target}{Colors.END}?", False):
            print_warning("Deployment cancelled")
            return False
    
    # Execute deployment
    print_info("Deploying...")
    status_code, response = api_request("/api/deploy", "POST", {"target": target})
    
    if status_code == 200:
        deployment_id = response.get("deploymentId", "unknown")
        print_success(f"Deployment successful (ID: {Colors.BOLD}{deployment_id}{Colors.END})")
        print_info(f"Message: {response.get('message', 'N/A')}")
        return True
    else:
        error = response.get("error", "Unknown error")
        print_error(f"Deployment failed: {error}")
        if "details" in response:
            print_error(f"Details: {response['details']}")
        return False


def rollback(skip_confirm: bool = False) -> bool:
    """Perform rollback to previous deployment."""
    status = get_status()
    if not status:
        print_error("Failed to connect to monitor service")
        return False
    
    current = status.get("active", {}).get("target", "unknown").lower()
    previous = "green" if current == "blue" else "blue"
    
    print_warning(f"Rolling back from {Colors.BOLD}{current}{Colors.END} to {Colors.BOLD}{previous}{Colors.END}")
    
    if not skip_confirm:
        if not confirm("Proceed with rollback?", False):
            print_warning("Rollback cancelled")
            return False
    
    status_code, response = api_request("/api/rollback", "POST", {})
    
    if status_code == 200:
        print_success(f"Rollback successful")
        print_info(f"Message: {response.get('message', 'N/A')}")
        return True
    else:
        error = response.get("error", "Unknown error")
        print_error(f"Rollback failed: {error}")
        return False


def show_status(watch: bool = False, interval: int = 5) -> None:
    """Display current deployment status."""
    if watch:
        try:
            while True:
                os.system('clear' if os.name == 'posix' else 'cls')
                _display_status_once()
                print(f"\n{Colors.BLUE}Refreshing every {interval}s (Ctrl+C to stop){Colors.END}")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nMonitoring stopped")
    else:
        _display_status_once()


def _display_status_once() -> None:
    """Display status information once."""
    print_header("Deployment Status")
    
    status = get_status()
    if not status:
        print_error("Failed to connect to monitor service")
        return
    
    # Active deployment
    active = status.get("active", {})
    print(f"{Colors.BOLD}Active Deployment:{Colors.END}")
    print(f"  Target: {Colors.CYAN}{active.get('target', 'N/A')}{Colors.END}")
    print(f"  Profile: {Colors.CYAN}{active.get('profile', 'N/A')}{Colors.END}")
    print(f"  Changed: {Colors.CYAN}{active.get('changedAt', 'N/A')}{Colors.END}")
    print()
    
    # Metrics
    metrics = status.get("metrics", {})
    print(f"{Colors.BOLD}Metrics:{Colors.END}")
    success_rate = metrics.get("successRate", 0) * 100
    error_rate = metrics.get("errorRate", 0) * 100
    status_color = Colors.GREEN if success_rate >= 95 else Colors.YELLOW if success_rate >= 80 else Colors.RED
    print(f"  Success Rate: {status_color}{success_rate:.1f}%{Colors.END}")
    print(f"  Error Rate: {Colors.RED if error_rate > 5 else Colors.GREEN}{error_rate:.1f}%{Colors.END}")
    print(f"  RPS: {Colors.CYAN}{metrics.get('rps', 0):.1f} req/s{Colors.END}")
    print(f"  Total Requests: {Colors.CYAN}{metrics.get('totalRequests', 0)}{Colors.END}")
    print()
    
    # Preflight
    devops = status.get("devops", {})
    preflight = devops.get("preflightReady", False)
    print(f"{Colors.BOLD}Preflight Checks:{Colors.END}")
    status_icon = f"{Colors.GREEN}{Icons.SUCCESS}{Colors.END}" if preflight else f"{Colors.RED}{Icons.FAILURE}{Colors.END}"
    print(f"  Ready: {status_icon}  {devops.get('summary', 'N/A')}")
    print()
    
    # Services
    services = status.get("services", {})
    print(f"{Colors.BOLD}Services:{Colors.END}")
    for service, service_status in services.items():
        healthy = service_status.get("healthy", False)
        icon = f"{Colors.GREEN}{Icons.SUCCESS}{Colors.END}" if healthy else f"{Colors.RED}{Icons.FAILURE}{Colors.END}"
        print(f"  {service}: {icon}  (latency: {service_status.get('latency_ms', 'N/A')}ms)")


def show_history(limit: int = 20) -> None:
    """Display deployment history."""
    print_header("Deployment History")
    
    try:
        events_file = Path("/workspace/runtime/events.jsonl")
        if not events_file.exists():
            print_warning("No deployment history found")
            return
        
        deployments = []
        with open(events_file, 'r') as f:
            for line in f:
                try:
                    event = json.loads(line)
                    if event.get("eventType", "").startswith("DEPLOY"):
                        deployments.append(event)
                except:
                    pass
        
        if not deployments:
            print_warning("No deployments found in history")
            return
        
        # Show last N deployments
        for event in sorted(deployments, key=lambda e: e.get("timestamp", ""), reverse=True)[:limit]:
            event_type = event.get("eventType", "UNKNOWN")
            msg = event.get("message", "")
            timestamp = event.get("timestamp", "")
            details = event.get("details", {})
            
            type_color = Colors.GREEN if "SUCCESS" in event_type else Colors.RED if "FAILED" in event_type else Colors.YELLOW
            
            print(f"{type_color}●{Colors.END} {timestamp}")
            print(f"  Event: {Colors.BOLD}{event_type}{Colors.END}")
            print(f"  Message: {msg}")
            if details.get("deploymentId"):
                print(f"  Deployment ID: {Colors.CYAN}{details['deploymentId']}{Colors.END}")
            if details.get("target"):
                print(f"  Target: {Colors.CYAN}{details['target']}{Colors.END}")
            print()
    except Exception as e:
        print_error(f"Failed to read history: {e}")


def show_profiles() -> None:
    """Display available deployment profiles."""
    print_header("Deployment Profiles")
    
    status_code, response = api_request("/api/profiles")
    if status_code != 200:
        print_error("Failed to fetch profiles")
        return
    
    default = response.get("defaultProfile", "N/A")
    profiles = response.get("profiles", {})
    
    print(f"Default Profile: {Colors.BOLD}{default}{Colors.END}\n")
    
    for name, profile in profiles.items():
        marker = " (default)" if name == default else ""
        print(f"{Colors.CYAN}{name}{Colors.END}{marker}")
        print(f"  Description: {profile.get('description', 'N/A')}")
        print(f"  Blue: {Colors.BLUE}{profile.get('blue', 'N/A')}{Colors.END}")
        print(f"  Green: {Colors.GREEN}{profile.get('green', 'N/A')}{Colors.END}")
        print()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Platform CLI - Blue-Green Deployment Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  platform deploy green              # Deploy to green environment
  platform rollback                  # Rollback to previous environment
  platform status                    # Show current deployment status
  platform status --watch            # Monitor status in real-time
  platform history                   # Show deployment history
  platform profiles                  # List available profiles
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Deploy command
    deploy_parser = subparsers.add_parser("deploy", help="Deploy to target environment")
    deploy_parser.add_argument("target", choices=["blue", "green"], help="Target environment")
    deploy_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts")
    
    # Rollback command
    rollback_parser = subparsers.add_parser("rollback", help="Rollback to previous environment")
    rollback_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Show deployment status")
    status_parser.add_argument("-w", "--watch", action="store_true", help="Watch status in real-time")
    status_parser.add_argument("-i", "--interval", type=int, default=5, help="Refresh interval in seconds")
    
    # History command
    history_parser = subparsers.add_parser("history", help="Show deployment history")
    history_parser.add_argument("-n", "--limit", type=int, default=20, help="Number of records to show")
    
    # Profiles command
    profiles_parser = subparsers.add_parser("profiles", help="List deployment profiles")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    try:
        if args.command == "deploy":
            success = deploy(args.target, skip_confirm=args.yes)
            return 0 if success else 1
        elif args.command == "rollback":
            success = rollback(skip_confirm=args.yes)
            return 0 if success else 1
        elif args.command == "status":
            show_status(watch=args.watch, interval=args.interval)
            return 0
        elif args.command == "history":
            show_history(limit=args.limit)
            return 0
        elif args.command == "profiles":
            show_profiles()
            return 0
    except KeyboardInterrupt:
        print("\nOperation cancelled")
        return 1
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
