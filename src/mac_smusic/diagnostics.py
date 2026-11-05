"""
Diagnostic Radar, Network Latency, & Drift Calibrator (mac-smusic)
==================================================================
Provides network telemetry, clock sync benchmarking, and live HUD displays.
"""

from __future__ import annotations
import time
import socket
import platform
from typing import List, Dict, Any, Optional

from mac_smusic.discovery import NetworkScanner
from mac_smusic.clock import ClockSyncClient


def run_radar_scan(timeout_sec: float = 2.5) -> List[Dict[str, Any]]:
    """Discovers all active mac-smusic host instances on the local subnet."""
    scanner = NetworkScanner()
    try:
        hosts = scanner.scan(timeout_sec=timeout_sec)
        for host in hosts:
            # Measure immediate RTT to each discovered host
            client = ClockSyncClient(host["ip"], port=host["clock_port"], window_size=4)
            res = client.sync_once()
            if res:
                offset_ns, rtt_ns = res
                host["rtt_ms"] = round(rtt_ns / 1e6, 2)
                host["offset_ms"] = round(offset_ns / 1e6, 2)
            else:
                host["rtt_ms"] = -1.0
                host["offset_ms"] = 0.0
            client.stop()
        return hosts
    finally:
        scanner.close()


def run_sync_benchmark(host_ip: str, clock_port: int = 49530, count: int = 10) -> Dict[str, Any]:
    """Runs high-precision SNTP clock synchronization benchmarking against a target Mac."""
    client = ClockSyncClient(host_ip, port=clock_port, window_size=count)
    client._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client._sock.settimeout(0.5)

    rtt_samples: List[float] = []
    offset_samples: List[float] = []

    for _ in range(count):
        res = client.sync_once()
        if res:
            offset_ns, rtt_ns = res
            rtt_samples.append(rtt_ns / 1e6)
            offset_samples.append(offset_ns / 1e6)
        time.sleep(0.1)

    client.stop()

    if not rtt_samples:
        return {"success": False, "error": "Connection timed out. Host unreachable."}

    min_rtt = min(rtt_samples)
    max_rtt = max(rtt_samples)
    avg_rtt = sum(rtt_samples) / len(rtt_samples)
    avg_offset = sum(offset_samples) / len(offset_samples)
    jitter = sum(abs(r - avg_rtt) for r in rtt_samples) / len(rtt_samples)

    if jitter < 0.5:
        verdict = "PERFECT (Ultra-low jitter, sub-millisecond phase-lock achievable)"
    elif jitter < 2.0:
        verdict = "EXCELLENT (Standard high-speed 5GHz Wi-Fi / LAN, flawless sync)"
    elif jitter < 5.0:
        verdict = "GOOD (Minor Wi-Fi jitter, drift compensation active)"
    else:
        verdict = "HIGH JITTER (Recommend 5GHz Wi-Fi or wired Ethernet for zero drift)"

    return {
        "success": True,
        "host": host_ip,
        "samples": len(rtt_samples),
        "min_rtt_ms": round(min_rtt, 3),
        "max_rtt_ms": round(max_rtt, 3),
        "avg_rtt_ms": round(avg_rtt, 3),
        "avg_offset_ms": round(avg_offset, 3),
        "jitter_ms": round(jitter, 3),
        "drift_ppm": round(client.drift_ppm, 2),
        "verdict": verdict,
    }


def get_system_audio_status() -> Dict[str, Any]:
    """Extracts local system audio and network configuration info."""
    hostname = platform.node()
    local_ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        local_ips.append("127.0.0.1")

    return {
        "hostname": hostname,
        "os_version": platform.mac_ver()[0],
        "arch": platform.machine(),
        "primary_ip": local_ips[0] if local_ips else "Unknown",
        "default_clock_port": 49530,
        "default_audio_port": 49531,
    }
