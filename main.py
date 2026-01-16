#!/usr/bin/env python3
"""
Replica Communication Demo for DigitalOcean App Platform

This application demonstrates how multiple replicas of a service can discover
and communicate with each other on App Platform, even without Kubernetes
StatefulSet-style DNS naming.

Key Features:
- Shows current replica hostname and IP
- Discovers peer replicas via subnet scanning
- Displays cluster status in a nice UI
- Auto-refreshes every 5 seconds

Environment Variables:
- SERVICE_NAME: Name of the service (default: main-service)
- REPLICA_COUNT: Expected number of replicas (default: 3)
- PORT: HTTP port to listen on (default: 8080)
"""

import os
import socket
import time
import json
import concurrent.futures
from datetime import datetime
from urllib.request import urlopen
from urllib.error import URLError

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="Replica Communication Demo",
    description="Demonstrates inter-replica communication on App Platform",
    version="1.0.0"
)

# Configuration from environment
SERVICE_NAME = os.environ.get("SERVICE_NAME", "main-service")
REPLICA_COUNT = int(os.environ.get("REPLICA_COUNT", "3"))
PORT = int(os.environ.get("PORT", "8080"))
HOSTNAME = socket.gethostname()
MY_IP = socket.gethostbyname(HOSTNAME)


def get_timestamp():
    """Return current timestamp in readable format."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def discover_peers(port=8080, timeout=0.1):
    """
    Discover peer replicas by scanning the pod network subnet.

    This works because all pods in the same App Platform app share
    a network where they can communicate via private IPs.
    """
    parts = MY_IP.split(".")
    base = ".".join(parts[:2])  # e.g., "10.244"
    my_third = int(parts[2])

    def check_ip(ip):
        """Check if an IP has our service port open."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            sock.close()
            return ip if result == 0 else None
        except:
            return None

    # Scan wider range of /24 subnets (pods may be spread across nodes)
    # App Platform pods can be on very different subnets (e.g., 0, 6, 33)
    ips_to_scan = [
        f"{base}.{third}.{fourth}"
        for third in range(0, 50)  # Scan first 50 subnets
        for fourth in range(1, 255)
    ]

    # Parallel scanning for speed
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        results = list(executor.map(check_ip, ips_to_scan))
        return sorted(set(ip for ip in results if ip))


def get_peer_identity(ip, port=8080, timeout=1.0):
    """
    Get the identity (hostname) of a peer by calling its /identity endpoint.
    Returns dict with ip, hostname, service or None if unreachable.
    """
    try:
        url = f"http://{ip}:{port}/identity"
        with urlopen(url, timeout=timeout) as response:
            data = json.loads(response.read().decode())
            return {
                "ip": ip,
                "hostname": data.get("hostname", "unknown"),
                "service": data.get("service", "unknown")
            }
    except (URLError, json.JSONDecodeError, Exception):
        return {"ip": ip, "hostname": "unreachable", "service": "unknown"}


def discover_peers_with_identity(port=8080):
    """
    Discover peers and fetch their identity (hostname, service name).
    Returns list of dicts with ip, hostname, service.
    """
    ips = discover_peers(port=port)

    # Fetch identity for each discovered IP in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        identities = list(executor.map(lambda ip: get_peer_identity(ip, port), ips))

    return identities


def filter_by_service(peers, service_name):
    """
    Filter peers to only include those whose hostname starts with the service name.
    """
    return [p for p in peers if p["hostname"].startswith(service_name)]


@app.get("/", response_class=HTMLResponse)
async def root():
    """
    Main page showing replica information and cluster status.
    Filters to show only replicas of this service (by hostname prefix).
    Auto-refreshes every 5 seconds to show load balancer rotation.
    """
    timestamp = get_timestamp()
    all_peers = discover_peers_with_identity(port=PORT)
    peers = filter_by_service(all_peers, SERVICE_NAME)
    cluster_ok = len(peers) >= REPLICA_COUNT

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Replica Communication Demo</title>
    <meta http-equiv="refresh" content="5">
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
            color: #eee;
            min-height: 100vh;
        }}
        h1 {{
            color: #00d4ff;
            border-bottom: 2px solid #00d4ff;
            padding-bottom: 15px;
            margin-bottom: 10px;
        }}
        h2 {{
            color: #ff6b6b;
            margin-top: 30px;
            margin-bottom: 15px;
        }}
        .timestamp {{
            color: #888;
            font-size: 0.9em;
            margin-bottom: 20px;
        }}
        .box {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            padding: 25px;
            margin: 15px 0;
        }}
        .hostname {{
            font-size: 2.2em;
            color: #00ff88;
            font-weight: bold;
            font-family: 'SF Mono', Monaco, monospace;
            text-shadow: 0 0 20px rgba(0, 255, 136, 0.3);
        }}
        .ip {{
            color: #888;
            font-family: monospace;
            margin-top: 10px;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin: 15px 0;
        }}
        .stat {{
            background: rgba(0, 0, 0, 0.3);
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }}
        .stat-value {{
            font-size: 2.5em;
            font-weight: bold;
            color: #00d4ff;
        }}
        .stat-value.success {{
            color: #00ff88;
        }}
        .stat-label {{
            font-size: 0.8em;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-top: 5px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }}
        th {{
            color: #00d4ff;
            font-size: 0.85em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        code {{
            background: rgba(0, 0, 0, 0.4);
            padding: 3px 8px;
            border-radius: 4px;
            font-family: 'SF Mono', Monaco, monospace;
        }}
        .online {{
            color: #00ff88;
            font-weight: bold;
        }}
        .me {{
            color: #00d4ff;
            font-size: 0.85em;
        }}
        .how-it-works {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }}
        .how-item {{
            background: rgba(0, 0, 0, 0.2);
            padding: 15px;
            border-radius: 8px;
        }}
        .how-item strong {{
            color: #00d4ff;
        }}
        .refresh-note {{
            text-align: center;
            color: #666;
            font-size: 0.85em;
            margin-top: 30px;
            padding: 15px;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
        }}
    </style>
</head>
<body>
    <h1>Replica Communication Demo</h1>
    <p class="timestamp">Generated: {timestamp} | Auto-refreshes every 5 seconds</p>

    <div class="box">
        <div style="color: #888; margin-bottom: 5px;">You are being served by:</div>
        <div class="hostname">{HOSTNAME}</div>
        <div class="ip">IP Address: {MY_IP} | Service: {SERVICE_NAME}</div>
    </div>

    <h2>Cluster Status</h2>
    <div class="grid">
        <div class="stat">
            <div class="stat-value">{len(peers)}</div>
            <div class="stat-label">Replicas Found</div>
        </div>
        <div class="stat">
            <div class="stat-value">{REPLICA_COUNT}</div>
            <div class="stat-label">Expected</div>
        </div>
        <div class="stat">
            <div class="stat-value {'success' if cluster_ok else ''}">{'OK' if cluster_ok else 'DISCOVERING...'}</div>
            <div class="stat-label">Status</div>
        </div>
    </div>

    <h2>Discovered Replicas</h2>
    <div class="box">
        <table>
            <tr>
                <th>#</th>
                <th>Instance Name</th>
                <th>IP Address</th>
                <th>Status</th>
            </tr>
"""

    for i, peer in enumerate(peers, 1):
        is_me = ' <span class="me">(this replica)</span>' if peer["ip"] == MY_IP else ''
        html += f"""
            <tr>
                <td>{i}</td>
                <td><code>{peer["hostname"]}</code>{is_me}</td>
                <td><code>{peer["ip"]}</code></td>
                <td class="online">Online</td>
            </tr>
"""

    html += f"""
        </table>
    </div>

    <h2>How It Works</h2>
    <div class="box">
        <div class="how-it-works">
            <div class="how-item">
                <strong>Discovery Method</strong><br>
                Subnet scanning on port {PORT}
            </div>
            <div class="how-item">
                <strong>Communication</strong><br>
                Direct IP-to-IP HTTP calls
            </div>
            <div class="how-item">
                <strong>DNS Pattern</strong><br>
                <code>{SERVICE_NAME}</code> = round-robin LB
            </div>
            <div class="how-item">
                <strong>Individual Addressing</strong><br>
                Via IP only (no pod-0 style DNS)
            </div>
        </div>
    </div>

    <p class="refresh-note">
        Refresh the page multiple times to see different hostnames above.<br>
        The load balancer rotates between all {REPLICA_COUNT} replicas.
    </p>
</body>
</html>
"""
    return HTMLResponse(content=html)


@app.get("/health")
async def health():
    """Health check endpoint for App Platform."""
    return {
        "status": "healthy",
        "hostname": HOSTNAME,
        "ip": MY_IP,
        "timestamp": time.time()
    }


@app.get("/identity")
async def identity():
    """Return this replica's identity."""
    return {
        "hostname": HOSTNAME,
        "ip": MY_IP,
        "service": SERVICE_NAME,
        "timestamp": get_timestamp()
    }


@app.get("/peers")
async def get_peers():
    """Return list of discovered peer replicas (filtered by service name)."""
    all_peers = discover_peers_with_identity(port=PORT)
    peers = filter_by_service(all_peers, SERVICE_NAME)
    return {
        "hostname": HOSTNAME,
        "ip": MY_IP,
        "service": SERVICE_NAME,
        "peers": [{"hostname": p["hostname"], "ip": p["ip"]} for p in peers],
        "count": len(peers),
        "expected": REPLICA_COUNT
    }


@app.get("/unfiltered", response_class=HTMLResponse)
async def unfiltered():
    """
    Show ALL discovered services on port 8080 without filtering.
    This reveals other services in the same App Platform app that share the port.
    """
    timestamp = get_timestamp()
    all_peers = discover_peers_with_identity(port=PORT)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Unfiltered Discovery - All Services on Port {PORT}</title>
    <meta http-equiv="refresh" content="10">
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1000px;
            margin: 0 auto;
            padding: 20px;
            background: linear-gradient(135deg, #1a0a0a 0%, #4a1a1a 50%, #2a1a1a 100%);
            color: #eee;
            min-height: 100vh;
        }}
        h1 {{
            color: #ff6b6b;
            border-bottom: 2px solid #ff6b6b;
            padding-bottom: 15px;
        }}
        h2 {{
            color: #ffaa00;
            margin-top: 30px;
        }}
        .warning {{
            background: rgba(255, 107, 107, 0.2);
            border: 2px solid #ff6b6b;
            border-radius: 10px;
            padding: 20px;
            margin: 20px 0;
        }}
        .warning strong {{
            color: #ff6b6b;
        }}
        .timestamp {{
            color: #888;
            font-size: 0.9em;
            margin-bottom: 20px;
        }}
        .box {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            padding: 25px;
            margin: 15px 0;
        }}
        .hostname {{
            font-size: 1.8em;
            color: #ff6b6b;
            font-weight: bold;
            font-family: 'SF Mono', Monaco, monospace;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin: 15px 0;
        }}
        .stat {{
            background: rgba(0, 0, 0, 0.3);
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }}
        .stat-value {{
            font-size: 2.5em;
            font-weight: bold;
            color: #ffaa00;
        }}
        .stat-label {{
            font-size: 0.8em;
            color: #888;
            text-transform: uppercase;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }}
        th {{
            color: #ffaa00;
            font-size: 0.85em;
            text-transform: uppercase;
        }}
        code {{
            background: rgba(0, 0, 0, 0.4);
            padding: 3px 8px;
            border-radius: 4px;
            font-family: 'SF Mono', Monaco, monospace;
        }}
        .match {{
            color: #00ff88;
        }}
        .other {{
            color: #ff6b6b;
        }}
        .me {{
            color: #00d4ff;
            font-size: 0.85em;
        }}
    </style>
</head>
<body>
    <h1>Unfiltered Discovery</h1>
    <p class="timestamp">Generated: {timestamp} | Auto-refreshes every 10 seconds</p>

    <div class="warning">
        <strong>WARNING:</strong> This page shows ALL services discovered on port {PORT} via subnet scanning.
        This includes services that are NOT replicas of <code>{SERVICE_NAME}</code>.
        The filtered view at <code>/</code> shows only matching replicas.
    </div>

    <div class="box">
        <div style="color: #888; margin-bottom: 5px;">Current instance:</div>
        <div class="hostname">{HOSTNAME}</div>
        <div style="color: #888; margin-top: 5px;">IP: {MY_IP} | Service: {SERVICE_NAME}</div>
    </div>

    <h2>Discovery Statistics</h2>
    <div class="grid">
        <div class="stat">
            <div class="stat-value">{len(all_peers)}</div>
            <div class="stat-label">Total Discovered</div>
        </div>
        <div class="stat">
            <div class="stat-value">{len([p for p in all_peers if p["hostname"].startswith(SERVICE_NAME)])}</div>
            <div class="stat-label">Match {SERVICE_NAME}</div>
        </div>
        <div class="stat">
            <div class="stat-value">{len([p for p in all_peers if not p["hostname"].startswith(SERVICE_NAME)])}</div>
            <div class="stat-label">Other Services</div>
        </div>
    </div>

    <h2>All Discovered Services</h2>
    <div class="box">
        <table>
            <tr>
                <th>#</th>
                <th>Instance Name (Hostname)</th>
                <th>IP Address</th>
                <th>Matches Service?</th>
            </tr>
"""

    for i, peer in enumerate(all_peers, 1):
        is_me = ' <span class="me">(this instance)</span>' if peer["ip"] == MY_IP else ''
        matches = peer["hostname"].startswith(SERVICE_NAME)
        match_class = "match" if matches else "other"
        match_text = "Yes" if matches else "No"
        html += f"""
            <tr>
                <td>{i}</td>
                <td><code>{peer["hostname"]}</code>{is_me}</td>
                <td><code>{peer["ip"]}</code></td>
                <td class="{match_class}">{match_text}</td>
            </tr>
"""

    html += """
        </table>
    </div>

    <div class="box">
        <h3 style="color: #ffaa00; margin-top: 0;">Why are there extra services?</h3>
        <p>Subnet scanning discovers ALL services listening on the specified port in the same App Platform network.
        This could include:</p>
        <ul>
            <li>Other service components in the same app (web, api, worker)</li>
            <li>Platform infrastructure services</li>
            <li>Services from other apps sharing the same node</li>
        </ul>
        <p>The filtered view at <code>/</code> uses the <code>/identity</code> endpoint to verify each
        discovered service's hostname and only shows those matching <code>""" + SERVICE_NAME + """</code>.</p>
    </div>
</body>
</html>
"""
    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
