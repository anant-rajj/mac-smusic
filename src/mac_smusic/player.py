"""
Low-Latency Hardware Audio Player (mac-smusic)
==============================================
Direct CoreAudio hardware output driver using macOS AudioToolbox AudioQueue
and ctypes, ensuring zero third-party dependencies on Apple Silicon & Intel.
"""

from __future__ import annotations
import time
import queue
import ctypes
import ctypes.util
import threading
from typing import Optional, List

# CoreAudio Type Definitions
AudioQueueRef = ctypes.c_void_p


class AudioStreamBasicDescription(ctypes.Structure):
    _fields_ = [
        ("mSampleRate", ctypes.c_double),
        ("mFormatID", ctypes.c_uint32),
        ("mFormatFlags", ctypes.c_uint32),
        ("mBytesPerPacket", ctypes.c_uint32),
        ("mFramesPerPacket", ctypes.c_uint32),
        ("mBytesPerFrame", ctypes.c_uint32),
        ("mChannelsPerFrame", ctypes.c_uint32),
        ("mBitsPerChannel", ctypes.c_uint32),
        ("mReserved", ctypes.c_uint32),
    ]


class AudioQueueBuffer(ctypes.Structure):
    pass


AudioQueueBufferRef = ctypes.POINTER(AudioQueueBuffer)

AudioQueueBuffer._fields_ = [
    ("mAudioDataBytesCapacity", ctypes.c_uint32),
    ("mAudioData", ctypes.c_void_p),
    ("mAudioDataByteSize", ctypes.c_uint32),
    ("mUserData", ctypes.c_void_p),
    ("mPacketDescriptionCapacity", ctypes.c_uint32),
    ("mPacketDescriptions", ctypes.c_void_p),
    ("mPacketDescriptionCount", ctypes.c_uint32),
]

AUDIO_QUEUE_OUTPUT_CALLBACK = ctypes.CFUNCTYPE(
    None,
    ctypes.c_void_p,          # inUserData
    AudioQueueRef,            # inAQ
    AudioQueueBufferRef,      # inBuffer
)


class CoreAudioPlayer:
    """
    Direct macOS CoreAudio hardware player using ctypes & AudioQueue.
    Buffers audio chunks and feeds them in lockstep to the hardware DAC.
    """

    NUM_BUFFERS = 4
    BUFFER_SIZE = 4096  # bytes (1024 frames @ 16-bit stereo)

    def __init__(self, sample_rate: int = 44100, channels: int = 2):
        self.sample_rate = sample_rate
        self.channels = channels
        self._lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("AudioToolbox"))
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=128)
        self._running = False
        self._audio_queue: AudioQueueRef = None
        self._buffers: List[AudioQueueBufferRef] = []
        self._callback_ref = AUDIO_QUEUE_OUTPUT_CALLBACK(self._audio_callback)

        self._setup_coreaudio()

    def _setup_coreaudio(self) -> None:
        desc = AudioStreamBasicDescription()
        desc.mSampleRate = float(self.sample_rate)
        desc.mFormatID = int.from_bytes(b"lpcm", "big")
        # kAudioFormatFlagIsSignedInteger (4) | kAudioFormatFlagsNativeEndian (2)
        desc.mFormatFlags = 0xC
        desc.mBytesPerPacket = self.channels * 2
        desc.mFramesPerPacket = 1
        desc.mBytesPerFrame = self.channels * 2
        desc.mChannelsPerFrame = self.channels
        desc.mBitsPerChannel = 16
        desc.mReserved = 0

        self._audio_queue = AudioQueueRef()
        status = self._lib.AudioQueueNewOutput(
            ctypes.byref(desc),
            self._callback_ref,
            None,
            None,
            None,
            0,
            ctypes.byref(self._audio_queue),
        )
        if status != 0:
            raise RuntimeError(f"AudioQueueNewOutput failed with status: {status}")

        for _ in range(self.NUM_BUFFERS):
            buf = AudioQueueBufferRef()
            status = self._lib.AudioQueueAllocateBuffer(
                self._audio_queue,
                self.BUFFER_SIZE,
                ctypes.byref(buf),
            )
            if status != 0:
                raise RuntimeError(f"AudioQueueAllocateBuffer failed with status: {status}")
            self._buffers.append(buf)

    def _audio_callback(self, in_user_data: ctypes.c_void_p, in_aq: AudioQueueRef, in_buffer: AudioQueueBufferRef) -> None:
        """Invoked by CoreAudio when a hardware buffer empties."""
        if not self._running:
            return

        try:
            chunk = self._queue.get_nowait()
        except queue.Empty:
            chunk = b"\x00" * self.BUFFER_SIZE

        buf_obj = in_buffer.contents
        copy_size = min(len(chunk), buf_obj.mAudioDataBytesCapacity)
        ctypes.memmove(buf_obj.mAudioData, chunk, copy_size)
        buf_obj.mAudioDataByteSize = copy_size

        self._lib.AudioQueueEnqueueBuffer(self._audio_queue, in_buffer, 0, None)

    def start(self) -> None:
        """Starts hardware playback stream."""
        if self._running:
            return
        self._running = True

        # Prime the buffers with silence or initial audio
        for buf in self._buffers:
            try:
                chunk = self._queue.get_nowait()
            except queue.Empty:
                chunk = b"\x00" * self.BUFFER_SIZE

            buf_obj = buf.contents
            copy_size = min(len(chunk), buf_obj.mAudioDataBytesCapacity)
            ctypes.memmove(buf_obj.mAudioData, chunk, copy_size)
            buf_obj.mAudioDataByteSize = copy_size
            self._lib.AudioQueueEnqueueBuffer(self._audio_queue, buf, 0, None)

        self._lib.AudioQueueStart(self._audio_queue, None)

    def push_pcm(self, pcm_bytes: bytes) -> None:
        """Pushes PCM bytes into the hardware output queue."""
        if not self._running:
            self.start()

        offset = 0
        while offset < len(pcm_bytes):
            chunk = pcm_bytes[offset : offset + self.BUFFER_SIZE]
            offset += len(chunk)
            if len(chunk) < self.BUFFER_SIZE:
                chunk = chunk + b"\x00" * (self.BUFFER_SIZE - len(chunk))
            try:
                self._queue.put(chunk, timeout=0.1)
            except queue.Full:
                # Drop oldest on severe backpressure to prevent unbounded latency
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                self._queue.put(chunk)

    def stop(self) -> None:
        """Stops hardware playback stream and releases CoreAudio buffers."""
        self._running = False
        if self._audio_queue:
            self._lib.AudioQueueStop(self._audio_queue, True)
            self._lib.AudioQueueDispose(self._audio_queue, True)
            self._audio_queue = None
            self._buffers.clear()
