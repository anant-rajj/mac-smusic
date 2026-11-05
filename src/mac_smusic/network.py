"""
High-Precision Audio Packet Network Protocol (mac-smusic)
=========================================================
Implements UDP multicast and unicast audio packet transmission with
embedded scheduled playout timestamps and sequence sequencing.
"""

from __future__ import annotations
import struct
import socket
import select
from typing import Optional, Tuple, NamedTuple, List

MAGIC_AUDIO = b"MSMC"
VERSION = 1

# Packet Header:
# Magic(4s), Version(B), Channels(B), SampleRate(H), Seq(I), PlayoutTimeNs(Q), PayloadLen(I), Reserved(8s)
AUDIO_HEADER_FMT = "!4sBBHIQI8s"
AUDIO_HEADER_SIZE = struct.calcsize(AUDIO_HEADER_FMT)

DEFAULT_AUDIO_PORT = 49531
DEFAULT_MULTICAST_GROUP = "239.255.49.50"


class AudioPacket(NamedTuple):
    channels: int
    sample_rate: int
    seq: int
    host_playout_ns: int
    payload: bytes


def pack_audio_packet(channels: int, sample_rate: int, seq: int, host_playout_ns: int, payload: bytes) -> bytes:
    """Serializes audio chunk with protocol header."""
    header = struct.pack(
        AUDIO_HEADER_FMT,
        MAGIC_AUDIO,
        VERSION,
        channels,
        sample_rate,
        seq & 0xFFFFFFFF,
        host_playout_ns,
        len(payload),
        b"\x00" * 8,
    )
    return header + payload


def unpack_audio_packet(data: bytes) -> Optional[AudioPacket]:
    """Deserializes binary packet into AudioPacket namedtuple."""
    if len(data) < AUDIO_HEADER_SIZE:
        return None

    magic, ver, channels, sample_rate, seq, host_playout_ns, payload_len, _ = struct.unpack(
        AUDIO_HEADER_FMT, data[:AUDIO_HEADER_SIZE]
    )

    if magic != MAGIC_AUDIO or ver != VERSION:
        return None

    payload = data[AUDIO_HEADER_SIZE : AUDIO_HEADER_SIZE + payload_len]
    if len(payload) != payload_len:
        return None

    return AudioPacket(
        channels=channels,
        sample_rate=sample_rate,
        seq=seq,
        host_playout_ns=host_playout_ns,
        payload=payload,
    )


class AudioBroadcaster:
    """Transmits timestamped audio chunks to local network peers via UDP multicast / broadcast."""

    def __init__(
        self,
        port: int = DEFAULT_AUDIO_PORT,
        multicast_group: str = DEFAULT_MULTICAST_GROUP,
        unicast_peers: Optional[List[str]] = None,
    ):
        self.port = port
        self.multicast_group = multicast_group
        self.unicast_peers = unicast_peers or []
        self._seq = 0
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

        # Enable broadcast
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # Set Multicast TTL & Loopback
        ttl = struct.pack("b", 2)
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
        try:
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        except OSError:
            pass

    def add_peer(self, ip: str) -> None:
        if ip not in self.unicast_peers:
            self.unicast_peers.append(ip)

    def send_chunk(self, pcm_bytes: bytes, host_playout_ns: int, sample_rate: int = 44100, channels: int = 2) -> int:
        """Packs and broadcasts an audio chunk to multicast group and registered peers."""
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        packet = pack_audio_packet(channels, sample_rate, self._seq, host_playout_ns, pcm_bytes)

        # Send to multicast group
        try:
            self._sock.sendto(packet, (self.multicast_group, self.port))
        except OSError:
            pass

        # Send to broadcast fallback
        try:
            self._sock.sendto(packet, ("<broadcast>", self.port))
        except OSError:
            pass

        # Send to explicit unicast peers
        for peer in self.unicast_peers:
            try:
                self._sock.sendto(packet, (peer, self.port))
            except OSError:
                pass

        return self._seq

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass


class AudioReceiver:
    """Receives timestamped audio chunks from multicast or broadcast."""

    def __init__(self, port: int = DEFAULT_AUDIO_PORT, multicast_group: str = DEFAULT_MULTICAST_GROUP):
        self.port = port
        self.multicast_group = multicast_group
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass

        # Bind to all interfaces
        self._sock.bind(("", self.port))

        # Join multicast group
        try:
            mreq = struct.pack("4sl", socket.inet_aton(self.multicast_group), socket.INADDR_ANY)
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError:
            pass

        self._last_seq = -1
        self.packets_received = 0
        self.packets_dropped = 0

    def receive_chunk(self, timeout_sec: float = 0.1) -> Optional[AudioPacket]:
        """Reads the next available audio packet with timeout."""
        ready = select.select([self._sock], [], [], timeout_sec)
        if not ready[0]:
            return None

        try:
            data, _ = self._sock.recvfrom(65535)
            packet = unpack_audio_packet(data)
            if packet is not None:
                self.packets_received += 1
                if self._last_seq != -1:
                    expected_seq = (self._last_seq + 1) & 0xFFFFFFFF
                    if packet.seq > expected_seq:
                        self.packets_dropped += (packet.seq - expected_seq)
                self._last_seq = packet.seq
            return packet
        except OSError:
            return None

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass
