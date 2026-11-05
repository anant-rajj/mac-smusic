import pytest
from mac_smusic.network import pack_audio_packet, unpack_audio_packet, AudioPacket


def test_audio_packet_roundtrip():
    payload = b"\x01\x00\x02\x00" * 256  # 1024 bytes of test audio
    seq = 101
    host_playout_ns = 543210987654
    channels = 2
    sample_rate = 44100

    packed = pack_audio_packet(channels, sample_rate, seq, host_playout_ns, payload)
    packet = unpack_audio_packet(packed)

    assert packet is not None
    assert packet.channels == channels
    assert packet.sample_rate == sample_rate
    assert packet.seq == seq
    assert packet.host_playout_ns == host_playout_ns
    assert packet.payload == payload


def test_audio_packet_corrupt():
    assert unpack_audio_packet(b"") is None
    assert unpack_audio_packet(b"INVALID_HEADER_DATA_TOO_SHORT") is None
    assert unpack_audio_packet(b"XXXX" + b"\x00" * 30) is None
