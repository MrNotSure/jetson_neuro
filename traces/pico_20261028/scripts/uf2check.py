"""Check a UF2 file is an RP2040 image: magic numbers, family ID, block layout.

Standard library only. Usage: python3 uf2check.py <file.uf2>
"""
import struct
import sys

MAGIC0 = 0x0A324655
MAGIC1 = 0x9E5D5157
MAGIC_END = 0x0AB16F30
FAMILY_RP2040 = 0xE48BFF56
FLAG_FAMILY_PRESENT = 0x00002000
# Other RP2350 family IDs, so a wrong image is named explicitly.
KNOWN_FAMILIES = {
    0xE48BFF56: "RP2040",
    0xE48BFF57: "absolute (RP2350 bootrom)",
    0xE48BFF58: "data",
    0xE48BFF59: "RP2350 ARM secure",
    0xE48BFF5A: "RP2350 RISC-V",
    0xE48BFF5B: "RP2350 ARM non-secure",
}


def parse(block):
    m0, m1, flags, addr, size, blockno, nblocks, fam = struct.unpack_from("<8I", block, 0)
    (mend,) = struct.unpack_from("<I", block, 508)
    return dict(m0=m0, m1=m1, flags=flags, addr=addr, size=size,
                blockno=blockno, nblocks=nblocks, family=fam, mend=mend)


def main(path):
    data = open(path, "rb").read()
    print(f"file: {path}")
    print(f"size: {len(data)} bytes, {len(data) / 512:.3f} blocks of 512")
    first = parse(data[:512])
    print("first block:")
    print(f"  magicStart0 = 0x{first['m0']:08X}  expected 0x{MAGIC0:08X}  {'OK' if first['m0'] == MAGIC0 else 'FAIL'}")
    print(f"  magicStart1 = 0x{first['m1']:08X}  expected 0x{MAGIC1:08X}  {'OK' if first['m1'] == MAGIC1 else 'FAIL'}")
    print(f"  magicEnd    = 0x{first['mend']:08X}  expected 0x{MAGIC_END:08X}  {'OK' if first['mend'] == MAGIC_END else 'FAIL'}")
    print(f"  flags       = 0x{first['flags']:08X}  familyID-present bit {'set' if first['flags'] & FLAG_FAMILY_PRESENT else 'NOT set'}")
    fam_name = KNOWN_FAMILIES.get(first["family"], "unknown")
    print(f"  familyID    = 0x{first['family']:08X} ({fam_name})  expected 0x{FAMILY_RP2040:08X}  {'OK' if first['family'] == FAMILY_RP2040 else 'FAIL'}")
    print(f"  targetAddr  = 0x{first['addr']:08X}")
    print(f"  payloadSize = {first['size']}")
    print(f"  blockNo     = {first['blockno']} of numBlocks {first['nblocks']}")

    # Whole-file consistency: every block well-formed, same family, contiguous numbering,
    # target addresses inside the RP2040's XIP flash window (0x10000000..0x11000000).
    ok = len(data) % 512 == 0
    lo, hi = None, None
    families = set()
    for i in range(len(data) // 512):
        b = parse(data[i * 512:(i + 1) * 512])
        if b["m0"] != MAGIC0 or b["m1"] != MAGIC1 or b["mend"] != MAGIC_END:
            print(f"  block {i}: bad magic"); ok = False
        if b["blockno"] != i or b["nblocks"] != first["nblocks"]:
            print(f"  block {i}: numbering {b['blockno']}/{b['nblocks']}"); ok = False
        families.add(b["family"])
        lo = b["addr"] if lo is None else min(lo, b["addr"])
        hi = b["addr"] + b["size"] if hi is None else max(hi, b["addr"] + b["size"])
    print("all blocks:")
    print(f"  count {len(data) // 512}, numBlocks field {first['nblocks']}, match {'OK' if len(data) // 512 == first['nblocks'] else 'FAIL'}")
    print(f"  families seen: {', '.join(f'0x{f:08X}' for f in sorted(families))}")
    print(f"  address range 0x{lo:08X}..0x{hi:08X} ({(hi - lo) / 1024:.1f} KiB)")
    in_flash = 0x10000000 <= lo and hi <= 0x11000000
    print(f"  inside RP2040 XIP flash window: {'OK' if in_flash else 'FAIL'}")
    # Look for the version banner in the payload (informational).
    payload = b"".join(data[i * 512 + 32:i * 512 + 32 + 476] for i in range(len(data) // 512))
    for needle in (b"v1.29.0", b"Raspberry Pi Pico W", b"Raspberry Pi Pico2", b"RP2350", b"Raspberry Pi Pico with RP2040"):
        print(f"  payload contains {needle.decode()!r}: {needle in payload}")
    all_ok = (ok and first["m0"] == MAGIC0 and first["m1"] == MAGIC1 and first["mend"] == MAGIC_END
              and first["flags"] & FLAG_FAMILY_PRESENT and first["family"] == FAMILY_RP2040
              and families == {FAMILY_RP2040} and in_flash)
    print("RESULT:", "PASS (RP2040 UF2)" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
