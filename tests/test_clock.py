import time
import struct
import pytest
from mac_smusic.clock import ClockSyncServer, ClockSyncClient, PACKET_FORMAT, MAGIC_CLOCK, VERSION, TYPE_REQ, TYPE_RESP


def test_clock_packet_struct():
    seq = 42
    t1 = 1000000
    t2 = 1000500
    t3 = 1000600

    data = struct.pack(PACKET_FORMAT, MAGIC_CLOCK, VERSION, TYPE_REQ, b"\x00\x00", seq, t1, t2, t3)
    magic, ver, ptype, _, out_seq, out_t1, out_t2, out_t3 = struct.unpack(PACKET_FORMAT, data)

    assert magic == MAGIC_CLOCK
    assert ver == VERSION
    assert ptype == TYPE_REQ
    assert out_seq == seq
    assert out_t1 == t1
    assert out_t2 == t2
    assert out_t3 == t3


def test_clock_client_server_sync():
    server = ClockSyncServer(port=49540)
    server.start()

    client = ClockSyncClient("127.0.0.1", port=49540, window_size=5)
    try:
        res = client.sync_once()
        assert res is not None
        offset_ns, rtt_ns = res
        assert rtt_ns >= 0
        # Over loopback, RTT should be under 5ms (5,000,000 ns)
        assert rtt_ns < 10_000_000

        # Translation checks
        local_now = time.monotonic_ns()
        host_equiv = client.local_to_host_ns(local_now)
        recovered_local = client.host_to_local_ns(host_equiv)
        assert abs(recovered_local - local_now) <= 10
    finally:
        client.stop()
        server.stop()
