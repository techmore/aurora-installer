# Mac16,10 Alpha 20 test release inputs

These inputs build the unofficial `0.1.0-alpha.20.m4minipatches` developer package. They admit only `apple,j773g` and default the UI to the only included profile, Aurora NixOS KDE. They are not signed by the Aurora project.

The sealed schema-5 catalog is signed by the disposable test key whose public half is `Release/trust-root.ed25519.pub` (SHA-256 `1fba873ce0fb89a20221bb0add62fe5a8746364339fbd9d3055bf86ad3b04618`). The private half was destroyed after signing. The catalog SHA-256 is `d344475845ab6e7292bfe9933a6286eeed6db6a993077af1dec1379d6be206b6`; it pins the patched payload SHA-256 `6b3133a13efa365e05d5c4bef1ba1cabb93bf062371b79d768379321fca1bc2d` and all six release parts.

Build only on the Mac build host:

```sh
AURORA_DEVELOPER_BUILD=1 macOS/Packaging/build-app.sh \
  macOS/M4MiniPatches/Release /absolute/output
macOS/Packaging/build-developer-pkg.sh \
  '/absolute/output/Aurora Installer.app' \
  '/absolute/output/Aurora-Installer-0.1.0-alpha.20.m4minipatches.pkg'
```

The package is necessary: an ad-hoc app cannot use `SMJobBless`. The developer package installs the helper LaunchDaemon with an exact code-directory-hash binding to this one app build. It is still unnotarized and must pass independent review before use.

`make-release-inputs.py` documents how the committed catalog was derived from the live official Alpha 20 NixOS KDE catalog. It requires a new raw 32-byte Ed25519 private key and refuses to overwrite an existing output directory. Regenerating creates a new trust root and is not reproducible; do not regenerate the committed inputs for this release.
