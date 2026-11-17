# Aurora Installer

A native macOS app for installing Aurora Linux on Apple Silicon Macs.

> **Unofficial Mac16,10 test build:** the `m4minipatches/alpha21-r3-272` branch is not an Aurora project release and is not affiliated with or endorsed by Aurora Silicon. Version `0.1.0-alpha.21.m4minipatches` is an ad-hoc-signed, unnotarized developer build for `apple,j773g` (Mac mini M4) and requires independent review before installation. Its single NixOS KDE payload carries the complete experimental Stage 2, kernel/modules/initrd, Mesa and NixOS chain. It builds the startup stub from macOS 27.2 (26B123). It is not proven on hardware: on the J773g the patched Stage 2 and kernel reached Linux on a 26.6.2 stub only; on any stub the real root mount, the desktop and HDMI have not been observed, and no clean install of this payload has booted.

Choose **Fedora Aurora Remix**, **Aurora ALARM** or **Aurora NixOS**, with **KDE Plasma**, **GNOME** or a **minimal shell** system.

The app and privileged helper use a built-in Swift engine for disk planning, partitioning, image writing, firmware extraction and Recovery setup. Installation runs without a Python runtime or a downloaded engine.

## Downloads

See [Aurora distributions](https://github.com/aurora-silicon/aurora-distributions) for current downloads, supported Macs and hardware validation. Follow the app's installation and Recovery instructions.

## Development

The app requires macOS 15+, Swift 6.2+ and XcodeBuildMCP. Build a simulation preview:

```sh
cd macOS
XCODEBUILDMCP=/path/to/xcodebuildmcp bash Packaging/build-aurora-preview.sh /absolute/output
open "/absolute/output/Aurora Installer.app" --args --simulate
```

The preview uses simulated data and does not change disks or register a helper. See [macOS development](macOS/README.md) for tests, packaging and the source layout.

An installed system boots with one picture on screen from power-on to the desktop; [flicker-free boot](https://github.com/aurora-silicon/aurora-distributions/blob/main/docs/flicker-free-boot.md) describes each boot stage, the branding a distribution or downstream configures, and how to verify it.

Standalone [speaker-tuning tools](tools/speaker-tuning/README.md) and their Python firmware library remain available for existing Linux installations.

## Credits

Aurora Installer builds on work from the Asahi Linux contributors and the Omarchy macOS installer. Attribution and import history are retained in [provenance](macOS/docs/extraction.md) and the [firmware library notes](macOS/Sources/AuroraFirmware/PROVENANCE.md).

Licensed under [MIT](LICENSE); third-party notices remain with their sources.
