#!/bin/bash
# Fixture tests for check-j773g-payload.py: one consistent payload must pass,
# and each known J773g failure mode must fail its own check.
# Needs root-free tools only: mkfs.ext4 -d, mkfs.btrfs --rootdir, cpio, zstd, zip.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
checker=${CHECKER:-$here/check-j773g-payload.py}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

rel_a=7.3.0-m4atlrx-m4test-j773g-fullchain-v2-20261115
boot_uuid=41dc57cf-2d07-50f9-ba96-7c95cde85ada
root_uuid=8e3c084b-44d8-5293-a753-ae3288c9274b
stale_uuid=c70d646a-adf9-41af-bcfd-67d75b6a32a0
sys=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-nixos-system-aurora-test
km=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb-kernel-modules
etcp=cccccccccccccccccccccccccccccccc-etc
fst=dddddddddddddddddddddddddddddddd-etc-fstab
kpkg=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee-linux-test
ipkg=ffffffffffffffffffffffffffffffff-initrd-linux-test

printf 'stage2-patched' > "$work/stage2-patched.bin"
printf 'stage2-stock' > "$work/stage2-stock.bin"
patched=$(sha256sum "$work/stage2-patched.bin" | cut -d' ' -f1)

kernel() { # release -> file
  { head -c 4096 /dev/zero; printf 'Linux version %s (builder@test) #1 SMP\n' "$1"; head -c 4096 /dev/zero; } > "$2"
}

initrd() { # out module_release fstab_root_uuid [firstboot: good|no-exec|no-dmcrypt]
  local d=$work/initrd-src fb=${4:-good}
  local fbs=nix/store/gggggggggggggggggggggggggggggggg-aurora-firstboot/lib/aurora
  rm -rf "$d"; mkdir -p "$d/etc" "$d/nix/store/ms-kernel-modules-shrunk/lib/modules/$2" "$d/etc/systemd/system"
  ln -s /nix/store/ms-kernel-modules-shrunk/lib/modules "$d/lib-modules-tmp"
  mkdir -p "$d/lib"; mv "$d/lib-modules-tmp" "$d/lib/modules"
  printf 'kernel/drivers/watchdog/apple_wdt.ko\nkernel/drivers/nvme/host/nvme-apple.ko\nkernel/fs/btrfs/btrfs.ko\nkernel/drivers/md/dm-mod.ko\n' \
    > "$d/nix/store/ms-kernel-modules-shrunk/lib/modules/$2/modules.builtin"
  [[ $fb == no-dmcrypt ]] || printf 'kernel/drivers/md/dm-crypt.ko\n' \
    >> "$d/nix/store/ms-kernel-modules-shrunk/lib/modules/$2/modules.builtin"
  # First-boot programs: /bin/true, modprobe, and the root conversion script
  # that calls cryptsetup (needs dm-crypt) through a second store script.
  mkdir -p "$d/bin" "$d/nix/store/k-kmod/bin" "$d/$fbs"
  printf '#!/bin/sh\n' > "$d/bin/true"
  printf '#!/bin/sh\n' > "$d/nix/store/k-kmod/bin/modprobe"
  printf '#!/bin/sh\nexec /%s/encrypt-step "$@"\n' "$fbs" > "$d/$fbs/aurora-initrd-root"
  printf '#!/bin/sh\ncryptsetup reencrypt --encrypt /dev/root\n' > "$d/$fbs/encrypt-step"
  [[ $fb == no-exec ]] && rm "$d/$fbs/aurora-initrd-root"
  mkdir -p "$d/etc/systemd/system/sysroot.mount.d"
  printf '[Unit]\nRequires=aurora-initrd-root.service\nAfter=aurora-initrd-root.service\n' \
    > "$d/etc/systemd/system/sysroot.mount.d/overrides.conf"
  : > "$d/nix/store/ms-kernel-modules-shrunk/lib/modules/$2/modules.dep"
  printf '/dev/disk/by-uuid/%s / btrfs x-initrd.mount,subvol=root,compress=zstd:1 0 0\n' "$3" > "$d/etc/fstab"
  printf '[Service]\nTimeoutStartSec=infinity\nExecStartPre=/nix/store/k-kmod/bin/modprobe apple_wdt\nExecStart=/%s/aurora-initrd-root\n' "$fbs" \
    > "$d/etc/systemd/system/aurora-initrd-root.service"
  printf '[Service]\nExecStart=/bin/true\n' > "$d/etc/systemd/system/aurora-vendor-firmware.service"
  (cd "$d" && find . | cpio --quiet -o -H newc | zstd -q -19 -o "$1")
}

make_payload() { # name ctxr_bin kernel_rel initrd_rel initrd_root_uuid closure_rel [firstboot]
  local name=$1 p=$work/$1
  mkdir -p "$p/esp/m1n1" "$p/bootfs/grub" "$p/bootfs/kernels" "$p/rootfs/root/nix/store"
  cp "$work/stage2-stock.bin" "$p/esp/m1n1/boot.bin"
  cp "$work/stage2-stock.bin" "$p/esp/m1n1/boot-ctxr.bin"
  cp "$work/stage2-patched.bin" "$p/esp/m1n1/boot-j773g.bin"
  cp "$2" "$p/esp/m1n1/boot-ctxr-j773g.bin"
  kernel "$3" "$p/bootfs/kernels/Image"
  initrd "$p/bootfs/kernels/initrd" "$4" "$5" "${7:-good}"
  cat > "$p/bootfs/grub/grub.cfg" <<EOF
set default=0
menuentry "NixOS" --class nixos {
  search --no-floppy --fs-uuid --set=drive1 $boot_uuid
  linux (\$drive1)//kernels/Image init=/nix/store/$sys/init root=fstab
  initrd (\$drive1)//kernels/initrd
}
EOF
  local s=$p/rootfs/root/nix/store
  mkdir -p "$s/$sys" "$s/$kpkg" "$s/$ipkg" "$s/$km/lib/modules/$6" "$s/$etcp/etc" "$s/$fst"
  cp "$p/bootfs/kernels/Image" "$s/$kpkg/Image"
  cp "$p/bootfs/kernels/initrd" "$s/$ipkg/initrd"
  ln -s "/nix/store/$kpkg/Image" "$s/$sys/kernel"
  ln -s "/nix/store/$ipkg/initrd" "$s/$sys/initrd"
  ln -s "/nix/store/$km" "$s/$sys/kernel-modules"
  ln -s "/nix/store/$etcp/etc" "$s/$sys/etc"
  printf '#!/bin/sh\n' > "$s/$sys/init"
  : > "$s/$km/lib/modules/$6/modules.builtin"
  printf '/dev/disk/by-uuid/%s / btrfs subvol=root 0 0\n/dev/disk/by-uuid/%s /boot ext4 defaults 0 2\n' \
    "$root_uuid" "$boot_uuid" > "$s/$fst/fstab"
  ln -s "/nix/store/$fst/fstab" "$s/$etcp/etc/fstab"
  mkfs.ext4 -q -F -U "$boot_uuid" -L AURORA_BOOT -d "$p/bootfs" "$p/boot.img" 16M
  truncate -s 160M "$p/root.img"
  if mkfs.btrfs --help 2>&1 | grep -q -- '--subvol'; then
    mkfs.btrfs -q -f -U "$root_uuid" -L aurora-root --rootdir "$p/rootfs" --subvol root "$p/root.img" >/dev/null
  else
    mv "$p/rootfs/root/nix" "$p/rootfs/nix"; rmdir "$p/rootfs/root"
    mkfs.btrfs -q -f -U "$root_uuid" -L aurora-root --rootdir "$p/rootfs" "$p/root.img" >/dev/null
  fi
  (cd "$p" && zip -q -r "$work/$name.zip" boot.img root.img esp)
}

expect() { # name expected_verdict failing_check
  local name=$1 want=$2 check=${3:-}
  set +e
  python3 "$checker" "$work/$name.zip" --stage2-sha256 "$patched" --esp-volume-id 0x1FE07AA4 \
    --receipt "$work/$name.json" > "$work/$name.out" 2>&1
  local rc=$?
  set -e
  local got; got=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["verdict"])' "$work/$name.json")
  if [[ $got != "$want" ]]; then echo "FAIL $name: verdict $got, wanted $want"; cat "$work/$name.out"; cat "$work/$name.json"; exit 1; fi
  if [[ $want == PASS && $rc -ne 0 ]] || [[ $want == FAIL && $rc -eq 0 ]]; then echo "FAIL $name: exit $rc"; exit 1; fi
  if [[ -n $check ]] && ! grep -q "^FAIL  $check$" "$work/$name.out"; then
    echo "FAIL $name: check $check did not fail"; cat "$work/$name.out"; exit 1
  fi
  echo "ok   $name -> $got${check:+ ($check)}"
}

make_payload good "$work/stage2-patched.bin" "$rel_a" "$rel_a" "$root_uuid" "$rel_a"
expect good PASS
make_payload stock-ctxr "$work/stage2-stock.bin" "$rel_a" "$rel_a" "$root_uuid" "$rel_a"
expect stock-ctxr FAIL stage2-active
make_payload stale-modules "$work/stage2-patched.bin" "$rel_a" 7.3.0 "$root_uuid" "$rel_a"
expect stale-modules FAIL kernel-release
grep -q '^FAIL  initrd-modprobe$' "$work/stale-modules.out" && echo "ok   stale-modules -> also initrd-modprobe"
make_payload closure-modules "$work/stage2-patched.bin" "$rel_a" "$rel_a" "$root_uuid" 7.3.0
expect closure-modules FAIL kernel-release
make_payload stale-uuid "$work/stage2-patched.bin" "$rel_a" "$rel_a" "$stale_uuid" "$rel_a"
expect stale-uuid FAIL root-identity
make_payload firstboot-no-exec "$work/stage2-patched.bin" "$rel_a" "$rel_a" "$root_uuid" "$rel_a" no-exec
expect firstboot-no-exec FAIL initrd-firstboot
make_payload firstboot-no-dmcrypt "$work/stage2-patched.bin" "$rel_a" "$rel_a" "$root_uuid" "$rel_a" no-dmcrypt
expect firstboot-no-dmcrypt FAIL initrd-firstboot
echo "ALL FIXTURE CASES PASS"
