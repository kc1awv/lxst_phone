# LXST Phone

**Decentralized, Encrypted VoIP over Reticulum**

LXST Phone is a peer-to-peer voice calling application built on the [Reticulum Network Stack](https://reticulum.network/). It provides encrypted voice calls without requiring centralized servers, phone numbers, or accounts.

---

**N.B:** This project was created in a coding environment that includes AI tooling which provided assistance for some of the more complex features and documentation, like this README. While every effort has been made to ensure code quality and security, LXST Phone has not undergone professional security audits. Use at your own risk. Code reviews and testing by human maintainers are welcome.

Contributions to this project using AI tools are also welcome, but please ensure thorough review and testing of any changes by a human maintainer.

Basically, this is a project coded in Python with human oversight and AI assistance where requested. It is not a fully AI-generated project, and should be treated as such. No parts of the codebase are entirely AI-generated. Coding using AI tools does not negate the need for understanding Python and software development best practices.

---

## Features

- **End-to-end encrypted calls** using Reticulum's built-in encryption
- **Decentralized** - no servers, no accounts, no phone numbers
- **High-quality audio** with Opus codec (8-64 kbps) or Codec2 (0.7-3.2 kbps)
- **Automatic codec negotiation** - peers automatically agree on compatible settings
- **Ringtones** - customizable incoming and outgoing call ringtones
- **SAS verification** for manually verifying peer identity
- **Call history** tracking with statistics (encrypted at rest)
- **Contact management** with peer discovery and verification status
- **Blocklist** for unwanted callers with auto-reject
- **Rate limiting** - spam/DoS protection (3 calls/min, 10 calls/hour per peer)
- **Identity backup/export** with password encryption
- **Quality metrics** (RTT, packet loss, bitrate, jitter)
- **Connection status** indicator showing RNS network state
- **Network quality** indicator (Good/Fair/Poor)

## Requirements

- Python 3.10 or newer
- Linux, macOS, or Windows
- Audio input/output devices (microphone and speakers)
- Reticulum network access (local, radio, or internet)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/kc1awv/lxst_phone.git
cd lxst_phone
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Reticulum

LXST Phone uses your system's Reticulum configuration. If you haven't configured Reticulum yet:

```bash
# Initialize Reticulum configuration
rnsd --config <config-path>

# Edit the config file (typically ~/.reticulum/config)
# Add interfaces for your network (TCP, UDP, Radio, etc.)
```

See the [Reticulum documentation](https://reticulum.network/manual/) for detailed configuration instructions.

## Quick Start

### Running the Application

```bash
python main.py
```

On first launch, LXST Phone will:
1. Create a unique identity (your "phone number")
2. Generate configuration files in `~/.lxst_phone/`
3. Start listening for calls

### Your Node ID

Your **Node ID** (displayed in the main window) is your unique identifier on the network. Share this with others so they can call you.

### Making a Call

1. Get the Node ID from the person you want to call
2. Paste their Node ID into the "Remote node ID" field
3. Click the **Call** button
4. Wait for them to accept

### Receiving a Call

When someone calls you:
1. You'll see "Incoming call from [Node ID]"
2. Click **Accept** to answer or **Reject** to decline
3. Once accepted, audio will stream automatically

### Verifying Security

After connecting a call, verify the **SAS (Short Authentication String)** with the other person:

1. Click the **Verify Security** button during a call
2. Both parties will see a 4-digit code
3. Verbally confirm the codes match
4. Click "Codes Match" to mark the peer as verified

## Audio Device Selection

### Via Settings Panel

Audio devices can be selected through the application's Settings panel:

1. Click **Settings** tab
2. Select your **Audio Input** (microphone) from the dropdown
3. Select your **Audio Output** (speakers/headphones) from the dropdown
4. Devices are automatically saved and persist across sessions

### Via Command Line

```bash
# List available audio devices
python tools/list_audio_devices.py

# Use specific devices
python main.py --audio-input-device 2 --audio-output-device 3
```

### Disabling Audio (Testing)

```bash
# Run without audio for testing with multiple instances
python main.py --no-audio
```

## Peer Discovery

LXST Phone includes automatic peer discovery:

1. Click **Announce** to broadcast your presence
2. Other peers on the network will see your announcement
3. Click **Discovered Peers** to view the list
4. Double-click a peer to auto-fill their Node ID

**Automatic Announcements**: By default, LXST Phone announces your presence every 5 minutes. You can:
- Disable: `python main.py --no-announce`
- Change period: `python main.py --announce-period 10` (minutes)
- Set display name: `python main.py --display-name "Alice"`

## Call History

View your call history with encrypted storage:

1. Menu: **View -> Call History**
2. See recent calls with:
   - Timestamp
   - Direction (incoming/outgoing)
   - Peer ID and display name
   - Duration
   - Status (answered/missed)
3. Double-click to call a peer from history
4. Statistics panel shows total calls, duration, and more

**Privacy**: Call history is encrypted using your identity and stored securely at rest.

## Identity Management

### Exporting Your Identity

**Important**: Export your identity to prevent losing your Node ID!

1. Menu: **File -> Export Identity...**
2. Enter a strong password (minimum 8 characters)
3. Save the `.backup` file somewhere safe
4. **Keep both the file AND password secure**

### Importing an Identity

To restore your identity on a new device:

1. Menu: **File -> Import Identity...**
2. Select your `.backup` file
3. Enter the password
4. Restart the application

**Warning**: Importing replaces your current identity. Your old identity is backed up to `~/.lxst_phone/identity.backup`.

## Blocking Contacts

To block abusive or spam callers:

1. Click **Discovered Peers**
2. Select the peer to block
3. Click **Block**

Blocked peers:
- Cannot call you (calls auto-rejected with rate limiting)
- Are marked with `[BLOCKED]` in the peers list
- Can be unblocked at any time

**Rate Limiting**: All peers are rate-limited to prevent spam:
- Maximum 3 calls per minute
- Maximum 10 calls per hour
- Excess calls are automatically rejected

## Codec Selection & Network Optimization

LXST Phone supports multiple audio codecs optimized for different network conditions:

### Supported Codecs

**Opus** (Default)
- High quality, moderate bandwidth
- Bitrates: 8, 16, 24, 32, 48, 64 kbps
- Best for: Regular internet, WiFi, good cellular connections
- Sample rate: 48 kHz

**Codec2**
- Lower quality, ultra-low bandwidth
- Modes: 700, 1200, 1300, 1400, 1600, 2400, 3200 bps
- Best for: Mesh networks, satellite links, very slow connections, LoRa
- Optimized for voice intelligibility

### Automatic Codec Negotiation

**No manual configuration needed!** When two peers connect:

1. Each peer sends their preferred codec settings
2. The system automatically negotiates:
   - **Codec2 takes priority** over Opus (lower bandwidth)
   - **Lower bitrate wins** within the same codec
3. Both peers use the negotiated settings
4. Negotiated codec is shown in the UI during calls

**Examples:**
- Desktop (Opus 48 kbps) + Mobile (Opus 16 kbps) -> **Opus 16 kbps**
- Desktop (Opus 48 kbps) + Mesh node (Codec2 1600) -> **Codec2 1600 bps**
- Both using Opus 24 kbps -> **Opus 24 kbps**

### Configuring Your Codec Preference

Set your preferred codec in the **Settings** panel:

1. Click **Settings** tab
2. Under **Codec Settings**:
   - Select codec type (Opus or Codec2)
   - Choose bitrate for your network conditions
3. Settings save automatically

Your preference will be used for negotiation, but the final codec depends on both peers' capabilities.

## Ringtones

LXST Phone includes customizable ringtones for incoming and outgoing calls.

### Default Ringtones

On first startup, default ringtones are automatically copied to `~/.lxst_phone/ringtones/`:
- `incoming.wav` - Played when receiving a call
- `outgoing.wav` - Played when making a call (ring-back tone)

### Custom Ringtones

To use your own ringtones:

1. **Create or obtain WAV files**:
   - Format: WAV (PCM)
   - Sample Rate: 8000 Hz or higher (44100 Hz recommended)
   - Channels: Mono or Stereo
   - Duration: 2-5 seconds (loops automatically)

2. **Place files in ringtone directory**:
   ```bash
   cp my_ringtone.wav ~/.lxst_phone/ringtones/
   ```

3. **Update configuration** (`~/.lxst_phone/config.json`):
   ```json
   {
     "audio": {
       "ringtone_enabled": true,
       "ringtone_incoming": "my_ringtone.wav",
       "ringtone_outgoing": "my_ringtone.wav"
     }
   }
   ```

4. **Restart LXST Phone** to apply changes

### Disabling Ringtones

To disable ringtones, set `ringtone_enabled` to `false` in the config file:

```json
{
  "audio": {
    "ringtone_enabled": false
  }
}
```

## Configuration

Configuration is stored in `~/.lxst_phone/config.json`.

### Audio Settings

```json
{
  "audio": {
    "input_device": 2,              // Audio input device index (null = system default)
    "output_device": 3,             // Audio output device index
    "enabled": true,                // Enable/disable audio
    "ringtone_enabled": true,       // Enable ringtone playback
    "ringtone_incoming": "incoming.wav",  // Incoming call ringtone filename
    "ringtone_outgoing": "outgoing.wav"   // Outgoing call ringtone filename
  }
}
```

### Codec Settings

```json
{
  "codec": {
    "type": "opus",             // Codec type: "opus" or "codec2"
    "opus_bitrate": 24000,      // Opus bitrate in bps (8000-64000)
    "codec2_mode": 3200,        // Codec2 mode in bps (700-3200)
    "sample_rate": 48000,       // Audio sample rate (Hz)
    "frame_ms": 20,             // Frame duration (milliseconds)
    "channels": 1,              // Mono audio
    "opus_complexity": 10       // Opus complexity (0-10, higher = better quality)
  }
}
```

**Note**: Codec settings are auto-negotiated with peers. Your configured values are your preference.

### Network Settings

```json
{
  "network": {
    "target_jitter_ms": 60,            // Jitter buffer size (milliseconds)
    "adaptive_jitter": false,          // Adaptive jitter buffer (future)
    "announce_on_start": true,         // Send presence announcement on startup
    "announce_period_minutes": 5,      // Presence announcement period
    "max_calls_per_minute": 3,         // Rate limit: calls per minute per peer
    "max_calls_per_hour": 10           // Rate limit: calls per hour per peer
  }
}
```

### UI Settings

```json
{
  "ui": {
    "window_geometry": [620, 550],     // Window width and height
    "last_remote_id": "",              // Last called Node ID
    "display_name": "Your Name"        // Your display name for announcements
  }
}
```

## Logging

### Enabling Detailed Logs

```bash
# Set log level
python main.py --log-level DEBUG

# Custom log file location
python main.py --log-file /path/to/logfile.log

# Disable file logging (console only)
python main.py --no-log-file
```

Default log location: `~/.lxst_phone/logs/lxst_phone.log` (rotates at 10MB, keeps 5 backups)

## Troubleshooting

### No Audio

**Problem**: No audio during calls

**Solutions**:
1. Check audio devices: `python tools/list_audio_devices.py`
2. Verify device indices: `python main.py --audio-input-device X --audio-output-device Y`
3. Check system audio settings (not muted, correct default devices)
4. Look for errors in logs: `tail -f ~/.lxst_phone/logs/lxst_phone.log`

### Cannot Connect to Peer

**Problem**: Calls don't connect or fail immediately

**Solutions**:
1. Verify Reticulum is configured: `rnstatus`
2. Check peer is online (send an announcement, wait for response)
3. Ensure Node IDs are correct (they're long hex strings)
4. Check firewall settings (if using TCP/UDP interfaces)
5. Enable debug logging: `python main.py --log-level DEBUG`

### High Latency / Choppy Audio

**Problem**: Poor audio quality, delays, or dropouts

**Solutions**:
1. Check network connection quality (see connection status indicator)
2. Switch to lower bitrate codec: Settings -> Codec -> Codec2 (if both peers support it)
3. Increase jitter buffer in config: `"target_jitter_ms": 100`
4. Lower Opus complexity for less CPU: `"opus_complexity": 5`
5. Check RTT and packet loss in stats panel during call
6. Use wired network instead of WiFi if possible

### Rate Limited / Call Rejected

**Problem**: Incoming call automatically rejected

**Cause**: Rate limiting protects against spam/DoS attacks. Default limits are:
- 3 calls per minute per peer
- 10 calls per hour per peer

**Solution**: Wait for rate limit window to reset. Persistent issues may indicate:
1. Peer's clock is incorrect (causing timestamp issues)
2. Legitimate high call volume - increase limits in config
3. Adjust limits: Settings -> Network -> Max calls per minute/hour

### Identity Lost

**Problem**: Lost your identity file and don't have a backup

**Unfortunately**: Your Node ID is permanently lost. You'll need to:
1. Create a new identity: `python main.py --new-identity`
2. Share your new Node ID with contacts
3. **Export your new identity immediately**: File -> Export Identity...

## File Locations

- **Identity**: `~/.lxst_phone/identity`
- **Config**: `~/.lxst_phone/config.json`
- **Peers**: `~/.lxst_phone/peers.json` (verified/blocked status)
- **Call History**: `~/.lxst_phone/call_history.json` (encrypted)
- **Ringtones**: `~/.lxst_phone/ringtones/` (incoming.wav, outgoing.wav)
- **Logs**: `~/.lxst_phone/logs/lxst_phone.log`

On Windows, `~` is `C:\Users\YourUsername`

**Privacy Note**: Call history is encrypted using your identity. Config and peers files are stored in plaintext.

## Development

### Running Tests

```bash
# Run all tests
python -m pytest tests/

# Run with coverage
python -m pytest tests/ --cov=lxst_phone --cov-report=html
```

### Code Style

```bash
# Format code
black lxst_phone/

# Type checking
mypy lxst_phone/
```

## Security Considerations

1. **SAS Verification**: Always verify the SAS code on first call with new peers
2. **Identity Backup**: Export and encrypt your identity regularly - if lost, it cannot be recovered
3. **Blocklist**: Block abusive callers immediately
4. **Rate Limiting**: Default limits (3/min, 10/hour) protect against spam/DoS - adjust carefully
5. **Call History**: Encrypted at rest using your identity, but accessible to anyone with file system access
6. **Network**: Use secure Reticulum interfaces (avoid unencrypted public networks)
7. **Updates**: Keep Reticulum and LXST Phone updated for latest security fixes

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Submit a pull request

## License

GNU General Public License v3.0 (GPL-3.0)

## Credits

- Built on [Reticulum Network Stack](https://reticulum.network/) by Mark Qvist
- Audio codecs: [Opus](https://opus-codec.org/) and [Codec2](http://www.rowetel.com/codec2.html)
- UI: [PySide6](https://doc.qt.io/qtforpython/)

## Support

- **Issues**: https://github.com/kc1awv/lxst_phone/issues
- **Reticulum Community**: https://github.com/markqvist/Reticulum/discussions

---

**Important**: LXST Phone is experimental software. While it uses strong encryption, it has not been professionally audited. Use at your own risk.
