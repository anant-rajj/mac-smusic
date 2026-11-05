# mac-smusic 🎵 ⚡

> **Precision multi-Mac synchronized audio and music streaming CLI engine for macOS.**  
> Connect two or more Macs over Wi-Fi/LAN, lock hardware DAC playheads to microsecond accuracy, and play music or live audio in perfect sync with zero echo or phasing.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS%20Apple%20Silicon%20%7C%20Intel-lightgrey.svg)]()
[![CoreAudio: Native](https://img.shields.io/badge/CoreAudio-Zero--KEXT%20Native-success.svg)]()
[![Sync Accuracy: < 0.5ms](https://img.shields.io/badge/Sync%20Accuracy-%3C%200.5ms-cyan.svg)]()
[![Tests: 8 Passing](https://img.shields.io/badge/Tests-8%2F8%20Passing-brightgreen.svg)]()

---

## ⚡ Why mac-smusic?

Streaming audio from one Mac to another over Wi-Fi has historically been a frustrating experience:
* **AirPlay / Airfoil**: Enforces an intentional **2,000ms (2-second)** buffer delay, making live interaction or synchronized multi-speaker listening in the same room unviable.
* **AudioRelay / VBAN**: Requires manual IP configuration, clunky GUIs, and suffers from **clock drift** (the two Mac soundcards run at slightly different hardware quartz frequencies, accumulating echo or scratchy buffer clicks after 10 minutes).
* **Legacy Soundflower / Jack Audio**: Completely broken on modern macOS (Sonoma, Sequoia, Tahoe) because Apple deprecated third-party Kernel Extensions (KEXTs).

**`mac-smusic`** solves this at the systems level with zero bloat and zero kernel extensions:

| Feature | AirPlay / Airfoil | AudioRelay / VBAN | `mac-smusic` |
| :--- | :--- | :--- | :--- |
| **Playout Latency** | 2,000 ms (2 sec) | 100 – 300 ms | **35 – 150 ms** (Configurable) |
| **Sync Accuracy** | ~50 ms (Audible Phasing) | Uncompensated Drift | **< 0.5 ms (Phase-Locked)** |
| **Clock Drift Regulator** | ❌ Hard drop/stutter | ❌ Buffer overflow clicks | **✅ Adaptive PI Resampler (PPM Lock)** |
| **Discovery** | Proprietary Bonjour | ❌ Manual IP Typing | **✅ ZeroConf mDNS Auto-Discovery** |
| **Kernel Extensions** | ❌ Historical KEXT bloat | Virtual Audio Drivers | **✅ Pure User-Space CoreAudio AudioQueue** |
| **Interface** | Heavy GUI | Heavy GUI / Electron | **✅ Lightweight, Scriptable CLI** |
| **Apple Silicon M-Series** | Emulation / Overhead | Universal Binary | **✅ Native arm64 + Mach-O Swift Engine** |

---

## 🚀 How It Works (Under the Hood)

```
                  ┌───────────────────────────────────────────────┐
                  │                 HOST MAC                      │
                  │   Audio Source: MP3 / WAV / FLAC / Mic        │
                  │   Local Monotonic Timeline: T_host            │
                  └───────────────────────┬───────────────────────┘
                                          │
                        UDP Stream with Playout Timestamps
                        Continuous SNTP Sync Channel (Port 49530)
                                          │
                     ┌────────────────────┴────────────────────┐
                     ▼                                         ▼
         ┌─────────────────────────┐               ┌─────────────────────────┐
         │      RECEIVER MAC 1     │               │      RECEIVER MAC 2     │
         │ Local Timeline: T_rec1  │               │ Local Timeline: T_rec2  │
         │ Offset: -1.24 ms        │               │ Offset: +0.82 ms        │
         │ Adaptive PI Resampler   │               │ Adaptive PI Resampler   │
         │ Native CoreAudio DAC    │               │ Native CoreAudio DAC    │
         └─────────────────────────┘               └─────────────────────────┘
```

1. **Microsecond Monotonic Time Sync**: Employs Mach absolute time (`time.monotonic_ns()`) and a 16-sample sliding-window min-RTT filter over UDP port `49530` to continuously measure network jitter and clock skew without being biased by Wi-Fi queuing spikes.
2. **Scheduled Playout Timestamps**: The host tags every audio chunk with a future target playout moment (`T_play = T_host + BufferLead`).
3. **Adaptive Clock-Drift Resampler**: Follower Macs monitor hardware DAC queue depth in real time. A Proportional-Integral (PI) regulator applies subtle linear interpolation ($\pm 0.01\%$) to prevent buffer underrun clicks or latency creep.
4. **Zero-Configuration Discovery**: Automatic mDNS beacons on UDP `49532` let Macs discover each other across the room in under 1 second.

---

## 📦 Installation

### Quick Clone & Install
```bash
git clone https://github.com/anant-rajj/mac-smusic.git
cd mac-smusic
pip install -e .
make
```

Verify installation:
```bash
mac-smusic --version
mac-smusic status
```

---

## 🎮 CLI Usage Guide

### 1. Play Music Synchronized Across All Macs
On **Mac 1 (Host)**:
```bash
mac-smusic play ~/Music/favorite_song.mp3
```
*Supports `.mp3`, `.wav`, `.flac`, `.m4a`, `.aac`, and `.ogg` files.*

On **Mac 2, Mac 3, etc. (Receivers)**:
```bash
mac-smusic join
```
*That's it! The receiver automatically discovers the host via Bonjour, syncs its hardware clock, and begins playing in lockstep.*

---

### 2. Stream Live System Audio or Microphone
Stream your microphone or system sound (via BlackHole) to other Macs in real time:

On **Broadcaster Mac**:
```bash
mac-smusic stream --buffer 150
```

On **Listener Macs**:
```bash
mac-smusic join
```

---

### 3. Radar Network Scanner
Scan your local network to discover all active Macs running `mac-smusic`:
```bash
mac-smusic scan
```

Output:
```console
mac-smusic v0.1.0 // Precision Multi-Mac Synchronized Audio Engine

[📡] Scanning local subnet for active mac-smusic devices (Timeout: 2.5s)...

MACHINE NAME              IP ADDRESS         RTT          CLOCK OFFSET    PORTS
--------------------------------------------------------------------------------
Anant's MacBook Air       192.168.1.45       2.14 ms      -1.12 ms        Clock:49530 / Audio:49531
Studio M3 Max             192.168.1.82       1.08 ms      +0.45 ms        Clock:49530 / Audio:49531
--------------------------------------------------------------------------------

[✓] Found 2 active device(s). Connect with: mac-smusic join --host 192.168.1.45
```

---

### 4. Telemetry & Clock-Drift Benchmarking
Benchmark clock offset, RTT latency, jitter, and estimated hardware drift between two Macs:
```bash
mac-smusic sync 192.168.1.45
```

Output:
```console
SYNCHRONIZATION TELEMETRY REPORT
=============================================
 Target Host:       192.168.1.45
 Round-Trip (RTT):  Min: 1.42ms | Avg: 2.05ms | Max: 3.18ms
 Network Jitter:    0.28 ms
 Clock Offset:      -1.35 ms
 Estimated Drift:   0.12 PPM
 Verdict:           EXCELLENT (Standard high-speed 5GHz Wi-Fi / LAN, flawless sync)
=============================================
```

---

## 🛠️ CLI Command Reference

| Command | Description |
|---|---|
| `mac-smusic host [-f file] [-b ms]` | Start broadcaster and clock sync server |
| `mac-smusic join [-H ip] [-t timeout]` | Auto-discover and stream from host |
| `mac-smusic play <file> [-b ms]` | Play music file synchronized across all Macs |
| `mac-smusic stream [-b ms]` | Stream live microphone or BlackHole input |
| `mac-smusic scan [-t timeout]` | Scan local network for other Macs |
| `mac-smusic sync [host_ip]` | Benchmark RTT, jitter, and crystal drift PPM |
| `mac-smusic status` | Display local CoreAudio and network telemetry |

---

## 🔬 Research & Maker Post-Mortem

Detailed technical research analyzing the design of Snapcast, Shairport-Sync, ROC Toolkit, and community findings from Reddit & Quora is archived in:
* **[docs/MAKER_POST_MORTEM.md](docs/MAKER_POST_MORTEM.md)**: Forensic case studies on clock drift traps, buffer sizing, and rate modulation algorithms.
* **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**: Mathematical foundations of the SNTP filter, PI resampler, and CoreAudio buffer sizing.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.

Developed with ⚡ by **[Anant Raj](https://github.com/anant-rajj)**.
