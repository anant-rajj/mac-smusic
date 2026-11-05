"""
Universal Audio File Decoder (mac-smusic)
=========================================
Decodes MP3, FLAC, M4A, AAC, WAV, and OGG files into uniform
16-bit signed stereo PCM chunks (44.1 kHz) using PyAV or native macOS afconvert.
"""

from __future__ import annotations
import os
import wave
import struct
import subprocess
import tempfile
from typing import Generator, Tuple, Optional

SAMPLE_RATE = 44100
CHANNELS = 2
BYTES_PER_SAMPLE = 2  # 16-bit
BYTES_PER_FRAME = CHANNELS * BYTES_PER_SAMPLE  # 4 bytes per stereo frame
DEFAULT_CHUNK_FRAMES = 1024  # ~23.2ms per chunk


def decode_audio_file(
    file_path: str,
    target_sample_rate: int = SAMPLE_RATE,
    chunk_frames: int = DEFAULT_CHUNK_FRAMES,
) -> Generator[bytes, None, None]:
    """
    Decodes audio file into a stream of 16-bit signed stereo PCM chunks.
    Yields chunks of size `chunk_frames * 4` bytes.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    # 1. Try PyAV first (instant in-memory C decoding)
    try:
        import av
        container = av.open(file_path)
        audio_stream = next((s for s in container.streams if s.type == "audio"), None)
        if audio_stream:
            resampler = av.AudioResampler(
                format="s16",
                layout="stereo",
                rate=target_sample_rate,
            )

            buffer = bytearray()
            chunk_bytes = chunk_frames * BYTES_PER_FRAME

            for frame in container.decode(audio_stream):
                resampled_frames = resampler.resample(frame)
                for r_frame in resampled_frames:
                    buffer.extend(r_frame.to_ndarray().tobytes())
                    while len(buffer) >= chunk_bytes:
                        yield bytes(buffer[:chunk_bytes])
                        del buffer[:chunk_bytes]

            if buffer:
                # Pad final chunk to chunk_bytes with silence
                padding = chunk_bytes - len(buffer)
                buffer.extend(b"\x00" * padding)
                yield bytes(buffer)
            return
    except Exception:
        pass

    # 2. Try native macOS afconvert tool (built into all macOS versions)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
        tmp_wav_path = tmp_wav.name

    try:
        cmd = [
            "afconvert",
            "-f", "WAVE",
            "-d", f"LEI16@{target_sample_rate}",
            "-c", str(CHANNELS),
            file_path,
            tmp_wav_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and os.path.exists(tmp_wav_path):
            with wave.open(tmp_wav_path, "rb") as wf:
                chunk_bytes = chunk_frames * BYTES_PER_FRAME
                while True:
                    data = wf.readframes(chunk_frames)
                    if not data:
                        break
                    if len(data) < chunk_bytes:
                        data += b"\x00" * (chunk_bytes - len(data))
                    yield data
            return
    finally:
        if os.path.exists(tmp_wav_path):
            try:
                os.remove(tmp_wav_path)
            except OSError:
                pass

    raise RuntimeError(f"Unable to decode audio format for file: {file_path}")
