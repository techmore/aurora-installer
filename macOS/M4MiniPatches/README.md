# Mac16,10 test release inputs (r3, macOS 27.2 stub)

These tools build the unofficial `0.1.0-alpha.21.m4minipatches` developer
package. It admits only `apple,j773g` and offers one profile, Aurora NixOS KDE.
This private test build is not an Aurora project release, is not affiliated
with or endorsed by Aurora Silicon, and is not signed by the Aurora project.
The app bundle includes the upstream MIT license as `Aurora-Installer.LICENSE`
and the exact source commit as `Aurora-Installer.source-revision`.

It is **not proven on hardware**. On the J773g, the patched Stage 2 and kernel A
reached Linux on a 26.6.2 (25G83) stub; the real root mount, the desktop and
HDMI have not been observed.

The installer now builds the J773g startup stub from macOS 27.2 (26B123), the
pinned production firmware (`scripts/firmware-qualification.json`, J773g as an
experimental T8132 board). A Stage 2 and kernel built for that firmware are
passed by digest: `check-j773g-payload.py --stage2-sha256`,
`make-release-inputs.py --stage2-sha256 --evidence-revision`, and
`M4MINIPATCHES_STAGE2_SHA256` for `build-app.sh`. All three must name the same
bytes. Stage 2 B (`33ce5198…`) remains the default only for the 26.6.2 record.

## Build order

Each step refuses to run on the output of a failed earlier step.

1. Build the NixOS payload ZIP whose kernel, module tree, initrd and system
   closure all come from one kernel A release, with the patched Stage 2 under
   both `esp/m1n1/boot-j773g.bin` and `esp/m1n1/boot-ctxr-j773g.bin`.
2. Gate it (Linux host with e2fsprogs, btrfs-progs and zstd):

   ```sh
   macOS/M4MiniPatches/check-j773g-payload.py nixos-kde-build-43451965403.zip \
     --stage2-sha256 33ce5198c58766fb87e18f817a8f1f55d2141b2fcf619c8bf5c157470205a3c4 \
     --metadata installer-data-nixos-kde.json --receipt PAYLOAD-GATE.json
   ```

   The gate fails unless the member the installer copies to ESP
   `m1n1/boot-ctxr.bin` (the file Stage 1 loads on M4, and the bytes Recovery
   records as `stage2SHA256`) is the patched Stage 2; GRUB's kernel release,
   every initrd `/lib/modules` release and the closure's `kernel-modules`
   release are one release; GRUB's kernel and initrd are the closure's; every
   fatal initrd `modprobe` resolves; and every UUID or label the initrd, GRUB
   and the closure fstab name is a filesystem the installer writes, with `/` on
   `root.img` and `/boot` on `boot.img`; and every first-boot initrd unit
   (`aurora-*`, `omarchy-*`, and what `sysroot.mount` requires) has its programs
   in the initrd and the kernel support its scripts need (dm-crypt, the root
   filesystem) for that kernel release (`--kernel-config` adds the kernel's
   `CONFIG_*=y` built-ins). `test-check-j773g-payload.sh` covers
   the pass case and each failure mode with small fixtures.
3. Generate the sealed catalog with `make-release-inputs.py --gate-receipt
   PAYLOAD-GATE.json ...`. It refuses a receipt that did not pass on these exact
   payload bytes, and records the gate results in `CATALOG-RECEIPT.json`.
4. Build on the Mac build host:

   ```sh
   AURORA_DEVELOPER_BUILD=1 macOS/Packaging/build-app.sh \
     macOS/M4MiniPatches/Release /absolute/output
   macOS/Packaging/build-developer-pkg.sh \
     '/absolute/output/Aurora Installer.app' \
     '/absolute/output/Aurora-Installer-0.1.0-alpha.21.m4minipatches.pkg'
   ```

   `build-app.sh` refuses `M4MiniPatches/Release` unless its catalog digest,
   payload digest and gate results match `ReleaseAssets/CATALOG-RECEIPT.json`.

The package is necessary: an ad-hoc app cannot use `SMJobBless`. The developer
package installs the helper LaunchDaemon with an exact code-directory-hash
binding to this one app build. It is unnotarized and must pass independent
review before use.

`make-release-inputs.py` derives the catalog from the live official Alpha 20
NixOS KDE catalog. It needs a new raw 32-byte Ed25519 private key, which must be
destroyed after signing, and it refuses to overwrite an existing output
directory. A new key means a new trust root; the catalog is not reproducible.
