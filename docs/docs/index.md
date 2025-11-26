# LXST Phone Documentation

**Decentralized, Encrypted Voice over Reticulum (VoR)**

Welcome to the official documentation for LXST Phone, a peer-to-peer voice calling application built on the [Reticulum Network Stack](https://reticulum.network/). This project demonstrates how modern VoIP concepts can be adapted to operate over delay-tolerant, mesh-based networks without centralized infrastructure.

---

!!! warning "Prototype Status"
    LXST Phone is a proof-of-concept implementation created using IDEs that include AI assistance. While every effort has been made to ensure code quality and security, this project has not undergone professional security audits. **Use at your own risk.**

---

## What is LXST Phone?

LXST Phone provides encrypted voice calls without requiring centralized servers, phone numbers, or accounts. It operates entirely peer-to-peer using cryptographic identities over the Reticulum Network Stack.

### Key Features

- **End-to-end encrypted calls** using Reticulum's built-in encryption
- **Decentralized architecture** - no servers, no accounts, no phone numbers
- **High-quality audio** with Opus codec (8-64 kbps) or Codec2 (0.7-3.2 kbps)
- **Automatic codec negotiation** between peers
- **Peer discovery** via network announces
- **Call history** tracking with encrypted storage
- **Contact management** with verification status
- **Security features** including SAS verification, blocklists, and rate limiting
- **Real-time quality metrics** (RTT, packet loss, bitrate, jitter)

## Technology Stack

| Component | Technology |
|-----------|-----------|
| **Networking** | Reticulum Network Stack (RNS) |
| **GUI Framework** | PySide6 (Qt for Python) |
| **Audio Codecs** | Opus (opuslib), Codec2 (pycodec2) |
| **Audio I/O** | sounddevice (PortAudio) |
| **Language** | Python 3.10+ |

## Documentation Structure

This documentation is organized to guide you through both using and understanding LXST Phone:

### Getting Started

- **[Quick Reference](quick_reference.md)** - Developer guide with key components, paths, and workflows

### Core Documentation

- **[Program Startup](program_startup.md)** - Application initialization, identity loading, and configuration
- **[Announces](announces.md)** - Peer discovery mechanism and announce protocol
- **[Signaling](signaling.md)** - Call state machine, message handling, and codec negotiation
- **[Call Management](call_management.md)** - Call lifecycle, state transitions, and error handling
- **[Security](security.md)** - Encryption, verification, blocklists, and anti-abuse measures
- **[Architecture](architecture.md)** - Comprehensive system design and implementation details

## Quick Installation

```bash
# Clone the repository
git clone https://github.com/kc1awv/lxst_phone.git
cd lxst_phone

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

## Requirements

- Python 3.10 or newer
- Linux, macOS, or Windows
- Audio input/output devices (microphone and speakers)
- Reticulum network access (local, radio, or internet)

## Project Resources

- **GitHub Repository**: [kc1awv/lxst_phone](https://github.com/kc1awv/lxst_phone)
- **Reticulum Network**: [reticulum.network](https://reticulum.network/)
- **Issue Tracker**: [GitHub Issues](https://github.com/kc1awv/lxst_phone/issues)

## Contributing

Contributions are welcome! Whether you're fixing bugs, adding features, or improving documentation, please ensure:

- Thorough testing of any changes
- Code reviews by human maintainers
- Following Python best practices
- Understanding of the Reticulum Network Stack

Contributions using AI tools are accepted, but must be fully reviewed and tested by humans before submission.

## License

See the [LICENSE](https://github.com/kc1awv/lxst_phone/blob/main/LICENSE) file in the repository for license information.

---

*Ready to dive deeper? Start with the [Quick Reference](quick_reference.md) for a developer overview, or jump into the [Architecture](architecture.md) guide for comprehensive system design details.*
