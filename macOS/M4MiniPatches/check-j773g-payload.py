#!/usr/bin/env python3
"""Fail-closed build-time gate for the Mac16,10 (J773g) NixOS payload ZIP.

The installer copies payload members to the ESP by fixed rules
(NativeESPLayout.map in NativeBootChain.swift).  On an execute-window chip
such as M4, Stage 1 loads ESP ``m1n1/boot-ctxr.bin``; that file comes from
``esp/m1n1/boot-ctxr-<board>.bin`` when present, otherwise from
``esp/m1n1/boot-ctxr.bin``.  Recovery then records the same bytes as
``stage2SHA256``.  The installer writes ``boot.img`` and ``root.img`` byte for
byte, so their filesystem UUIDs are the UUIDs the installed system has.

Checks (each one must pass):

  stage2-active      the member installed as m1n1/boot-ctxr.bin has the
                     expected patched Stage 2 SHA-256 (and fits the window)
  stage2-standard    the member installed as m1n1/boot.bin has the same bytes
  kernel-release     GRUB's kernel release == every initrd /lib/modules release
                     == the system closure's kernel-modules release
  closure-identity   GRUB's kernel and initrd are the closure's kernel/initrd
  initrd-modprobe    every fatal ``modprobe`` in an initrd unit names a module
                     that is built in or present for that release
  root-identity      every UUID/label the initrd, GRUB and the closure fstab
                     name is one of the filesystems the installer writes, and
                     ``/`` and ``/boot`` name root.img and boot.img
  initrd-firstboot   every first-boot initrd unit (aurora-*/omarchy-*, and each
                     unit sysroot.mount requires) resolves under this kernel:
                     its fatal Exec* programs exist in the initrd, and the
                     kernel support its scripts need (dm-crypt for cryptsetup,
                     the root filesystem driver) is built in or in the initrd
                     module tree for the GRUB kernel's release

The vendor-firmware initrd unit is reported, not judged: its failure under
kernel A on hardware is an open blocker that a payload file check cannot
settle.

Needs: python3 >= 3.11, debugfs (e2fsprogs), btrfs (btrfs-progs), zstd.
Writes a JSON receipt; exit status 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import lzma
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

BOARD = "j773g"
# ExecuteWindow.auraSlot is the confined Stage 2 ceiling the installer enforces.
UUID_RE = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
FAT_RE = r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}"


class Failure(Exception):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, **kw)


# ------------------------------------------------------------- first-boot units

FIRSTBOOT_UNIT = re.compile(r"(^|/)(aurora|omarchy)[-_][^/]*\.service$")
# Programs in first-boot scripts -> kernel modules they need at run time.
SCRIPT_NEEDS = (
    (re.compile(r"\bcryptsetup\b"), ("dm_crypt", "dm_mod")),
    (re.compile(r"\bbtrfs\s+(filesystem|fi)\b"), ("btrfs",)),
)
FS_MODULE = {"btrfs": "btrfs", "ext4": "ext4", "vfat": "vfat", "xfs": "xfs"}
# CONFIG_ symbols for the modules above, for --kernel-config.
MODULE_CONFIG = {"dm_crypt": "DM_CRYPT", "dm_mod": "BLK_DEV_DM", "btrfs": "BTRFS_FS",
                 "ext4": "EXT4_FS", "vfat": "VFAT_FS", "xfs": "XFS_FS",
                 "apple_wdt": "APPLE_WATCHDOG"}


def exec_lines(text: str):
    """(directive, program, fatal) for each Exec* line of a unit."""
    for line in text.splitlines():
        m = re.match(r"\s*(ExecStartPre|ExecStart|ExecStartPost|ExecCondition)=(.*)", line)
        if not m or not m.group(2).strip():
            continue
        cmd = m.group(2).strip()
        prefix = re.match(r"[-@:+!]*", cmd).group(0)
        argv = cmd[len(prefix):].split()
        if argv:
            yield m.group(1), argv[0], "-" not in prefix


def unit_names(entries: dict[str, dict], unit: str) -> list[str]:
    return [n for n in entries if n.rsplit("/", 1)[-1] == unit]


def read_text(entries: dict[str, dict], path: str) -> str | None:
    e = entries.get(resolve_in(entries, path))
    if not e or e["kind"] != "file" or b"\0" in e["data"][:4096] or len(e["data"]) > (4 << 20):
        return None
    return e["data"].decode(errors="replace")


def firstboot_scan(entries: dict[str, dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """(units, missing programs, kernel-module requirements) for the first-boot set."""
    required = set()
    for name, e in entries.items():
        if "sysroot.mount" in name and e["kind"] == "file":
            for m in re.finditer(r"^(?:Requires|Wants|BindsTo)=(.*)$",
                                 e["data"].decode(errors="replace"), re.M):
                required.update(u for u in m.group(1).split() if u.endswith(".service"))
    units, missing, needs = [], [], []
    seen = set()
    for name, e in entries.items():
        base = name.rsplit("/", 1)[-1]
        if not (FIRSTBOOT_UNIT.search(name) or base in required) or base in seen:
            continue
        text = read_text(entries, name)
        if text is None:
            continue
        seen.add(base)
        m = re.search(r"^TimeoutStartSec=(\S+)", text, re.M)
        units.append({"unit": base, "path": name, "required_by_sysroot": base in required,
                      "timeout": m.group(1) if m else "default"})
        scripts: list[str] = []
        for directive, prog, fatal in exec_lines(text):
            if prog.startswith("/"):
                found = resolve_in(entries, prog) in entries
            else:
                found = any(resolve_in(entries, f"{d}/{prog}") in entries
                            for d in ("bin", "sbin", "usr/bin", "usr/sbin"))
            if not found and fatal:
                missing.append({"unit": base, "directive": directive, "program": prog})
            if found and prog.startswith("/"):
                scripts.append(prog)
        # Follow store paths from the unit's scripts (bounded) to find the
        # programs whose kernel support must be present.
        queue, visited = list(scripts), set()
        while queue and len(visited) < 64:
            path = queue.pop(0)
            if path in visited:
                continue
            visited.add(path)
            body = read_text(entries, path)
            if body is None:
                continue
            for pattern, modules in SCRIPT_NEEDS:
                if pattern.search(body):
                    for mod in modules:
                        needs.append({"unit": base, "module": mod, "why": f"{pattern.pattern} in {path}"})
            queue.extend(re.findall(r"/nix/store/[0-9a-z]{32}-[^\s'\"();|&<>]+", body))
    return units, missing, needs


def config_builtins(path: Path | None) -> set[str]:
    if not path:
        return set()
    text = path.read_text(errors="replace")
    return {mod for mod, sym in MODULE_CONFIG.items() if re.search(rf"^CONFIG_{sym}=y$", text, re.M)}


# --------------------------------------------------------------------------- ESP

def esp_layout(members: set[str], template: dict | None) -> tuple[str, str | None]:
    """(member for m1n1/boot.bin, member for m1n1/boot-ctxr.bin) per NativeESPLayout."""
    standard = "esp/m1n1/boot.bin"
    selected = None
    if template is not None and "aurora_stage2" in template:
        policy = template["aurora_stage2"]
        if policy.get("kind") != "board-file-v1":
            raise Failure("installer data has an unknown aurora_stage2 policy")
        selected = policy["board_members"].get(BOARD + "ap", standard)
    if selected is None:
        conventional = f"esp/m1n1/boot-{BOARD}.bin"
        selected = conventional if conventional in members else standard
    confined = next(
        (m for m in (f"esp/m1n1/boot-ctxr-{BOARD}.bin", "esp/m1n1/boot-ctxr.bin") if m in members),
        None,
    )
    return selected, confined


def os_template(metadata: Path | None) -> dict | None:
    if metadata is None:
        return None
    data = json.loads(metadata.read_text())
    entries = data.get("os_list") or []
    if len(entries) != 1:
        raise Failure("installer data must describe exactly one OS")
    return entries[0]


# ------------------------------------------------------------------ filesystems

def write_sparse(src, dst: Path) -> None:
    with dst.open("wb") as out:
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            if chunk.count(0) == len(chunk):
                out.seek(len(chunk), os.SEEK_CUR)
            else:
                out.write(chunk)
        out.truncate()


def ext4_identity(path: Path) -> dict:
    with path.open("rb") as f:
        f.seek(1024)
        sb = f.read(1024)
    if sb[0x38:0x3A] != b"\x53\xef":
        raise Failure(f"{path.name} is not ext2/3/4")
    u = sb[0x68:0x78].hex()
    label = sb[0x78:0x88].split(b"\0")[0].decode(errors="replace")
    return {"fs": "ext4", "uuid": f"{u[:8]}-{u[8:12]}-{u[12:16]}-{u[16:20]}-{u[20:]}", "label": label}


def btrfs_identity(path: Path) -> dict:
    with path.open("rb") as f:
        f.seek(0x10000)
        sb = f.read(4096)
    if sb[0x40:0x48] != b"_BHRfS_M":
        raise Failure(f"{path.name} is not btrfs")
    u = sb[0x20:0x30].hex()
    label = sb[0x12B:0x12B + 256].split(b"\0")[0].decode(errors="replace")
    return {"fs": "btrfs", "uuid": f"{u[:8]}-{u[8:12]}-{u[12:16]}-{u[16:20]}-{u[20:]}", "label": label}


def identity(path: Path) -> dict:
    try:
        return btrfs_identity(path)
    except Failure:
        return ext4_identity(path)


class Ext4Reader:
    def __init__(self, image: Path):
        self.image = image

    def read(self, path: str) -> bytes:
        r = run(["debugfs", "-R", f"cat {path}", str(self.image)])
        if r.returncode != 0 or b"File not found" in r.stderr:
            raise Failure(f"{self.image.name}: cannot read {path}")
        return r.stdout


class BtrfsReader:
    """Reads files from an unmounted btrfs image with `btrfs restore`."""

    def __init__(self, image: Path, work: Path):
        self.image = image
        self.work = work
        self.n = 0

    def _restore(self, path: str) -> Path:
        self.n += 1
        out = self.work / f"r{self.n}"
        out.mkdir()
        parts = [p for p in path.strip("/").split("/") if p]
        regex = "^/" + "".join(f"(|{re.escape(p)}" if i == 0 else f"(|/{re.escape(p)}" for i, p in enumerate(parts))
        regex += "(|/.*)" + ")" * len(parts) + "$"
        r = run(["btrfs", "restore", "-s", "-S", "-i", "--path-regex", regex, str(self.image), str(out)])
        if r.returncode != 0:
            raise Failure(f"btrfs restore {path}: {r.stderr.decode(errors='replace')[-300:]}")
        return out

    def locate(self, path: str, prefixes: list[str]) -> tuple[Path, str]:
        """Restore `path`, trying each subvolume prefix; return (local path, prefix)."""
        for prefix in prefixes:
            full = prefix + path
            out = self._restore(full)
            local = out / full.lstrip("/")
            if local.exists() or local.is_symlink():
                return local, prefix
            shutil.rmtree(out, ignore_errors=True)
        raise Failure(f"{self.image.name}: {path} not found under any of {prefixes}")


# ---------------------------------------------------------------------- initrd

def decompress_segments(data: bytes) -> list[bytes]:
    """Split a possibly concatenated initramfs into uncompressed cpio streams."""
    out, pos = [], 0
    while pos < len(data):
        rest = data[pos:]
        if rest[:4] == b"\0\0\0\0":
            pos += 4
            continue
        if rest[:6] in (b"070701", b"070702"):
            end = rest.find(b"TRAILER!!!")
            if end < 0:
                raise Failure("initrd: cpio without trailer")
            end += len(b"TRAILER!!!")
            end = (end + 3) & ~3
            out.append(rest[:end])
            pos += end
        elif rest[:2] == b"\x1f\x8b":
            d = zlib.decompressobj(31)
            out.append(d.decompress(rest))
            pos = len(data) - len(d.unused_data)
        elif rest[:6] == b"\xfd7zXZ\0":
            d = lzma.LZMADecompressor()
            out.append(d.decompress(rest))
            pos = len(data) - len(d.unused_data)
        elif rest[:4] == b"\x28\xb5\x2f\xfd":
            r = run(["zstd", "-dcq"], input=rest)
            if r.returncode != 0:
                raise Failure("initrd: zstd segment does not decompress")
            out.append(r.stdout)
            pos = len(data)
        else:
            raise Failure(f"initrd: unknown segment magic {rest[:6].hex()} at {pos}")
    return out


def parse_cpio(stream: bytes) -> dict[str, dict]:
    entries, pos = {}, 0
    while pos + 110 <= len(stream):
        hdr = stream[pos:pos + 110]
        if hdr[:6] not in (b"070701", b"070702"):
            break
        f = [int(hdr[6 + 8 * i:14 + 8 * i], 16) for i in range(13)]
        mode, filesize, namesize = f[1], f[6], f[11]
        name = stream[pos + 110:pos + 110 + namesize - 1].decode(errors="replace")
        pos = (pos + 110 + namesize + 3) & ~3
        body = stream[pos:pos + filesize]
        pos = (pos + filesize + 3) & ~3
        if name == "TRAILER!!!":
            break
        name = name.lstrip(".").lstrip("/")
        kind = {0o100000: "file", 0o120000: "link", 0o040000: "dir"}.get(mode & 0o170000, "other")
        entries[name] = {"kind": kind, "data": body if kind in ("file", "link") else b""}
    return entries


def initrd_entries(data: bytes) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for seg in decompress_segments(data):
        merged.update(parse_cpio(seg))
    return merged


def resolve_in(entries: dict[str, dict], path: str, depth: int = 0) -> str:
    """Resolve symlinks (any component) inside the initrd namespace."""
    if depth > 40:
        raise Failure(f"initrd: symlink loop at {path}")
    parts = [p for p in path.strip("/").split("/") if p]
    cur: list[str] = []
    for i, p in enumerate(parts):
        cur.append(p)
        joined = "/".join(cur)
        e = entries.get(joined)
        if e and e["kind"] == "link":
            target = e["data"].decode()
            base = target.strip("/") if target.startswith("/") else "/".join(cur[:-1] + [target])
            norm = os.path.normpath("/" + base).lstrip("/")
            return resolve_in(entries, "/".join([norm] + parts[i + 1:]), depth + 1)
    return "/".join(parts)


def module_trees(entries: dict[str, dict]) -> dict[str, str]:
    """release -> directory inside the initrd, for /lib/modules and store trees."""
    trees = {}
    lib = resolve_in(entries, "lib/modules")
    for name in entries:
        m = re.match(r"(.*?(?:^|/)lib/modules)/([^/]+)/", name + "/")
        if m and (m.group(1) == lib or m.group(1).startswith("nix/store/") or m.group(1) == "lib/modules"):
            trees.setdefault(m.group(2), f"{m.group(1)}/{m.group(2)}")
    return trees


def module_names(entries: dict[str, dict], tree: str) -> set[str]:
    names = set()
    for name, e in entries.items():
        if name.startswith(tree + "/") and re.search(r"\.ko(\.(xz|gz|zst))?$", name):
            names.add(re.sub(r"\.ko(\..*)?$", "", name.rsplit("/", 1)[1]).replace("-", "_"))
    for listing in ("modules.builtin", "modules.dep"):
        e = entries.get(resolve_in(entries, f"{tree}/{listing}"))
        if e and e["kind"] == "file":
            for line in e["data"].decode(errors="replace").splitlines():
                mod = line.split(":", 1)[0].strip()
                if mod:
                    names.add(re.sub(r"\.ko(\..*)?$", "", mod.rsplit("/", 1)[-1]).replace("-", "_"))
    return names


def text_files(entries: dict[str, dict]):
    for name, e in entries.items():
        if e["kind"] == "file" and len(e["data"]) <= (1 << 20) and b"\0" not in e["data"][:4096]:
            yield name, e["data"].decode(errors="replace")


def fstab_mounts(text: str) -> dict[str, str]:
    mounts = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 2 and not fields[0].startswith("#"):
            mounts[fields[1]] = fields[0]
    return mounts


def spec_identity(spec: str) -> tuple[str, str] | None:
    m = re.fullmatch(rf"(?:/dev/disk/by-uuid/|UUID=)({UUID_RE}|{FAT_RE})", spec)
    if m:
        return ("uuid", m.group(1).lower())
    m = re.fullmatch(r"(?:/dev/disk/by-label/|LABEL=)(.+)", spec)
    if m:
        return ("label", m.group(1).replace("\\x20", " "))
    return None


# ------------------------------------------------------------------------ GRUB

def grub_entries(cfg: str) -> list[dict]:
    entries, cur = [], None
    for raw in cfg.splitlines():
        line = raw.strip()
        if line.startswith("menuentry "):
            cur = {"title": line, "search": [], "linux": None, "initrd": None}
            entries.append(cur)
        elif cur is not None:
            if line.startswith("search "):
                cur["search"].append(line)
            elif line.startswith("linux "):
                cur["linux"] = line.split()[1:]
            elif line.startswith("initrd "):
                cur["initrd"] = line.split()[1:]
            elif line == "}":
                cur = None
    return [e for e in entries if e["linux"]]


def grub_drives(lines: list[str]) -> dict[str, tuple[str, str]]:
    """search --set=VAR (default root) --fs-uuid|--label X  ->  {VAR: (kind, X)}."""
    drives = {}
    for line in lines:
        words = line.split()
        var = "root"
        kind = None
        for w in words[1:]:
            if w.startswith("--set="):
                var = w.split("=", 1)[1]
            elif w in ("--fs-uuid", "-u"):
                kind = "uuid"
            elif w in ("--label", "-l"):
                kind = "label"
        if kind:
            value = words[-1]
            drives[var] = (kind, value.lower() if kind == "uuid" else value)
    return drives


def split_grub_path(path: str) -> tuple[str | None, str]:
    """'($drive1)//kernels/x' -> ('drive1', '/kernels/x'); '/x' -> (None, '/x')."""
    m = re.match(r"^\(\$?([^)]+)\)(.*)$", path)
    drive, rest = (m.group(1), m.group(2)) if m else (None, path)
    return drive, "/" + re.sub(r"/+", "/", rest).lstrip("/")


def kernel_release(image: bytes) -> str:
    if image[:2] == b"\x1f\x8b":
        image = gzip.decompress(image)
    elif image[:4] == b"\x28\xb5\x2f\xfd":
        image = run(["zstd", "-dcq"], input=image).stdout
    m = re.search(rb"Linux version (\S+) ", image)
    if not m:
        raise Failure("kernel image carries no 'Linux version' string")
    return m.group(1).decode()


# ------------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("payload", type=Path)
    ap.add_argument("--stage2-sha256", required=True)
    ap.add_argument("--stage2-max-bytes", type=int, default=0, help="0 = do not check")
    ap.add_argument("--kernel-sha256", help="expected GRUB kernel SHA-256 (optional)")
    ap.add_argument("--metadata", type=Path, help="installer-data JSON (stage2 board policy)")
    ap.add_argument("--esp-volume-id", help="FAT volume id the installer formats, e.g. 0x1FE07AA4")
    ap.add_argument("--kernel-config", type=Path,
                    help="the GRUB kernel's .config; CONFIG_X=y counts as built in for initrd-firstboot")
    ap.add_argument("--receipt", type=Path, required=True)
    ap.add_argument("--work", type=Path, help="scratch directory (default: temp)")
    args = ap.parse_args()

    checks: dict[str, dict] = {}
    facts: dict[str, object] = {"payload": str(args.payload)}

    def record(name: str, ok: bool, detail: object) -> None:
        checks[name] = {"result": "PASS" if ok else "FAIL", "detail": detail}

    work_ctx = tempfile.TemporaryDirectory(dir=args.work) if args.work else tempfile.TemporaryDirectory()
    try:
        with work_ctx as tmp, zipfile.ZipFile(args.payload) as z:
            work = Path(tmp)
            facts["payload_sha256"] = sha256_file(args.payload)
            members = {i.filename for i in z.infolist() if not i.is_dir()}
            template = os_template(args.metadata)

            # Stage 2 under the active name.
            standard, confined = esp_layout(members, template)
            facts["esp_member_for_boot_bin"] = standard
            facts["esp_member_for_boot_ctxr_bin"] = confined
            want = args.stage2_sha256.lower()
            if confined is None:
                record("stage2-active", False, "no confined Stage 2 member; M4 Stage 1 would load nothing")
            else:
                data = z.read(confined)
                ok = sha256_bytes(data) == want and (args.stage2_max_bytes == 0 or len(data) <= args.stage2_max_bytes)
                record("stage2-active", ok, {"member": confined, "esp_path": "m1n1/boot-ctxr.bin",
                                             "sha256": sha256_bytes(data), "bytes": len(data), "expected": want})
            data = z.read(standard)
            record("stage2-standard", sha256_bytes(data) == want,
                   {"member": standard, "esp_path": "m1n1/boot.bin", "sha256": sha256_bytes(data)})

            # Images exactly as the installer writes them.
            images = {}
            for name in ("boot.img", "root.img"):
                if name not in members:
                    raise Failure(f"payload has no {name}")
                with z.open(name) as src:
                    write_sparse(src, work / name)
                images[name] = identity(work / name)
            facts["filesystems"] = images
            esp_uuid = None
            if args.esp_volume_id:
                v = int(args.esp_volume_id, 16)
                esp_uuid = f"{v >> 16:04X}-{v & 0xFFFF:04X}".lower()
            elif template:
                for part in template.get("partitions", []):
                    if part.get("format") == "fat" and part.get("volume_id"):
                        v = int(part["volume_id"], 16)
                        esp_uuid = f"{v >> 16:04X}-{v & 0xFFFF:04X}".lower()
            facts["esp_uuid"] = esp_uuid
            by_uuid = {i["uuid"].lower(): n for n, i in images.items()}
            if esp_uuid:
                by_uuid[esp_uuid] = "esp"
            by_label = {i["label"]: n for n, i in images.items() if i["label"]}
            boot_fs = Ext4Reader(work / "boot.img") if images["boot.img"]["fs"] == "ext4" else None
            root_reader = BtrfsReader(work / "root.img", work) if images["root.img"]["fs"] == "btrfs" else None
            if boot_fs is None or root_reader is None:
                raise Failure(f"unexpected layout {images}; expected ext4 boot.img and btrfs root.img")
            subvol_prefixes = ["/root", "/@", ""]

            grub_cfg = None
            for candidate in ("/grub/grub.cfg", "/boot/grub/grub.cfg"):
                try:
                    grub_cfg = boot_fs.read(candidate).decode(errors="replace")
                    facts["grub_cfg_path"] = candidate
                    break
                except Failure:
                    continue
            if grub_cfg is None:
                raise Failure("boot.img has no GRUB configuration")
            entries = grub_entries(grub_cfg)
            if not entries:
                raise Failure("GRUB configuration has no Linux entry")
            facts["grub_cfg"] = grub_cfg[-4000:]
            global_search = [l.strip() for l in grub_cfg.splitlines() if l.strip().startswith("search ")]

            def grub_read(path: str, drives: dict) -> tuple[bytes, str]:
                drive, rel = split_grub_path(path)
                kind, value = drives.get(drive or "root", ("uuid", images["boot.img"]["uuid"]))
                target = (by_uuid.get(value) if kind == "uuid" else by_label.get(value))
                if target == "boot.img":
                    return boot_fs.read(rel), "boot.img"
                if target == "root.img":
                    local, _ = root_reader.locate(rel, [""] + subvol_prefixes)
                    return local.read_bytes(), "root.img"
                raise Failure(f"GRUB path {path} names drive {drive or 'root'}={value}, not a written filesystem")

            refs: list[dict] = []  # every filesystem reference we must resolve

            def note_ref(where: str, kind: str, value: str, role: str | None = None) -> None:
                # udev rules and shell helpers carry templates ($env{...}, $label);
                # only literal identifiers are references.
                if any(c in value for c in "$%{}*") or value in ("by-uuid", "by-label"):
                    return
                refs.append({"where": where, "kind": kind, "value": value, "role": role})

            for m in re.finditer(rf"search\s[^\n]*--fs-uuid[^\n]*?\s({UUID_RE})", grub_cfg):
                note_ref("grub search", "uuid", m.group(1).lower())
            for m in re.finditer(r"search\s[^\n]*--label[^\n]*?\s(\S+)\s*$", grub_cfg, re.M):
                note_ref("grub search", "label", m.group(1))

            releases = {}
            closure_ok = []
            fatal_modprobe = []
            initrd_info = []
            firstboot = []          # per entry: units, missing programs, unmet modules
            builtin_cfg = config_builtins(args.kernel_config)
            for idx, entry in enumerate(entries):
                kpath, *params = entry["linux"]
                ipaths = entry["initrd"] or []
                drives = grub_drives(global_search + entry["search"])
                kernel, kernel_fs = grub_read(kpath, drives)
                krel = kernel_release(kernel)
                releases[f"grub[{idx}].kernel"] = krel
                if args.kernel_sha256 and sha256_bytes(kernel) != args.kernel_sha256.lower():
                    closure_ok.append({"entry": idx, "problem": "kernel SHA-256 differs from expected",
                                       "sha256": sha256_bytes(kernel)})
                init = next((p.split("=", 1)[1] for p in params if p.startswith("init=")), None)
                for p in params:
                    if p.startswith("root=") and p != "root=fstab":
                        ident = spec_identity(p[5:])
                        if ident:
                            note_ref(f"grub[{idx}] root=", ident[0], ident[1], "root.img")
                if not ipaths:
                    raise Failure(f"GRUB entry {idx} loads no initrd")
                initrd_parts = [grub_read(ip, drives)[0] for ip in ipaths]
                initrd = initrd_parts[0]
                ent = {}
                for part in initrd_parts:  # GRUB concatenates them in order
                    ent.update(initrd_entries(part))
                trees = module_trees(ent)
                for rel in trees:
                    releases[f"grub[{idx}].initrd:/lib/modules/{rel}"] = rel
                if not trees:
                    releases[f"grub[{idx}].initrd:/lib/modules"] = "<none>"
                avail = module_names(ent, trees[krel]) if krel in trees else set()
                for name, text in text_files(ent):
                    if name.endswith(".service"):
                        for line in text.splitlines():
                            m = re.match(r"(ExecStartPre|ExecStart)=([^-@:+!].*)", line.strip())
                            if m and re.search(r"(^|/)modprobe\s", m.group(2)):
                                for mod in [a for a in m.group(2).split()[1:] if not a.startswith("-")]:
                                    if mod.replace("-", "_") not in avail:
                                        fatal_modprobe.append({"entry": idx, "unit": name, "module": mod,
                                                               "line": line.strip()[:300]})
                    if name.endswith("fstab") or "/etc/fstab" in name:
                        for mnt, spec in fstab_mounts(text).items():
                            ident = spec_identity(spec)
                            if ident:
                                role = {"/": "root.img", "/sysroot": "root.img", "/boot": "boot.img",
                                        "/sysroot/boot": "boot.img"}.get(mnt)
                                note_ref(f"initrd[{idx}]:{name} {mnt}", ident[0], ident[1], role)
                    for m in re.finditer(rf"by-uuid/({UUID_RE}|{FAT_RE})\b", text):
                        note_ref(f"initrd[{idx}]:{name}", "uuid", m.group(1).lower())
                    for m in re.finditer(r"by-label/([^\s'\"]+)", text):
                        note_ref(f"initrd[{idx}]:{name}", "label", m.group(1).replace("\\x20", " "))
                fb_units, fb_missing, fb_needs = firstboot_scan(ent)
                for name, text in text_files(ent):
                    if name.endswith("fstab") or "/etc/fstab" in name:
                        for line in text.splitlines():
                            f = line.split()
                            if len(f) >= 3 and not f[0].startswith("#") and f[1] in ("/", "/sysroot") \
                                    and f[2] in FS_MODULE:
                                fb_needs.append({"unit": "sysroot.mount", "module": FS_MODULE[f[2]],
                                                 "why": f"{name}: {f[1]} is {f[2]}"})
                firstboot.append({"entry": idx, "release": krel, "units": fb_units, "missing": fb_missing,
                                  "needs": fb_needs, "initrd_modules": avail})
                fw = [n for n in ent if n.endswith("aurora-vendor-firmware.service")]
                root_units = [n for n in ent if n.endswith("aurora-initrd-root.service")]
                root_timeout = None
                for n in root_units:
                    e = ent[resolve_in(ent, n)]
                    if e["kind"] == "file":
                        m = re.search(r"^TimeoutStartSec=(\S+)", e["data"].decode(errors="replace"), re.M)
                        root_timeout = m.group(1) if m else "default"
                initrd_info.append({"entry": idx, "initrd": ipaths[0], "sha256": sha256_bytes(initrd),
                                    "module_releases": sorted(trees),
                                    "vendor_firmware_unit_present": bool(fw),
                                    "module_tree_evidence": {
                                        rel: {
                                            "dir": tree,
                                            "has_modules_builtin": resolve_in(ent, f"{tree}/modules.builtin") in ent,
                                            "ko_files": sum(1 for n in ent if n.startswith(tree + "/")
                                                            and re.search(r"\.ko(\.(xz|gz|zst))?$", n)),
                                            "known_module_names": len(module_names(ent, tree)),
                                        } for rel, tree in trees.items()},
                                    "initrd_root_unit_present": bool(root_units),
                                    "initrd_root_unit_timeout": root_timeout})

                # The system closure GRUB starts must be this kernel/initrd's closure.
                if not init:
                    closure_ok.append({"entry": idx, "problem": "no init= on the kernel command line"})
                    continue
                system = init.rsplit("/", 1)[0]
                problems = []
                for leaf, expect in (("kernel", sha256_bytes(kernel)), ("initrd", sha256_bytes(initrd))):
                    link, prefix = root_reader.locate(f"{system}/{leaf}", subvol_prefixes)
                    target = os.readlink(link) if link.is_symlink() else None
                    if target:
                        local, _ = root_reader.locate(target, [prefix])
                        got = sha256_file(local)
                    else:
                        got = sha256_file(link)
                    if got != expect:
                        problems.append(f"closure {leaf} {got} != GRUB {leaf} {expect}")
                link, prefix = root_reader.locate(f"{system}/kernel-modules", subvol_prefixes)
                km = os.readlink(link) if link.is_symlink() else f"{system}/kernel-modules"
                kmdir, _ = root_reader.locate(f"{km}/lib/modules", [prefix])
                for rel in sorted(os.listdir(kmdir)):
                    releases[f"grub[{idx}].closure:kernel-modules/{rel}"] = rel
                    builtin = kmdir / rel / "modules.builtin"
                    if rel == krel and builtin.is_file():
                        firstboot[-1]["closure_builtin"] = {
                            re.sub(r"\.ko(\..*)?$", "", l.strip().rsplit("/", 1)[-1]).replace("-", "_")
                            for l in builtin.read_text(errors="replace").splitlines() if l.strip()}
                etc_link, _ = root_reader.locate(f"{system}/etc", [prefix])
                etc = os.readlink(etc_link) if etc_link.is_symlink() else f"{system}/etc"
                fstab_link, _ = root_reader.locate(f"{etc}/fstab", [prefix])
                chain = [f"{etc}/fstab"]
                hops = 0
                while fstab_link.is_symlink() and hops < 8:
                    t = os.readlink(fstab_link)
                    chain.append(t)
                    fstab_link, _ = root_reader.locate(t if t.startswith("/") else f"{etc}/{t}", [prefix])
                    hops += 1
                fstab_text = fstab_link.read_text()
                facts.setdefault("closure_fstab", {})[f"entry{idx}"] = {
                    "chain": chain, "bytes": len(fstab_text), "text": fstab_text[-2000:]}
                if not fstab_mounts(fstab_text):
                    problems.append(f"closure fstab {' -> '.join(chain)} is empty or unreadable "
                                    f"({len(fstab_text)} bytes restored)")
                for mnt, spec in fstab_mounts(fstab_text).items():
                    if mnt == "/" and spec.startswith("/dev/mapper/"):
                        # Reported, not judged: the stock first-boot conversion
                        # (aurora-initrd-root.service) encrypts root in place.
                        facts.setdefault("closure_root_device_mapper", []).append(
                            {"entry": idx, "spec": spec})
                    ident = spec_identity(spec)
                    if ident:
                        role = {"/": "root.img", "/boot": "boot.img"}.get(mnt)
                        note_ref(f"closure {etc}/fstab {mnt}", ident[0], ident[1], role)
                facts.setdefault("closures", []).append({"entry": idx, "system": system, "subvolume_prefix": prefix,
                                                         "kernel_modules": km})
                if problems:
                    closure_ok.append({"entry": idx, "problems": problems})

            facts["grub_entries"] = [{"title": e["title"], "linux": e["linux"], "initrd": e["initrd"]} for e in entries]
            facts["initrds"] = initrd_info
            distinct = sorted(set(releases.values()))
            record("kernel-release", len(distinct) == 1 and distinct != ["<none>"], releases)
            record("closure-identity", not closure_ok, closure_ok or "GRUB kernel/initrd are the closure's")
            record("initrd-modprobe", not fatal_modprobe, fatal_modprobe or "every fatal modprobe resolves")

            fb_bad, fb_report = [], []
            for fb in firstboot:
                have = fb["initrd_modules"] | fb.get("closure_builtin", set()) | builtin_cfg
                unmet = [n for n in fb["needs"] if n["module"] not in have]
                if not fb["units"]:
                    fb_bad.append({"entry": fb["entry"], "problem": "no first-boot initrd unit found"})
                fb_bad += [dict(m, entry=fb["entry"], problem="program not in initrd") for m in fb["missing"]]
                fb_bad += [dict(n, entry=fb["entry"], problem=f"module not built in or in initrd for {fb['release']}")
                           for n in unmet]
                fb_report.append({"entry": fb["entry"], "release": fb["release"], "units": fb["units"],
                                  "needs": sorted({n["module"] for n in fb["needs"]}),
                                  "builtin_source": ("closure modules.builtin" if "closure_builtin" in fb else
                                                     "none") + (" + --kernel-config" if builtin_cfg else "")})
            facts["initrd_firstboot"] = fb_report
            record("initrd-firstboot", not fb_bad, fb_bad or "first-boot units resolve under this kernel")

            bad = []
            for ref in refs:
                target = by_uuid.get(ref["value"]) if ref["kind"] == "uuid" else by_label.get(ref["value"])
                ref["resolves_to"] = target
                if target is None or (ref["role"] and target != ref["role"]):
                    bad.append(ref)
            if not any(r["role"] == "root.img" for r in refs):
                bad.append({"problem": "nothing names the root filesystem by UUID or label"})
            record("root-identity", not bad, bad or f"{len(refs)} references all resolve")
            facts["filesystem_references"] = refs
            facts["open_blockers"] = [
                "Under kernel A on J773g /sysroot never mounted even with the correct root UUID "
                "(alpha20-kernel-a-root-c70d-20261115-01). sysroot.mount Requires= "
                "aurora-initrd-root.service, the first-boot btrfs shrink + in-place LUKS conversion, "
                "which has no start timeout and was still running at +183 s. "
                "aurora-vendor-firmware.service also failed (likely the mismatched module tree) but "
                "only orders before sysroot.mount. Neither is decidable from payload files; the "
                "bypass candidate is unbooted."
            ]
    except (Failure, zipfile.BadZipFile, KeyError, OSError) as exc:
        record("gate", False, f"{type(exc).__name__}: {exc}")

    verdict = "PASS" if checks and all(c["result"] == "PASS" for c in checks.values()) else "FAIL"
    receipt = {"schema": 1, "tool": "check-j773g-payload.py", "verdict": verdict, "checks": checks, "facts": facts}
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    for name, c in checks.items():
        print(f"{c['result']}  {name}")
    print(f"VERDICT {verdict}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
