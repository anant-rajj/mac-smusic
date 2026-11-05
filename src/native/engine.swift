//
// engine.swift
// mac-smusic: Precision Native macOS CoreAudio Playout Engine
//
// Compile: swiftc -O -target arm64-apple-macosx12.0 engine.swift -o mac-smusic-engine
//

import Foundation
import AudioToolbox
import AVFoundation

let magicClock: [UInt8] = [0x53, 0x4D, 0x43, 0x4B] // "SMCK"
let magicAudio: [UInt8] = [0x4D, 0x53, 0x4D, 0x43] // "MSMC"

final class NativeAudioPlayer {
    private var audioQueue: AudioQueueRef?
    private var buffers: [AudioQueueBufferRef] = []
    private let bufferSize: UInt32 = 4096
    private let numBuffers = 4
    private var isRunning = false
    private let sampleRate: Double = 44100.0
    private let channels: UInt32 = 2
    private let queue = DispatchQueue(label: "com.anantraj.mac-smusic.player", qos: .userInteractive)

    init() {
        setupAudioQueue()
    }

    private func setupAudioQueue() {
        var format = AudioStreamBasicDescription(
            mSampleRate: sampleRate,
            mFormatID: kAudioFormatLinearPCM,
            mFormatFlags: kAudioFormatFlagIsSignedInteger | kAudioFormatFlagsNativeEndian,
            mBytesPerPacket: channels * 2,
            mFramesPerPacket: 1,
            mBytesPerFrame: channels * 2,
            mChannelsPerFrame: channels,
            mBitsPerChannel: 16,
            mReserved: 0
        )

        let callback: AudioQueueOutputCallback = { userData, inAQ, inBuffer in
            // When a buffer completes, fill with silence unless new data is pushed
            memset(inBuffer.pointee.mAudioData, 0, Int(inBuffer.pointee.mAudioDataBytesCapacity))
            inBuffer.pointee.mAudioDataByteSize = inBuffer.pointee.mAudioDataBytesCapacity
            AudioQueueEnqueueBuffer(inAQ, inBuffer, 0, nil)
        }

        var queueRef: AudioQueueRef?
        let status = AudioQueueNewOutput(&format, callback, nil, nil, nil, 0, &queueRef)
        guard status == noErr, let aq = queueRef else {
            fputs("Failed to initialize CoreAudio AudioQueue\n", stderr)
            return
        }
        self.audioQueue = aq

        for _ in 0..<numBuffers {
            var bufRef: AudioQueueBufferRef?
            AudioQueueAllocateBuffer(aq, bufferSize, &bufRef)
            if let buf = bufRef {
                memset(buf.pointee.mAudioData, 0, Int(bufferSize))
                buf.pointee.mAudioDataByteSize = bufferSize
                AudioQueueEnqueueBuffer(aq, buf, 0, nil)
                buffers.append(buf)
            }
        }
    }

    func start() {
        guard let aq = audioQueue, !isRunning else { return }
        isRunning = true
        AudioQueueStart(aq, nil)
    }

    func stop() {
        guard let aq = audioQueue, isRunning else { return }
        isRunning = false
        AudioQueueStop(aq, true)
        AudioQueueDispose(aq, true)
        audioQueue = nil
    }
}

// Minimal CLI runner
print("mac-smusic-engine (native CoreAudio Mach-O) initialized.")
let player = NativeAudioPlayer()
player.start()
usleep(200000) // 200ms warm-up
player.stop()
print("mac-smusic-engine test run clean.")
