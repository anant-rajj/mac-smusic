"""
Precision Monotonic Clock Synchronization Module (mac-smusic)
=============================================================
Implements microsecond-level clock offset estimation and drift rate calculation
using monotonic Mach absolute timestamps and an adaptive SNTP-style filter.
"""

from __future__ import annotations
import time
import struct
import socket
import threading
from typing import Optional, Tuple, List, Dict, Any

# Protocol constants
MAGIC_CLOCK = b"SMCK"
VERSION = 1
TYPE_REQ = 1
TYPE_RESP = 2

# Struct: Magic(4s), Version(B), Type(B), Reserved(2s), Seq(I), T1(Q), T2(Q), T3(Q)
PACKET_FORMAT = "!4sBB2sIQQQ"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)


class ClockSyncClient:
    """
    Client-side clock synchronizer.
    Periodically sends timestamp pings to the host, computes RTT and clock offset,
    and maintains an exponentially filtered clock skew estimate.
    """

    def __init__(self, host: str, port: int = 49530, window_size: int = 16):
        self.host = host
        self.port = port
        self.window_size = window_size
        self._seq = 0
        self._sock: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # State estimates
        self.offset_ns: int = 0
        self.min_rtt_ns: int = 1_000_000_000  # Initial 1 sec fallback
        self.last_rtt_ns: int = 0
        self.jitter_ns: int = 0
        self.drift_ppm: float = 0.0
        self.samples: List[Tuple[int, int, int]] = []  # (t_client_ns, offset_ns, rtt_ns)
        self._lock = threading.Lock()

    def start(self, interval_sec: float = 0.25) -> None:
        """Starts background clock synchronization thread."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.5)
        self._running = True
        self._thread = threading.Thread(target=self._sync_loop, args=(interval_sec,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stops background clock synchronization."""
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def host_to_local_ns(self, host_time_ns: int) -> int:
        """Translates a host monotonic timestamp to the receiver's local monotonic timeline."""
        with self._lock:
            return host_time_ns - self.offset_ns

    def local_to_host_ns(self, local_time_ns: int) -> int:
        """Translates local monotonic time to host monotonic timeline."""
        with self._lock:
            return local_time_ns + self.offset_ns

    def sync_once(self) -> Optional[Tuple[int, int]]:
        """
        Performs a single round-trip timestamp exchange.
        Returns (offset_ns, rtt_ns) or None if timed out.
        """
        if not self._sock:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(0.5)

        self._seq = (self._seq + 1) & 0xFFFFFFFF
        t1 = time.monotonic_ns()
        packet = struct.pack(PACKET_FORMAT, MAGIC_CLOCK, VERSION, TYPE_REQ, b"\x00\x00", self._seq, t1, 0, 0)

        try:
            self._sock.sendto(packet, (self.host, self.port))
            data, _ = self._sock.recvfrom(PACKET_SIZE)
            t4 = time.monotonic_ns()

            if len(data) < PACKET_SIZE:
                return None

            magic, ver, ptype, _, seq, r_t1, t2, t3 = struct.unpack(PACKET_FORMAT, data)
            if magic != MAGIC_CLOCK or ver != VERSION or ptype != TYPE_RESP or seq != self._seq:
                return None

            # Calculate RTT and Clock Offset
            rtt = (t4 - t1) - (t3 - t2)
            if rtt < 0:
                rtt = 0

            # Offset = ((T2 - T1) + (T3 - T4)) / 2
            offset = ((t2 - t1) + (t3 - t4)) // 2

            with self._lock:
                self.last_rtt_ns = rtt
                self.samples.append((t4, offset, rtt))
                if len(self.samples) > self.window_size:
                    self.samples.pop(0)

                # Use the sample with lowest RTT (least network queue delay)
                best_sample = min(self.samples, key=lambda s: s[2])
                self.min_rtt_ns = best_sample[2]

                # Exponential smoothing of offset
                if self.offset_ns == 0:
                    self.offset_ns = offset
                else:
                    alpha = 0.85
                    self.offset_ns = int(alpha * self.offset_ns + (1.0 - alpha) * best_sample[1])

                # Compute Jitter (mean deviation)
                if len(self.samples) > 2:
                    mean_rtt = sum(s[2] for s in self.samples) / len(self.samples)
                    self.jitter_ns = int(sum(abs(s[2] - mean_rtt) for s in self.samples) / len(self.samples))

                # Compute Drift Rate (PPM) if we have sufficient time span (> 2 seconds)
                if len(self.samples) >= 4:
                    dt_span = (self.samples[-1][0] - self.samples[0][0]) / 1e9
                    if dt_span >= 2.0:
                        d_offset = (self.samples[-1][1] - self.samples[0][1]) / 1e9
                        # PPM = (offset change / elapsed time) * 1,000,000
                        self.drift_ppm = (d_offset / dt_span) * 1_000_000.0

            return offset, rtt
        except (socket.timeout, OSError):
            return None

    def _sync_loop(self, interval: float) -> None:
        """Background continuous sync loop."""
        while self._running:
            self.sync_once()
            time.sleep(interval)


class ClockSyncServer:
    """
    Host-side clock synchronization server.
    Listens for timestamp requests and returns immediate arrival/send timestamps.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 49530):
        self.host = host
        self.port = port
        self._sock: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Starts background clock response server."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.settimeout(0.5)
        self._running = True
        self._thread = threading.Thread(target=self._server_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stops clock response server."""
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _server_loop(self) -> None:
        """Listens and responds immediately to SNTP sync requests."""
        while self._running:
            try:
                assert self._sock is not None
                data, addr = self._sock.recvfrom(PACKET_SIZE)
                t2 = time.monotonic_ns()

                if len(data) < PACKET_SIZE:
                    continue

                magic, ver, ptype, _, seq, t1, _, _ = struct.unpack(PACKET_FORMAT, data)
                if magic != MAGIC_CLOCK or ver != VERSION or ptype != TYPE_REQ:
                    continue

                t3 = time.monotonic_ns()
                resp = struct.pack(PACKET_FORMAT, MAGIC_CLOCK, VERSION, TYPE_RESP, b"\x00\x00", seq, t1, t2, t3)
                self._sock.sendto(resp, addr)
            except (socket.timeout, OSError):
                continue
