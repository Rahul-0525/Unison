# 🎵 Unison

> **Sub-millisecond synchronized multi-device audio streaming, dynamic synced lyrics, and ambient visualizer over your local network.**  
> *Built 100% via **Vibe Coding** with Google DeepMind's **Antigravity** AI assistant.*

---

## ⚡ The Story & Purpose: AI Vibe Coding in Action

This project was built from scratch purely through **vibe coding** in pair-programming with **Antigravity**.

The core mission behind Unison is to explore and demonstrate the power of AI-assisted engineering:
- **Learning to build complete full-stack applications with AI**: Moving beyond trivial prototypes to real-time distributed systems handling network clock synchronization, audio scheduling, canvas physics, and cross-platform responsive UX.
- **Shipping working software exponentially faster**: Iterating rapidly on complex engineering challenges—from Web Audio drift correction and mobile touch event optimizations to organic audio reactive visualizers and zero-latency sound feedback—without sacrificing velocity or code quality.
- **Proving the vibe-coding paradigm**: Demonstrating that natural language intent combined with agentic reasoning can produce production-grade, highly polished, tactile software in record time.

---

## ✨ Features

- 🔊 **Sub-Millisecond Multi-Device Sync**:
  - Plays the exact same audio stream simultaneously across any number of devices on your Wi-Fi/LAN (smartphones, PCs, laptops, tablets, speakers).
  - Uses an NTP-style continuous clock synchronization protocol over WebSockets.
  - Leverages the Web Audio API (`AudioContext`, `AudioBufferSourceNode`) with sample-accurate scheduled playback and dynamic drift compensation.
- 🌊 **Aurora Visualizer & iOS Ambient Lighting Mode**:
  - **Apple iOS-Style Toggle**: Smooth spring-animated toggle switch seamlessly switches between two visual experiences.
  - **Full Visualizer Mode**: 60 FPS multi-band audio visualizer analyzing FFT frequency data with smoothed non-linear dynamics that eliminate jarring spikes or sudden drops.
  - **Ambient Lighting Mode**: Soft, breathing aura dynamically derived from the song's album art palette that gently pulses with sub-bass frequencies without distracting movement.
  - Floating ambient particle physics active across both modes.
- 🎧 **Zero-Latency Tactile Immersion Audio**:
  - Preloaded Web Audio sound effects triggered instantly on user interaction:
    - `main_play.mp3`: Fires immediately on Play/Pause toggle and search result playback.
    - `loading_sound.mp3`: Loops during song download, extraction, and multi-device pre-buffering.
    - `search_sidebar_opening.mp3`: Plays smoothly when opening the search drawer.
    - `buttons.mp3`: Balanced tactile audio feedback when switching tabs (Lyrics, Playing, Devices, Search).
- 🔍 **Integrated YouTube Search & Streaming**:
  - Search any song directly from the client interface.
  - Automatically fetches audio streams using `yt-dlp` and caches them locally for instant replay.
- 📁 **Local Audio File Uploads**:
  - Broadcast your own offline audio library (`.mp3`, `.m4a`, `.flac`, `.wav`, `.ogg`, `.opus`, `.webm`) to all connected devices.
- 🎤 **Synchronized Real-Time Lyrics**:
  - Automatically fetches synchronized LRC lyrics from LRCLIB.
  - Responsive karaoke-style view with smooth continuous auto-scrolling and active line highlighting.
  - Mobile-optimized reading mode that centers lyrics on-screen without interface clutter.
- 📱 **Tactile Glassmorphic Design**:
  - Sleek, modern interface inspired by tactile hardware with spring-press button mechanics.
  - Responsive design engineered to look and feel native on desktop monitors and mobile touchscreens alike.
- 📲 **Frictionless Onboarding & QR Code Pairing**:
  - Clear, beginner-friendly instructions on the landing page for guests with no networking experience.
  - Dynamic QR code displayed in the navigation bar. Any guest on the same Wi-Fi can scan and join the session in seconds—no app installs or logins needed.
- 📊 **Real-Time Network & Drift Diagnostics**:
  - Live device manager tracking round-trip time (RTT), audio output latency, download progress, and clock sync offset for every connected device.

---

## 🧠 How It Works (Architecture)

```
                       +-------------------+
                       |    server.py      |
                       |  (Python/aiohttp) |
                       +---------+---------+
                                 |
                 +---------------+---------------+
                 |                               |
                 v                               v
         [ HTTP Endpoints ]             [ WebSockets Hub ]
         - Static UI serving            - NTP-style Clock Sync (RTT/offset)
         - Audio streaming / Range      - Play/Pause/Seek broadcasts
         - yt-dlp search & cache        - Device state & drift metrics
         - File upload endpoint         - Host privilege validation
         - Preloaded UI sounds          - Coordinated scheduled playback
                 |                               |
                 +---------------+---------------+
                                 |
                   +-------------+-------------+
                   |                           |
                   v                           v
          [ Host Device (PC) ]       [ Guest Devices (Mobiles) ]
          - AudioBuffer prefetch     - AudioBuffer prefetch
          - Scheduled AudioContext   - Scheduled AudioContext
          - Aurora / Ambient Visual  - Centered Synced Lyrics
          - Full playback controls   - Mute / Listen mode
          - Haptic sound feedback    - Tactile sound feedback
```

### 1. Clock Synchronization & Drift Correction
Audio synchronization over heterogeneous Wi-Fi networks requires sub-millisecond precision:
- Unison periodically exchanges timestamped ping/pong messages over WebSockets to calculate each client's **Round Trip Time (RTT)** and clock offset relative to the host.
- When the host triggers playback, a coordinated future start time (`at = now_ms() + LEAD_MS`) is broadcast to all devices.
- Each client schedules playback via `AudioBufferSourceNode.start(scheduledTime)`.
- If a device experiences clock drift or drops audio frames, non-destructive time realignment smoothly re-locks the audio to within ±10–15 milliseconds.

### 2. Audio Processing & Canvas Visualizer
- The Web Audio API `AnalyserNode` extracts real-time frequency data across sub-bass, mid-range, and treble bins.
- The **Aurora visualizer** calculates dynamic volume using a smoothed non-linear curve, mapping frequency response between subtle ambient glows and full-screen reactive waves while eliminating distracting spikes.
- When toggled to **Ambient Mode**, the canvas restricts high-frequency jumps, maintaining a soothing, breathing colored glow synchronized with low-end beats and the album artwork palette.

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.9+** installed
- **ffmpeg** installed and available in your system `PATH` (required by `yt-dlp` for audio extraction)

### 1. Clone the Repository
```bash
git clone https://github.com/<your-username>/unison.git
cd unison
```

### 2. Set Up Virtual Environment & Dependencies
```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (CMD):
.venv\Scripts\activate.bat
# Linux / macOS:
source .venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 3. Run the Server
```bash
python server.py
```

By default, the server listens on port **8765** (`0.0.0.0:8765`).

### 4. Connect Your Devices
- **Host (Master PC)**: Open `http://localhost:8765` in your browser.
- **Guest Devices (Smartphones, Tablets, Laptops)**:
  1. Make sure the device is connected to the **same Wi-Fi / Local Network**.
  2. Scan the **QR code** in the top navigation bar, or enter `http://<YOUR_LOCAL_IP>:8765`.
  3. Enter a friendly device name and tap anywhere on the screen to enable audio output (mobile browsers require one tap to unlock audio permissions).

---

## 📂 Project Structure

```
unison/
├── index.html        # Single-page client: Web Audio engine, Canvas visualizer, glassmorphism UI
├── server.py         # Async Python server: WebSocket hub, room coordinator, audio cache, NTP time sync
├── resources/        # Preloaded tactile immersion sound effects (.mp3)
│   ├── buttons.mp3
│   ├── loading_sound.mp3
│   ├── main_play.mp3
│   └── search_sidebar_opening.mp3
├── requirements.txt  # Python package dependencies (aiohttp, yt-dlp, qrcode)
├── .gitignore        # Clean ignore rules (excludes .venv/, desktop app/, caches, media)
├── LICENSE           # MIT License
└── README.md         # Project documentation and guide
```

> **Note**: Build directories (`desktop app/`, `cache/`, `uploads/`, and virtual environments `.venv/`) are intentionally excluded via `.gitignore` to keep the core repository clean and lightweight.

---

## 🛠️ Configuration Options

You can customize the server behavior using command-line arguments or environment variables:

| Option / Variable | Default | Description |
|---|---|---|
| `--port` / `PORT` | `8765` | Network port for the web and WebSocket server |
| `--host` | `0.0.0.0` | Host IP interface to bind to |
| `UNISON_HOST_KEY` | *auto-generated* | Secret authentication key granting host/playback controls |
| `UNISON_OPEN_HOST` | `false` | If set to `1` or `true`, any connected device can control playback |
| `UNISON_FORMAT` | `bestaudio/best` | yt-dlp format selection string for audio extraction |
| `UNISON_COOKIES_FROM` | *None* | Browser to extract cookies from if YouTube requires authentication (e.g. `chrome`, `firefox`) |

---

## 💡 Lessons from Vibe Coding

Building Unison with Antigravity highlighted several core principles for successful AI-aided development:
1. **Iterative Problem Solving**: Tackling features in modular chunks (first network sync, then Web Audio scheduling, followed by visualizer curves, haptic audio cues, and mobile ergonomics) leads to robust results.
2. **Immediate Verification**: Testing interactive behavior (audio clock drift, touch scrolling, responsiveness, latency) at every step ensures the application feels right in real-world use.
3. **Preserving Intent**: Communicating high-level aesthetic and functional vibes while allowing the AI assistant to handle intricate mathematical mappings, binary packaging, and cross-browser quirks.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE). Feel free to use, modify, and distribute it for personal or educational projects!
