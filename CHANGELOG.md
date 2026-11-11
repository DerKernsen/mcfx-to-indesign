# Changelog

## 0.2.0

- Add a desktop interface for selecting a saved MCFX project and a new output
  folder, displaying progress, and opening the completed output.
- Publish a standalone Windows x64 GUI build with bundled license notices and
  a SHA-256 checksum. Python is not required to run the Windows executable.
- Keep the command-line interface and add a reusable `convert()` function.
- Add synthetic tests for GUI input validation, progress and error handling.

The converter remains experimental. InDesign is required to run the generated
script and create editable documents. See the README for the supported layout
and features that are not converted.

## 0.1.0

- Initial command-line converter, reduced-size preview PDF and generated
  InDesign script for the supported image-based MCFX layout.
