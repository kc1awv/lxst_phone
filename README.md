# LXST Phone

A peer-to-peer voice calling application built on the [Reticulum Network Stack](https://reticulum.network/). Voice over Reticulum (VoR). LXST Phone provides encrypted voice calls without requiring centralized servers, phone numbers, or accounts.

---

## Features

- **End-to-end encrypted calls** using Reticulum's built-in encryption
- **Decentralized architecture** - no servers, no accounts, no phone numbers
- **High-quality audio** with Opus codec (8-64 kbps) or Codec2 (0.7-3.2 kbps)
- **Audio filters** - AGC (Automatic Gain Control) and bandpass filtering (LXST 0.4.4+)
- **Contact management** with peer discovery and verification
- **Call history** with encrypted storage
- **Security features** - SAS verification, peer blocking, and rate limiting
- **Cross-platform** - Linux, macOS, and Windows

## Requirements

- Python 3.10 or newer
- Audio input/output devices (microphone and speakers)
- Reticulum network access

## Installation

```bash
# Clone the repository
git clone https://github.com/kc1awv/lxst_phone.git
cd lxst_phone

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Basic Usage

```bash
python main.py
```

On first launch, LXST Phone will create a unique identity and configuration files in `~/.lxst_phone/`.

### Making Calls

1. Share your **Node ID** (displayed in the main window) with others
2. Get the Node ID from someone you want to call
3. Paste their Node ID into the "Remote node ID" field
4. Click **Call** and wait for them to answer

### Receiving Calls

When someone calls you, click **Accept** to answer or **Reject** to decline.

### Audio Settings

Configure audio devices in the **Settings** tab:
- Select your microphone from the input device dropdown
- Select your speakers/headphones from the output device dropdown
- Adjust AGC (Automatic Gain Control) settings for voice clarity
- Configure bandpass filters for noise reduction

### Security

Always verify the **SAS code** with new contacts:
1. Click **Verify Security** during a call
2. Both parties read their codes aloud
3. If codes match, click "Codes Match" to mark the call as verified

## Configuration

Configuration is stored in `~/.lxst_phone/config.json`. Key settings:

- **Audio devices**: Input/output device selection
- **Audio filters**: AGC target level, max gain, bandpass filters
- **Codec**: Opus or Codec2 with bitrate preferences
- **Network**: Announcement settings and rate limiting

See the configuration file for all available options.

## License

GNU General Public License v3.0 (GPL-3.0)

## Credits

- Built on [Reticulum Network Stack](https://reticulum.network/) by Mark Qvist
- Uses [LXST](https://github.com/markqvist/lxst) (Lightweight Extensible Signal Transport) library
- Audio codecs: [Opus](https://opus-codec.org/) and [Codec2](http://www.rowetel.com/codec2.html)
- UI: [PySide6](https://doc.qt.io/qtforpython/)

## Support

- **Issues**: https://github.com/kc1awv/lxst_phone/issues
- **Reticulum Community**: https://github.com/markqvist/Reticulum/discussions
