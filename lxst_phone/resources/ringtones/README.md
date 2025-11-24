# Default Ringtones

This directory contains the default ringtones for LXST Phone.

## Files

- `incoming.wav` - Ringtone played when receiving a call
- `outgoing.wav` - Ringtone played when making a call (ring-back tone)

## Format Requirements

Ringtone files should be:
- **Format**: WAV (PCM)
- **Sample Rate**: 8000 Hz or higher (44100 Hz recommended)
- **Channels**: Mono or Stereo
- **Duration**: 2-5 seconds (will loop automatically)

## Custom Ringtones

To use custom ringtones:

1. Place your WAV files in `~/.lxst_phone/ringtones/`
2. Update the config file (`~/.lxst_phone/config.json`):
   ```json
   {
     "audio": {
       "ringtone_incoming": "my_incoming.wav",
       "ringtone_outgoing": "my_outgoing.wav",
       "ringtone_enabled": true
     }
   }
   ```

## Creating Your Own

You can create custom ringtones using:
- Audacity (free, open-source)
- Any audio editor that exports WAV files
- Online tone generators

Keep files small (< 1 MB) for quick loading.
