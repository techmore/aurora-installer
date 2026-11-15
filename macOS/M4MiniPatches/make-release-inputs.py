#!/usr/bin/env python3
"""Create the sealed J773g-only developer catalog for the M4 mini test build."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

OFFICIAL_ENVELOPE = (
    "https://aurorasilicon.org/aurora-distributions/installer/Profiles/"
    "nixos-kde/channels/edge/catalog.signed.json"
)
TAG = "v0.1.0-alpha.20.m4minipatches"
RELEASE_BASE = f"https://github.com/techmore/aurora-installer/releases/download/{TAG}"
PROFILE = "nixos-kde"
PAYLOAD = "nixos-kde-build-43451965403.zip"
PAYLOAD_SHA256 = "6b3133a13efa365e05d5c4bef1ba1cabb93bf062371b79d768379321fca1bc2d"
PAYLOAD_BYTES = 5_910_504_128
METADATA = "installer-data-nixos-kde.json"
METADATA_SHA256 = "db285f896eadce0a010beb17fb0da5bac5f5c293b8a80e497fe8ff1e7107bb3f"
METADATA_BYTES = 16_714
PARTS = (
    ("part00", 1_073_741_824, "09c0d23be061d39076702595c7c8d543a3ca593fd678a99fc1f6219aa4d633e1"),
    ("part01", 1_073_741_824, "dd70b47c58a745a22dadf884de665cb3d332cadce6f73c1d68223486db3c38fb"),
    ("part02", 1_073_741_824, "529d4cb6d20a899ee2d6c1d26be413295921da733b57831f4755a0a971fd9ed3"),
    ("part03", 1_073_741_824, "8e310bb4addb0bdcc60798ca2514aca146b48d5e908947563bab8ae373c3051f"),
    ("part04", 1_073_741_824, "7c41aec281c972af9bb85fe49037e7c3120eccd14f85b97a52bef4d6fce91abe"),
    ("part05", 541_795_008, "6b3fd586410f4511bb18ca907fd1ec7607eaf163989c4725f61c6edbf48f3f6a"),
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def descriptor(fingerprint: str) -> dict:
    return {
        "schema_version": 3,
        "default_channel": "edge",
        "channels": {
            channel: {
                "catalog_url": f"{RELEASE_BASE}/{PROFILE}-{channel}.catalog.signed.json"
            }
            for channel in ("stable", "rc", "edge")
        },
        "trust_root_fingerprint": f"sha256:{fingerprint}",
        "helper_mach_service_name": "org.aurorasilicon.installer.helper",
        "helper_code_signing_requirement": 'identifier "org.aurorasilicon.installer.helper"',
    }


def write_json(path: Path, value: object, *, compact: bool = False) -> None:
    if compact:
        body = json.dumps(value, separators=(",", ":")) + "\n"
    else:
        body = json.dumps(value, indent=2) + "\n"
    path.write_text(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite {args.output}")

    private_raw = args.private_key.read_bytes()
    if len(private_raw) != 32:
        raise SystemExit("private key must contain exactly 32 raw Ed25519 bytes")
    metadata = args.metadata.read_bytes()
    if len(metadata) != METADATA_BYTES or digest(metadata) != METADATA_SHA256:
        raise SystemExit("official NixOS KDE metadata does not match Alpha 20")

    with urllib.request.urlopen(OFFICIAL_ENVELOPE) as response:
        envelope = json.load(response)
    official = json.loads(base64.b64decode(envelope["catalog"]))
    records = [record for record in official["models"] if record["deviceIdentifier"] == "apple,j773g"]
    if len(records) != 1:
        raise SystemExit("official catalog does not contain exactly one apple,j773g record")
    record = records[0]
    if (
        record["installationProfile"] != PROFILE
        or record["metadataDigest"] != f"sha256:{METADATA_SHA256}"
        or record["payloadDigest"]
        != "sha256:061f2d4e000802ee90c17f6d69ff995360ddf422bfd86ba7616d35cc523160e7"
    ):
        raise SystemExit("official J773g record is not the audited Alpha 20 NixOS KDE record")

    record["payloadDigest"] = f"sha256:{PAYLOAD_SHA256}"
    record["evidenceRevision"] = "alpha20-j773g-ethernet-4248745d"
    record["metadataArtifact"] = {
        "sourceURL": f"{RELEASE_BASE}/{METADATA}",
        "fileName": METADATA,
        "sizeBytes": METADATA_BYTES,
    }
    record["payloadArtifact"] = {
        "sourceURL": f"{RELEASE_BASE}/{PAYLOAD}",
        "fileName": PAYLOAD,
        "sizeBytes": PAYLOAD_BYTES,
        "parts": [
            {
                "sourceURL": f"{RELEASE_BASE}/{PAYLOAD}.{suffix}",
                "fileName": f"{PAYLOAD}.{suffix}",
                "sizeBytes": size,
                "sha256": f"sha256:{sha256}",
            }
            for suffix, size, sha256 in PARTS
        ],
    }
    if sum(part[1] for part in PARTS) != PAYLOAD_BYTES:
        raise SystemExit("part sizes do not reconstruct the payload")

    catalog = {
        "schemaVersion": 5,
        "sequence": 1_794_694_001,
        "issuedAt": "2026-11-15T03:34:00Z",
        "expiresAt": "2027-02-15T03:34:00Z",
        "installer": official["installer"],
        "models": [record],
    }
    catalog_bytes = (json.dumps(catalog, indent=2) + "\n").encode()
    key = Ed25519PrivateKey.from_private_bytes(private_raw)
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    signature = key.sign(catalog_bytes)
    key.public_key().verify(signature, catalog_bytes)

    root = args.output
    profile = root / "Profiles" / PROFILE
    assets = root.parent / "ReleaseAssets"
    profile.mkdir(parents=True)
    assets.mkdir(parents=True)
    fingerprint = digest(public)
    release = descriptor(fingerprint)
    for directory in (root, profile):
        write_json(directory / "release.json", release)
        (directory / "trust-root.ed25519.pub").write_bytes(public)
        (directory / "catalog.json").write_bytes(catalog_bytes)
        (directory / "catalog.json.sig").write_bytes(signature)
    write_json(
        root / "profile-manifest.json",
        {
            "schema": 1,
            "sealed": True,
            "profiles": {
                PROFILE: {
                    "catalog_sha256": digest(catalog_bytes),
                    "sequence": catalog["sequence"],
                }
            },
        },
    )
    shutil.copyfile(args.metadata, assets / METADATA)
    signed = {
        "schema_version": 1,
        "catalog": base64.b64encode(catalog_bytes).decode(),
        "signature": base64.b64encode(signature).decode(),
    }
    for channel in ("stable", "rc", "edge"):
        write_json(assets / f"{PROFILE}-{channel}.catalog.signed.json", signed, compact=True)
    write_json(
        assets / "CATALOG-RECEIPT.json",
        {
            "schema": 1,
            "profile": PROFILE,
            "deviceIdentifier": "apple,j773g",
            "catalogSha256": digest(catalog_bytes),
            "trustRootSha256": fingerprint,
            "payloadSha256": PAYLOAD_SHA256,
            "metadataSha256": METADATA_SHA256,
            "sourceCatalog": OFFICIAL_ENVELOPE,
        },
    )


if __name__ == "__main__":
    main()
