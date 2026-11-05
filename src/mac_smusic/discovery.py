"""
Zero-Configuration Local Network Discovery (mac-smusic)
=======================================================
Implements Bonjour/mDNS-style UDP beacon discovery across the LAN
so Macs find each other automatically with zero IP configuration.
"""

from __future__ import annotations
import json
import time
import socket
import select
import platform
import threading
from typing import Optional, Dict, List, Any, Callable

DISCOVERY_PORT = 49532
DISCOVERY_GROUP = "239.255.49.52"
MAGIC_BEACON = "MAC-SMUSIC-BEACON-V1"


class HostBeacon:
    """Broadcasts presence and service capabilities on the local subnet."""

    def __init__(self, machine_name: Optional[str] = None, clock_port: int = 49530, audio_port: int = 49531):
        self.machine_name = machine_name or platform.node().replace(".local", "")
        self.clock_port = clock_port
        self.audio_port = audio_port
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        except OSError:
            pass

    def start(self, interval_sec: float = 1.0) -> None:
        """Starts periodic discovery broadcast in the background."""
        self._running = True
        self._thread = threading.Thread(target=self._broadcast_loop, args=(interval_sec,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stops discovery broadcast."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        try:
            self._sock.close()
        except Exception:
            pass

    def _broadcast_loop(self, interval: float) -> None:
        while self._running:
            payload = json.dumps({
                "magic": MAGIC_BEACON,
                "name": self.machine_name,
                "clock_port": self.clock_port,
                "audio_port": self.audio_port,
                "time": time.time(),
            }).encode("utf-8")

            # Broadcast to LAN broadcast and multicast
            try:
                self._sock.sendto(payload, ("<broadcast>", DISCOVERY_PORT))
            except OSError:
                pass

            try:
                self._sock.sendto(payload, (DISCOVERY_GROUP, DISCOVERY_PORT))
            except OSError:
                pass

            # Loopback broadcast for local tests & CI runners
            try:
                self._sock.sendto(payload, ("127.0.0.1", DISCOVERY_PORT))
            except OSError:
                pass

            time.sleep(interval)


class NetworkScanner:
    """Listens for active mac-smusic hosts and peers on the local subnet."""

    def __init__(self, port: int = DISCOVERY_PORT):
        self.port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass

        self._sock.bind(("", self.port))

        # Join multicast group
        try:
            mreq = socket.inet_aton(DISCOVERY_GROUP) + socket.inet_aton("0.0.0.0")
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError:
            pass

    def scan(self, timeout_sec: float = 2.0) -> List[Dict[str, Any]]:
        """Scans for active mac-smusic hosts on the local network."""
        start_time = time.time()
        discovered: Dict[str, Dict[str, Any]] = {}

        while (time.time() - start_time) < timeout_sec:
            rem_timeout = max(0.05, timeout_sec - (time.time() - start_time))
            ready = select.select([self._sock], [], [], rem_timeout)
            if not ready[0]:
                break

            try:
                data, addr = self._sock.recvfrom(4096)
                ip = addr[0]
                info = json.loads(data.decode("utf-8"))
                if info.get("magic") == MAGIC_BEACON:
                    discovered[ip] = {
                        "ip": ip,
                        "name": info.get("name", "Unknown Mac"),
                        "clock_port": info.get("clock_port", 49530),
                        "audio_port": info.get("audio_port", 49531),
                        "last_seen": time.time(),
                    }
            except (json.JSONDecodeError, OSError):
                continue

        return list(discovered.values())

    def find_first_host(self, timeout_sec: float = 3.0) -> Optional[Dict[str, Any]]:
        """Blocks until the first active mac-smusic host is discovered, or returns None on timeout."""
        start = time.time()
        while (time.time() - start) < timeout_sec:
            results = self.scan(timeout_sec=0.5)
            if results:
                return results[0]
        return None

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass
