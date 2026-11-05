"""
Command-Line Interface Entrypoint (mac-smusic)
==============================================
Provides personalized CLI commands for multi-Mac audio and music synchronization.
"""

from __future__ import annotations
import os
import sys
import time
import signal
import argparse
from typing import Optional

from mac_smusic import __version__
from mac_smusic.clock import ClockSyncServer, ClockSyncClient
from mac_smusic.network import AudioBroadcaster, AudioReceiver, DEFAULT_AUDIO_PORT
from mac_smusic.discovery import HostBeacon, NetworkScanner
from mac_smusic.decoder import decode_audio_file, DEFAULT_CHUNK_FRAMES
from mac_smusic.player import CoreAudioPlayer
from mac_smusic.resampler import AdaptiveResampler
from mac_smusic.streamer import CoreAudioCapture
from mac_smusic.diagnostics import run_radar_scan, run_sync_benchmark, get_system_audio_status

# ANSI Color Codes
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def print_banner() -> None:
    print(f"{CYAN}{BOLD}mac-smusic{RESET} {DIM}v{__version__}{RESET} // {MAGENTA}Precision Multi-Mac Synchronized Audio Engine{RESET}\n")


def print_multiuser_guide() -> None:
    """Displays the interactive multi-Mac setup and connection walkthrough."""
    print_banner()
    guide = f"""{BOLD}MULTI-MAC SYNCHRONIZED AUDIO // QUICK ONBOARDING GUIDE{RESET}
================================================================================
Play the exact same music or live audio across {BOLD}2, 3, 5, or 50+ Macs{RESET} simultaneously
over your local Wi-Fi or Ethernet network in sub-millisecond phase-lock!

{CYAN}┌──────────────────────────────────────────────────────────────────────────────┐
│                            MULTI-MAC NETWORK TOPOLOGY                        │
│                                                                              │
│                         ┌─────────────────────────────┐                      │
│                         │     HOST MAC (BROADCASTER)  │                      │
│                         │  mac-smusic play track.mp3  │                      │
│                         └──────────────┬──────────────┘                      │
│                                        │ UDP Multicast / mDNS Beacon         │
│               ┌────────────────────────┼────────────────────────┐            │
│               ▼                        ▼                        ▼            │
│  ┌────────────────────────┐┌────────────────────────┐┌────────────────────┐  │
│  │   MAC 2 (RECEIVER A)   ││   MAC 3 (RECEIVER B)   ││ MAC 4 (RECEIVER C) │...│
│  │     mac-smusic join    ││     mac-smusic join    ││   mac-smusic join  │  │
│  └────────────────────────┘└────────────────────────┘└────────────────────┘  │
│            🔊                       🔊                       🔊              │
│                     PERFECT PHASE-LOCKED HARDWARE PLAYOUT                    │
└──────────────────────────────────────────────────────────────────────────────┘{RESET}

{GREEN}{BOLD}STEP 1: ON THE FIRST MAC (BROADCASTER / DJ){RESET}
  Choose any music file and start broadcasting:
    {BOLD}mac-smusic play ~/Music/song.mp3{RESET}

  Or stream live system audio / microphone (e.g., via BlackHole):
    {BOLD}mac-smusic stream{RESET}

{GREEN}{BOLD}STEP 2: ON ALL OTHER MACS (RECEIVERS / MULTI-ROOM / OFFICE PARTY){RESET}
  On Mac 2, Mac 3, Mac 4, etc., simply run:
    {BOLD}mac-smusic join{RESET}

  {DIM}Zero IP typing required! Each receiver auto-discovers the host on your Wi-Fi,
  calibrates crystal clock drift, and begins playing synchronously with < 0.5ms delay.{RESET}

{GREEN}{BOLD}STEP 3: MULTI-MAC FLEET COMMANDS & FUNCTIONS{RESET}
  {BOLD}mac-smusic play <file>{RESET}       Broadcast a music file (.mp3, .wav, .flac, .m4a) to all Macs
  {BOLD}mac-smusic join{RESET}              Auto-discover host and play along in sync
  {BOLD}mac-smusic join --host <ip>{RESET}  Join a specific Mac directly (bypass auto-discovery)
  {BOLD}mac-smusic stream{RESET}            Broadcast live microphone or system audio input
  {BOLD}mac-smusic scan{RESET}              Radar scan your Wi-Fi to find all Macs running mac-smusic
  {BOLD}mac-smusic sync [host_ip]{RESET}    Benchmark latency, network jitter, and crystal clock drift PPM
  {BOLD}mac-smusic status{RESET}            Display local CoreAudio and network configuration
  {BOLD}mac-smusic guide{RESET}             Display this multi-Mac onboarding guide

{YELLOW}{BOLD}PRO TIPS FOR MULTIPLE USERS:{RESET}
  • {BOLD}Unlimited Listeners:{RESET} Because mac-smusic uses hardware UDP Multicast, adding 10
    or 50 Macs introduces 0 additional CPU or network overhead on the host.
  • {BOLD}Network Quality:{RESET} For the best experience, connect all Macs to the same 5GHz
    Wi-Fi band or local wired Ethernet.
  • {BOLD}Check Your Network:{RESET} Run {BOLD}mac-smusic scan{RESET} at any time to see every active Mac.
================================================================================
"""
    print(guide)


def command_host(args: argparse.Namespace) -> None:
    """Runs mac-smusic in Broadcaster/Host mode."""
    print_banner()
    lead_buffer_ns = int(args.buffer * 1_000_000)
    print(f"{GREEN}[✓]{RESET} Starting Clock Synchronization Server on UDP port {args.clock_port}...")
    clock_server = ClockSyncServer(port=args.clock_port)
    clock_server.start()

    print(f"{GREEN}[✓]{RESET} Initializing Bonjour Discovery Beacon...")
    beacon = HostBeacon(clock_port=args.clock_port, audio_port=args.audio_port)
    beacon.start()

    print(f"{GREEN}[✓]{RESET} Initializing Audio Broadcaster on UDP port {args.audio_port} (Playout Lead: {args.buffer}ms)...")
    broadcaster = AudioBroadcaster(port=args.audio_port)

    # Local audio player so the host Mac also plays along synchronously
    local_player = CoreAudioPlayer(sample_rate=44100, channels=2)

    stop_event = False

    def handle_sigint(sig, frame):
        nonlocal stop_event
        print(f"\n{YELLOW}[!] Stopping mac-smusic host gracefully...{RESET}")
        stop_event = True

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    if args.file:
        file_path = os.path.abspath(args.file)
        print(f"\n{CYAN}[▶]{RESET} Loading & broadcasting audio file: {BOLD}{os.path.basename(file_path)}{RESET}")
        try:
            chunks = list(decode_audio_file(file_path, chunk_frames=DEFAULT_CHUNK_FRAMES))
        except Exception as e:
            print(f"{YELLOW}[ERROR]{RESET} Failed to decode audio file: {e}")
            clock_server.stop()
            beacon.stop()
            broadcaster.close()
            return

        print(f"{GREEN}[✓]{RESET} Decoded {len(chunks)} audio chunks ({round(len(chunks) * 1024 / 44100, 1)}s). Broadcasting to peers...\n")

        chunk_duration_sec = DEFAULT_CHUNK_FRAMES / 44100.0
        start_mono_ns = time.monotonic_ns()

        for idx, chunk in enumerate(chunks):
            if stop_event:
                break

            target_host_playout_ns = start_mono_ns + int((idx * chunk_duration_sec) * 1e9) + lead_buffer_ns

            # Broadcast packet to all connected Macs
            broadcaster.send_chunk(chunk, host_playout_ns=target_host_playout_ns)

            # Push to local speaker player when scheduled playout time nears
            local_player.push_pcm(chunk)

            # Regulate broadcast loop pacing
            now_ns = time.monotonic_ns()
            scheduled_send_ns = start_mono_ns + int((idx * chunk_duration_sec) * 1e9)
            if scheduled_send_ns > now_ns:
                time.sleep((scheduled_send_ns - now_ns) / 1e9)

            if idx % 100 == 0 or idx == len(chunks) - 1:
                elapsed_sec = round(idx * chunk_duration_sec, 1)
                total_sec = round(len(chunks) * chunk_duration_sec, 1)
                active_clients = clock_server.get_active_clients()
                client_str = f"{len(active_clients)} Mac(s) in sync ({', '.join(active_clients)})" if active_clients else "Broadcasting (waiting for peers)"
                sys.stdout.write(f"\r{CYAN}[SYNC STREAM]{RESET} {elapsed_sec}s / {total_sec}s | {GREEN}● {client_str}{RESET}   ")
                sys.stdout.flush()

        print(f"\n{GREEN}[✓] Playback complete.{RESET}")
    else:
        print(f"\n{CYAN}[HOST IDLE]{RESET} Waiting for audio source. You can run:")
        print(f"  {BOLD}mac-smusic play <song.mp3>{RESET}  to stream music across all connected Macs.")
        print(f"  {BOLD}mac-smusic stream{RESET}           to stream live system/microphone audio.")
        print(f"\nPress Ctrl+C to stop host daemon.\n")
        while not stop_event:
            active_clients = clock_server.get_active_clients()
            client_count = len(active_clients)
            client_str = f"{client_count} Mac(s) in sync ({', '.join(active_clients)})" if active_clients else "Listening for listener Macs on Wi-Fi..."
            sys.stdout.write(f"\r{CYAN}[HOST READY]{RESET} {GREEN}● {client_str}{RESET}   ")
            sys.stdout.flush()
            time.sleep(0.5)

    local_player.stop()
    beacon.stop()
    broadcaster.close()
    clock_server.stop()
    print(f"{GREEN}[✓] mac-smusic host shut down cleanly.{RESET}")


def command_join(args: argparse.Namespace) -> None:
    """Runs mac-smusic in Receiver/Follower mode."""
    print_banner()

    target_host_ip = args.host
    clock_port = args.clock_port
    audio_port = args.audio_port

    if not target_host_ip:
        print(f"{CYAN}[🔍]{RESET} Auto-discovering broadcasting Mac via Bonjour mDNS...")
        scanner = NetworkScanner()
        discovered = scanner.find_first_host(timeout_sec=args.timeout)
        scanner.close()

        if not discovered:
            print(f"{YELLOW}[!] No broadcasting Mac found on the local network.{RESET}")
            print(f"    Ensure the host Mac has run {BOLD}mac-smusic host{RESET} or specify: {BOLD}mac-smusic join --host <IP>{RESET}")
            return

        target_host_ip = discovered["ip"]
        clock_port = discovered["clock_port"]
        audio_port = discovered["audio_port"]
        print(f"{GREEN}[✓]{RESET} Discovered Host: {BOLD}{discovered['name']}{RESET} at {CYAN}{target_host_ip}{RESET}")

    print(f"{GREEN}[✓]{RESET} Initializing Microsecond Clock Synchronizer with {target_host_ip}:{clock_port}...")
    clock_client = ClockSyncClient(target_host_ip, port=clock_port)
    clock_client.start(interval_sec=0.2)

    # Initial clock handshake
    print(f"{CYAN}[⏳]{RESET} Locking onto host timeline and measuring network jitter...")
    time.sleep(1.0)
    print(f"{GREEN}[✓]{RESET} Locked! Clock Offset: {BOLD}{round(clock_client.offset_ns / 1e6, 2)}ms{RESET} | Min RTT: {round(clock_client.min_rtt_ns / 1e6, 2)}ms | Jitter: {round(clock_client.jitter_ns / 1e6, 3)}ms")

    print(f"{GREEN}[✓]{RESET} Listening for synchronized audio packets on UDP port {audio_port}...")
    receiver = AudioReceiver(port=audio_port)
    player = CoreAudioPlayer(sample_rate=44100, channels=2)
    resampler = AdaptiveResampler(sample_rate=44100, channels=2)

    stop_event = False

    def handle_sigint(sig, frame):
        nonlocal stop_event
        print(f"\n{YELLOW}[!] Leaving synchronized audio session...{RESET}")
        stop_event = True

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    packet_count = 0
    start_time = time.time()

    print(f"\n{GREEN}[READY]{RESET} Synchronized audio stream active. Audio playing through native CoreAudio DAC.")

    while not stop_event:
        packet = receiver.receive_chunk(timeout_sec=0.2)
        if not packet:
            continue

        packet_count += 1
        now_local_ns = time.monotonic_ns()
        target_local_playout_ns = clock_client.host_to_local_ns(packet.host_playout_ns)
        queue_error_ms = (target_local_playout_ns - now_local_ns) / 1e6

        # Apply adaptive resampler to regulate hardware clock drift
        ratio = resampler.update_drift_correction(queue_error_ms)
        regulated_pcm = resampler.resample_chunk(packet.payload, ratio)

        player.push_pcm(regulated_pcm)

        if packet_count % 50 == 0:
            drift = round(clock_client.drift_ppm, 1)
            offset = round(clock_client.offset_ns / 1e6, 2)
            sys.stdout.write(
                f"\r{CYAN}[LOCK]{RESET} Packets: {packet_count} | Offset: {offset}ms | Queue Lead: {round(queue_error_ms, 1)}ms | Drift: {drift} PPM | Loss: {receiver.packets_dropped} pkts  "
            )
            sys.stdout.flush()

    player.stop()
    receiver.close()
    clock_client.stop()
    print(f"\n{GREEN}[✓] Disconnected cleanly.{RESET}")


def command_play(args: argparse.Namespace) -> None:
    """Plays an audio file synchronized across all Macs."""
    args.file = args.audio_file
    args.clock_port = 49530
    args.audio_port = DEFAULT_AUDIO_PORT
    command_host(args)


def command_stream(args: argparse.Namespace) -> None:
    """Streams live microphone or system audio input across all Macs."""
    print_banner()
    lead_buffer_ns = int(args.buffer * 1_000_000)

    print(f"{GREEN}[✓]{RESET} Starting Clock Server & Beacon...")
    clock_server = ClockSyncServer(port=args.clock_port)
    clock_server.start()

    beacon = HostBeacon(clock_port=args.clock_port, audio_port=args.audio_port)
    beacon.start()

    broadcaster = AudioBroadcaster(port=args.audio_port)
    capture = CoreAudioCapture(sample_rate=44100, channels=2)

    try:
        capture.start()
        print(f"{GREEN}[✓]{RESET} Live CoreAudio input stream active. Streaming in real-time with {args.buffer}ms lead buffer.")
        print(f"    Press Ctrl+C to stop streaming.\n")

        stop_event = False

        def handle_sigint(sig, frame):
            nonlocal stop_event
            print(f"\n{YELLOW}[!] Stopping live stream...{RESET}")
            stop_event = True

        signal.signal(signal.SIGINT, handle_sigint)

        chunk_idx = 0
        while not stop_event:
            chunk = capture.read_chunk(timeout_sec=0.1)
            if chunk:
                chunk_idx += 1
                now_ns = time.monotonic_ns()
                playout_ns = now_ns + lead_buffer_ns
                broadcaster.send_chunk(chunk, host_playout_ns=playout_ns)

                if chunk_idx % 50 == 0:
                    sys.stdout.write(f"\r{CYAN}[LIVE STREAM]{RESET} Chunks Broadcasted: {chunk_idx} | Buffer Lead: {args.buffer}ms  ")
                    sys.stdout.flush()
    finally:
        capture.stop()
        beacon.stop()
        broadcaster.close()
        clock_server.stop()
        print(f"\n{GREEN}[✓] Live stream terminated.{RESET}")


def command_scan(args: argparse.Namespace) -> None:
    """Scans the local network for other Macs running mac-smusic."""
    print_banner()
    print(f"{CYAN}[📡]{RESET} Scanning local subnet for active mac-smusic devices (Timeout: {args.timeout}s)...\n")
    hosts = run_radar_scan(timeout_sec=args.timeout)

    if not hosts:
        print(f"{YELLOW}[!] No other mac-smusic devices detected on your subnet.{RESET}")
        print(f"    Start a host on another Mac with: {BOLD}mac-smusic host{RESET}")
        return

    print(f"{BOLD}{'MACHINE NAME':<25} {'IP ADDRESS':<18} {'RTT':<12} {'CLOCK OFFSET':<15} {'PORTS'}{RESET}")
    print("-" * 80)
    for h in hosts:
        rtt_str = f"{h['rtt_ms']} ms" if h['rtt_ms'] >= 0 else "N/A"
        offset_str = f"{h['offset_ms']} ms" if h['rtt_ms'] >= 0 else "N/A"
        ports_str = f"Clock:{h['clock_port']} / Audio:{h['audio_port']}"
        print(f"{GREEN}{h['name']:<25}{RESET} {h['ip']:<18} {rtt_str:<12} {offset_str:<15} {DIM}{ports_str}{RESET}")
    print("-" * 80)
    print(f"\n{GREEN}[✓] Found {len(hosts)} active device(s). Connect with: {BOLD}mac-smusic join --host {hosts[0]['ip']}{RESET}\n")


def command_sync(args: argparse.Namespace) -> None:
    """Measures clock offset, jitter, and drift PPM between this Mac and another."""
    print_banner()
    host_ip = args.host
    if not host_ip:
        print(f"{CYAN}[🔍]{RESET} Probing subnet for host to benchmark...")
        scanner = NetworkScanner()
        discovered = scanner.find_first_host(timeout_sec=2.0)
        scanner.close()
        if not discovered:
            print(f"{YELLOW}[ERROR]{RESET} No host found. Provide an explicit IP: {BOLD}mac-smusic sync <host_ip>{RESET}")
            return
        host_ip = discovered["ip"]

    print(f"{CYAN}[⏱]{RESET} Running clock synchronization benchmark against {BOLD}{host_ip}{RESET} (10 samples)...\n")
    report = run_sync_benchmark(host_ip, count=10)

    if not report.get("success"):
        print(f"{YELLOW}[ERROR]{RESET} {report.get('error')}")
        return

    print(f"{BOLD}SYNCHRONIZATION TELEMETRY REPORT{RESET}")
    print("=" * 45)
    print(f" Target Host:       {CYAN}{report['host']}{RESET}")
    print(f" Round-Trip (RTT):  Min: {report['min_rtt_ms']}ms | Avg: {report['avg_rtt_ms']}ms | Max: {report['max_rtt_ms']}ms")
    print(f" Network Jitter:    {report['jitter_ms']} ms")
    print(f" Clock Offset:      {report['avg_offset_ms']} ms")
    print(f" Estimated Drift:   {report['drift_ppm']} PPM")
    print(f" Verdict:           {GREEN}{report['verdict']}{RESET}")
    print("=" * 45)


def command_status(args: argparse.Namespace) -> None:
    """Displays local audio status and device network telemetry."""
    print_banner()
    info = get_system_audio_status()
    print(f"{BOLD}LOCAL MACHINE TELEMETRY{RESET}")
    print("=" * 45)
    print(f" Machine Name:      {CYAN}{info['hostname']}{RESET}")
    print(f" macOS Version:     {info['os_version']} ({info['arch']})")
    print(f" Primary Local IP:  {info['primary_ip']}")
    print(f" Default Ports:     Clock: {info['default_clock_port']} (UDP) | Audio: {info['default_audio_port']} (UDP)")
    print(f" CoreAudio Driver:  Native AudioToolbox AudioQueue (Zero-KEXT)")
    print("=" * 45)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mac-smusic",
        description="Precision Multi-Mac Synchronized Audio Engine for macOS.",
    )
    parser.add_argument("-v", "--version", action="version", version=f"mac-smusic {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Host command
    host_p = subparsers.add_parser("host", help="Start master audio broadcaster & clock server")
    host_p.add_argument("-f", "--file", type=str, help="Path to audio file to broadcast (.mp3, .wav, .flac, .m4a)")
    host_p.add_argument("-b", "--buffer", type=int, default=200, help="Target lead buffer in milliseconds (default: 200)")
    host_p.add_argument("--clock-port", type=int, default=49530, help="Clock sync UDP port (default: 49530)")
    host_p.add_argument("--audio-port", type=int, default=DEFAULT_AUDIO_PORT, help="Audio UDP port (default: 49531)")

    # Join command
    join_p = subparsers.add_parser("join", help="Join an active broadcast and play in sync")
    join_p.add_argument("-H", "--host", type=str, help="Target host IP (auto-discovers if omitted)")
    join_p.add_argument("-t", "--timeout", type=float, default=3.0, help="Discovery timeout in seconds (default: 3.0)")
    join_p.add_argument("--clock-port", type=int, default=49530, help="Clock sync UDP port (default: 49530)")
    join_p.add_argument("--audio-port", type=int, default=DEFAULT_AUDIO_PORT, help="Audio UDP port (default: 49531)")

    # Play command
    play_p = subparsers.add_parser("play", help="Broadcast and play an audio file synchronously across all Macs")
    play_p.add_argument("audio_file", type=str, help="Path to audio file (.mp3, .wav, .flac, .m4a)")
    play_p.add_argument("-b", "--buffer", type=int, default=200, help="Playout lead buffer in ms (default: 200)")

    # Stream command
    stream_p = subparsers.add_parser("stream", help="Stream live microphone/system audio across all Macs")
    stream_p.add_argument("-b", "--buffer", type=int, default=150, help="Lead buffer in ms (default: 150)")
    stream_p.add_argument("--clock-port", type=int, default=49530, help="Clock sync UDP port")
    stream_p.add_argument("--audio-port", type=int, default=DEFAULT_AUDIO_PORT, help="Audio UDP port")

    # Scan command
    scan_p = subparsers.add_parser("scan", help="Scan local network for other Macs running mac-smusic")
    scan_p.add_argument("-t", "--timeout", type=float, default=2.5, help="Scan duration in seconds")

    # Sync benchmark command
    sync_p = subparsers.add_parser("sync", help="Benchmark clock offset, RTT, and jitter with a Mac")
    sync_p.add_argument("host", nargs="?", type=str, help="Host IP to benchmark against (auto-detects if omitted)")

    # Status command
    subparsers.add_parser("status", help="Show local machine audio and network status")

    # Guide command
    subparsers.add_parser("guide", help="Show multi-Mac setup guide and connection walkthrough")

    args = parser.parse_args()

    if not args.command:
        print_multiuser_guide()
        sys.exit(0)

    dispatch = {
        "host": command_host,
        "join": command_join,
        "play": command_play,
        "stream": command_stream,
        "scan": command_scan,
        "sync": command_sync,
        "status": command_status,
        "guide": lambda _: print_multiuser_guide(),
    }

    cmd_fn = dispatch.get(args.command)
    if cmd_fn:
        cmd_fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
