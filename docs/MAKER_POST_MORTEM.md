# Multi-Device Audio Streaming: Maker Post-Mortem & Research Archive

> **A forensic technical survey of how open-source developers, commercial platforms, and audio engineers built network-synchronized audio—the architectural traps they fell into, why naive implementations fail, and how modern algorithms solve clock drift.**

---

## 1. Executive Synthesis

Synchronizing digital audio playback across multiple independent physical machines over a packet-switched local network (Wi-Fi 802.11 / Ethernet 802.3) is often assumed to be a trivial socket streaming problem. In reality, it intersects three distinct branches of physics and engineering:
1. **Asynchronous Crystal Oscillators**: No two hardware DACs tick at the identical frequency.
2. **Nondeterministic Network Queuing (Wi-Fi Jitter)**: Radio frequency interference and CSMA/CA airtime contention introduce 1ms to 50ms variance.
3. **Operating System Scheduling Latency**: Kernel I/O ring buffers, audio thread preemption, and user-space context switches.

---

## 2. Platform Forensic Analysis

### A. Snapcast (`badaix/snapcast`)
* **Core Design**: Client-server architecture where the server tags PCM chunks with a monotonic timestamp indicating when the audio was captured or scheduled.
* **The Maker's Initial Mistake**:
  - The first versions of Snapcast relied on hard sample dropping when a client buffer grew too large. If client A's hardware clock ran 20 PPM slower than the server, once every few seconds the client had to discard ~10ms of audio, creating an audible "click" or popping artifact that ruined high-fidelity music listening.
* **What They Changed / Updated**:
  - **Dynamic Sample Interpolation**: Implemented subtle speed adjustment (resampling). Rather than dropping full samples, Snapcast alters the playback rate by fractional percentages (e.g. $\pm 0.02\%$), stretching or compressing the PCM frames using linear or polynomial interpolation.
  - **Monotonic Epochs**: Abandoned `gettimeofday()` wall-clock timestamps in favor of `CLOCK_MONOTONIC_RAW` to prevent time leaps when system NTP services adjust time.

---

### B. Shairport Sync (`mikebrady/shairport-sync`)
* **Core Design**: Reverse-engineered Apple AirPlay 1 and AirPlay 2 protocols to synchronize Linux/BSD/macOS machines with iOS and macOS transmitters.
* **The Maker's Initial Mistake**:
  - Relied on standard NTP (Network Time Protocol) for time synchronization. In multi-speaker arrays (where two speakers are in the same physical acoustic space), standard NTP offsets of 1–2ms produce severe comb filtering and flanging (hollow, metallic phasing sound).
* **What They Changed / Updated**:
  - **Net Quick Precision Time Protocol (NQPTP)**: Designed a specialized microsecond time protocol inspired by IEEE 1588 PTP, achieving clock skew estimation under 0.1ms.
  - **Hardware DAC Latency Calibration**: Introduced `audio_backend_latency_offset_in_seconds`. The maker discovered that different DAC chips (e.g. USB DAC vs I2S HiFiBerry vs built-in headphone jack) have differing internal DSP pipeline delays (up to 40ms difference), requiring a calibrated fixed offset setting.
  - **`soxr` Resampling**: Upgraded the rate-matching engine to use the SoX resampler library for pristine audiophile-grade drift regulation.

---

### C. ROC Toolkit (`roc-streaming/roc-toolkit`)
* **Core Design**: Real-time audio streaming over unreliable networks using RTP, Forward Error Correction (FEC), and adaptive jitter buffers.
* **The Maker's Findings**:
  - **Forward Error Correction (FEC)**: On crowded Wi-Fi networks, retransmitting lost packets via TCP creates catastrophic head-of-line blocking. ROC uses Reed-Solomon or LDPC codes to transmit repair symbols alongside raw audio packets. If 1 or 2 packets are dropped, the receiver mathematically reconstructs them without asking the sender for a retransmission.
  - **Session Clock Tracking**: Employs a Kalman filter over RTT round-trips to continuously estimate clock drift without being thrown off by transient Wi-Fi latency spikes.

---

### D. Reddit & Quora Community Post-Mortems (`r/MacOS`, `r/audiophile`, `r/macapps`)
* **The AirPlay 2-Second Buffer Trap**:
  - Hundreds of users across Reddit complain that AirPlay and Rogue Amoeba Airfoil introduce an intentional **2,000ms buffer delay**. While acceptable for casual music listening in separate rooms, it makes video synchronization, DJing, musical rehearsals, or live commentary impossible.
* **The KEXT (Kernel Extension) Extinction on macOS**:
  - Legacy macOS audio tools (Soundflower, old Jack Audio) relied on kernel extensions. With macOS Catalina, Big Sur, Monterey, Ventura, Sonoma, and Sequoia, Apple deprecated and blocked third-party KEXTs under System Integrity Protection (SIP).
  - Modern tools must use user-space CoreAudio HAL plugins, DriverKit, or native `AudioQueue` / `AVAudioEngine` APIs without requiring kernel modifications.

---

## 3. The 6 Critical Traps to Avoid in `mac-smusic`

| # | Trap | Why It Fails | `mac-smusic` Architectural Solution |
|---|---|---|---|
| **1** | **TCP Audio Transport** | Packet loss causes retransmission stall; latency cascades uncontrollably. | UDP Multicast / Unicast with sequence numbers and client-side drop tolerance. |
| **2** | **Instant Playout (Zero Buffer)** | Any 2ms Wi-Fi packet jitter starves the DAC queue, producing audio dropouts. | Calibrated target playout buffer (e.g. 150–200ms lead time) tagged to each packet. |
| **3** | **Wall-Clock Time** | NTP leaps or timezone changes throw clocks off by seconds. | High-resolution monotonic Mach absolute time (`time.monotonic_ns()`). |
| **4** | **Uncompensated DAC Drift** | Independent quartz crystals drift by 10–50 PPM, creating echo within 5 minutes. | Proportional-Integral (PI) queue depth resampler with linear PCM interpolation. |
| **5** | **Manual IP Typing** | Users dislike checking `ifconfig` or dealing with DHCP lease renewals. | ZeroConf / Bonjour mDNS beacon auto-discovery over `239.255.49.52`. |
| **6** | **Kernel Drivers / KEXTs** | Breaks on modern macOS and requires disabling SIP security. | Pure user-space CoreAudio `AudioQueue` via ctypes and native Swift Mach-O engine. |

---

## 4. Mathematical Clock Model

```
   Host Timeline   ───────────────────────────────────────► T_host
                         ▲                       │
                         │ Offset: θ             │ T_playout = T_now + BufferLead
                         │                       ▼
   Client Timeline ───────────────────────────────────────► T_client = T_host - θ
```

1. **SNTP RTT Ping-Pong**:
   $$\text{RTT} = (T_4 - T_1) - (T_3 - T_2)$$
   $$\theta = \frac{(T_2 - T_1) + (T_3 - T_4)}{2}$$
2. **Min-RTT Outlier Filter**:
   $$\theta_{\text{selected}} = \theta_i \quad \text{where } \text{RTT}_i = \min(\{\text{RTT}_{k-N \dots k}\})$$
3. **Playout Lead Mapping**:
   $$T_{\text{local\_playout}} = T_{\text{host\_playout}} - \theta_{\text{selected}}$$
4. **Drift Compensation Resampling**:
   $$\text{Ratio} = 1.0 + K_p \cdot e(t) + K_i \int e(t) \, dt$$
