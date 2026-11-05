import time
import pytest
from mac_smusic.discovery import HostBeacon, NetworkScanner, MAGIC_BEACON


def test_discovery_beacon_and_scan():
    beacon = HostBeacon(machine_name="Test-MacBook", clock_port=49541, audio_port=49542)
    beacon.start(interval_sec=0.1)

    scanner = NetworkScanner()
    try:
        host = scanner.find_first_host(timeout_sec=3.0)
        assert host is not None
        assert host["name"] == "Test-MacBook"
        assert host["clock_port"] == 49541
        assert host["audio_port"] == 49542
    finally:
        scanner.close()
        beacon.stop()
