"""
Live Audio Input Capture Streamer (mac-smusic)
==============================================
Captures live audio from microphone or virtual audio loopback (BlackHole)
using macOS AudioToolbox AudioQueue input callbacks.
"""

from __future__ import annotations
import queue
import ctypes
import ctypes.util
from typing import Generator, Optional, Callable

from mac_smusic.player import AudioStreamBasicDescription, AudioQueueRef, AudioQueueBufferRef, AudioQueueBuffer

AUDIO_QUEUE_INPUT_CALLBACK = ctypes.CFUNCTYPE(
    None,
    ctypes.c_void_p,          # inUserData
    AudioQueueRef,            # inAQ
    AudioQueueBufferRef,      # inBuffer
    ctypes.c_void_p,          # inStartTime (AudioTimeStamp*)
    ctypes.c_uint32,          # inNumberPacketDescriptions
    ctypes.c_void_p,          # inPacketDescs
)


class CoreAudioCapture:
    """Captures live 16-bit 44.1kHz stereo audio from default input device or BlackHole."""

    NUM_BUFFERS = 4
    BUFFER_SIZE = 4096  # bytes (1024 frames)

    def __init__(self, sample_rate: int = 44100, channels: int = 2):
        self.sample_rate = sample_rate
        self.channels = channels
        self._lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("AudioToolbox"))
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=128)
        self._running = False
        self._audio_queue: AudioQueueRef = None
        self._buffers = []
        self._callback_ref = AUDIO_QUEUE_INPUT_CALLBACK(self._input_callback)

    def _input_callback(
        self,
        in_user_data: ctypes.c_void_p,
        in_aq: AudioQueueRef,
        in_buffer: AudioQueueBufferRef,
        in_start_time: ctypes.c_void_p,
        in_num_packets: ctypes.c_uint32,
        in_packet_descs: ctypes.c_void_p,
    ) -> None:
        if not self._running:
            return

        buf_obj = in_buffer.contents
        byte_size = buf_obj.mAudioDataByteSize
        if byte_size > 0:
            data = ctypes.string_at(buf_obj.mAudioData, byte_size)
            try:
                self._queue.put_nowait(data)
            except queue.Full:
                pass

        self._lib.AudioQueueEnqueueBuffer(self._audio_queue, in_buffer, 0, None)

    def start(self) -> None:
        """Initializes and starts CoreAudio input stream."""
        if self._running:
            return

        desc = AudioStreamBasicDescription()
        desc.mSampleRate = float(self.sample_rate)
        desc.mFormatID = int.from_bytes(b"lpcm", "big")
        desc.mFormatFlags = 0xC
        desc.mBytesPerPacket = self.channels * 2
        desc.mFramesPerPacket = 1
        desc.mBytesPerFrame = self.channels * 2
        desc.mChannelsPerFrame = self.channels
        desc.mBitsPerChannel = 16
        desc.mReserved = 0

        self._audio_queue = AudioQueueRef()
        status = self._lib.AudioQueueNewInput(
            ctypes.byref(desc),
            self._callback_ref,
            None,
            None,
            None,
            0,
            ctypes.byref(self._audio_queue),
        )
        if status != 0:
            raise RuntimeError(f"AudioQueueNewInput failed with status: {status}")

        for _ in range(self.NUM_BUFFERS):
            buf = AudioQueueBufferRef()
            status = self._lib.AudioQueueAllocateBuffer(
                self._audio_queue,
                self.BUFFER_SIZE,
                ctypes.byref(buf),
            )
            if status != 0:
                raise RuntimeError(f"AudioQueueAllocateBuffer failed: {status}")
            self._buffers.append(buf)
            self._lib.AudioQueueEnqueueBuffer(self._audio_queue, buf, 0, None)

        self._running = True
        self._lib.AudioQueueStart(self._audio_queue, None)

    def read_chunk(self, timeout_sec: float = 0.1) -> Optional[bytes]:
        """Reads the next available live PCM chunk."""
        try:
            return self._queue.get(timeout=timeout_sec)
        except queue.Empty:
            return None

    def stop(self) -> None:
        """Stops live capture stream and releases resources."""
        self._running = False
        if self._audio_queue:
            self._lib.AudioQueueStop(self._audio_queue, True)
            self._lib.AudioQueueDispose(self._audio_queue, True)
            self._audio_queue = None
            self._buffers.clear()
