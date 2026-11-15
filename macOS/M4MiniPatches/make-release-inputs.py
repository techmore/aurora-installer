#!/usr/bin/env python3
"""Create the sealed J773g-only developer catalog for the M4 mini test build."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import urllib.request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

TAG = "v0.1.0-alpha.20.m4minipatches"
RELEASE_BASE = f"https://github.com/techmore/aurora-installer/releases/download/{TAG}"
PROFILE = "nixos-kde"
PAYLOAD = "nixos-kde-build-43451965403.zip"
METADATA = "installer-data-nixos-kde.json"
METADATA_SHA256 = "db285f896eadce0a010beb17fb0da5bac5f5c293b8a80e497fe8ff1e7107bb3f"
METADATA_BYTES = 16_714


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_identity(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r'([A-Z][A-Z0-9_]*)="([^"\\$`]*)"', line)
        if match:
            values[match.group(1)] = match.group(2)
    for name in ("INSTALLER_HELPER_IDENTIFIER", "INSTALLER_PUBLIC_BASE", "INSTALLER_STREAM_PATH"):
        if not values.get(name):
            raise SystemExit(f"identity file is missing {name}")
    return values


def descriptor(fingerprint: str, helper_identifier: str) -> dict:
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
        "helper_mach_service_name": helper_identifier,
        "helper_code_signing_requirement": f'identifier "{helper_identifier}"',
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
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument(
        "--identity",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "Packaging" / "identity.conf",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite {args.output}")

    identity = read_identity(args.identity)
    helper_identifier = identity["INSTALLER_HELPER_IDENTIFIER"]
    official_envelope = (
        f'{identity["INSTALLER_PUBLIC_BASE"]}/{identity["INSTALLER_STREAM_PATH"]}/Profiles/'
        "nixos-kde/channels/edge/catalog.signed.json"
    )

    private_raw = args.private_key.read_bytes()
    if len(private_raw) != 32:
        raise SystemExit("private key must contain exactly 32 raw Ed25519 bytes")
    metadata = args.metadata.read_bytes()
    if len(metadata) != METADATA_BYTES or digest(metadata) != METADATA_SHA256:
        raise SystemExit("official NixOS KDE metadata does not match Alpha 20")
    if args.payload.name != PAYLOAD or not args.payload.is_file():
        raise SystemExit(f"payload must be a regular file named {PAYLOAD}")
    payload_sha256 = file_digest(args.payload)
    payload_bytes = args.payload.stat().st_size
    part_paths = sorted(args.payload.parent.glob(f"{PAYLOAD}.part[0-9][0-9]"))
    expected_names = [f"{PAYLOAD}.part{index:02d}" for index in range(len(part_paths))]
    if len(part_paths) < 2 or [path.name for path in part_paths] != expected_names:
        raise SystemExit("payload parts are missing or not a contiguous part00 sequence")
    parts = [
        (path.name.removeprefix(f"{PAYLOAD}."), path.stat().st_size, file_digest(path))
        for path in part_paths
    ]
    if sum(part[1] for part in parts) != payload_bytes:
        raise SystemExit("part sizes do not reconstruct the payload")
    reconstructed = hashlib.sha256()
    for path in part_paths:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                reconstructed.update(block)
    if reconstructed.hexdigest() != payload_sha256:
        raise SystemExit("payload parts do not reconstruct the payload bytes")

    with urllib.request.urlopen(official_envelope) as response:
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

    record["payloadDigest"] = f"sha256:{payload_sha256}"
    record["evidenceRevision"] = "alpha20-j773g-fullstack-135aa996"
    record["metadataArtifact"] = {
        "sourceURL": f"{RELEASE_BASE}/{METADATA}",
        "fileName": METADATA,
        "sizeBytes": METADATA_BYTES,
    }
    record["payloadArtifact"] = {
        "sourceURL": f"{RELEASE_BASE}/{PAYLOAD}",
        "fileName": PAYLOAD,
        "sizeBytes": payload_bytes,
        "parts": [
            {
                "sourceURL": f"{RELEASE_BASE}/{PAYLOAD}.{suffix}",
                "fileName": f"{PAYLOAD}.{suffix}",
                "sizeBytes": size,
                "sha256": f"sha256:{sha256}",
            }
            for suffix, size, sha256 in parts
        ],
    }

    catalog = {
        "schemaVersion": 5,
        "sequence": 1_794_751_920,
        "issuedAt": "2026-11-15T14:12:00Z",
        "expiresAt": "2027-02-15T14:12:00Z",
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
    release = descriptor(fingerprint, helper_identifier)
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
            "payloadSha256": payload_sha256,
            "payloadBytes": payload_bytes,
            "payloadParts": len(parts),
            "metadataSha256": METADATA_SHA256,
            "sourceCatalog": official_envelope,
        },
    )


if __name__ == "__main__":
    main()
