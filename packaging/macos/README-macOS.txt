SelfStem for macOS
==================

Install:

1. Open the SelfStem DMG.
2. Drag SelfStem.app to Applications.
3. Open SelfStem from Applications.

First launch:

- SelfStem is a thin native app. It downloads a pinned, checksummed SelfStem
  runtime pack on first launch.
- The runtime installs to:
  ~/Library/Application Support/SelfStem/runtime
- FFmpeg and ffprobe install to:
  ~/Library/Application Support/SelfStem/ffmpeg
- Demucs model weights download on first use and are cached under:
  ~/Library/Application Support/SelfStem/models

Uninstall:

1. Delete /Applications/SelfStem.app.
2. To remove runtime files, jobs, caches, models, and logs, delete:
   ~/Library/Application Support/SelfStem

Notes:

- Internet access is required for first-run setup.
- Public releases should be signed and notarized.
- Unsigned local builds are for development and internal testing only.
