# SUMMARY — coreboot for ASUS PRIME B360M-C

**Boot Guard: not provisioned in the vendor firmware.** The FIT (BIOS 3202) holds only
4 microcode entries: no Startup ACM, no Key Manifest, no Boot Policy Manifest. A board
with Boot Guard fused on could not boot this vendor image, so coreboot can run. The fuse
state itself was not read (`intelmetool -b` is on the capture list).

**Input gap: only the ASUS update capsule (`3202.CAP`) was provided.** There was no SPI
dump and none of the requested dumps (inteltool, lspci, superiotool, …). Everything
below comes from the vendor image, the manual or reference boards; DECISIONS.md lists
each value with its source and confidence.

**Hardware test log:**

- 2026-11-27: variant C (EDK2 + FSP GOP) flashed first; the owner reports it boots
  and works. So bootblock → romstage → FSP-M memory init → ramstage → FSP-S → EDK2
  → OS works with at least one DIMM and the display in use.
- 2026-11-27: variant E (C + HAP bit) also boots and works. So the HAP strap at
  PCHSTRP0[16] at least does not prevent booting. Whether it actually disables
  the ME (HECI 00:16.0 gone from `lspci`) is not yet confirmed.
- The per-feature checklist (BRINGUP.md §6) has not been reported yet. Until then
  the table below still says "unverified".

## What was built

- **coreboot:** main @ c49935a4 + 3 patches (`patches/`):
  1. `util/intelp2m: Add Cannon Lake PCH-H platform`. The `cnl` profile is LP-only and
     maps PADRSTCFG wrongly for PCH-H.
  2. `superio/nuvoton: Add NCT6793D`.
  3. `mb/asus: Add PRIME B360M-C`: board, documentation page and index entry.
- **ROMs (`out/`):** all variants build:
  - A: SeaBIOS + libgfxinit
  - B: SeaBIOS + FSP GOP
  - C: EDK2 + FSP GOP
  - D: A + HAP strap, **unverified location**
  - E: C + the same HAP strap (UEFI with ME disabled). Not committed; `build.sh`
    produces it.
  - Each as a full 16 MiB image plus a BIOS-region file.
- **Checks:** all pass (`scripts/check.sh`):
  - `util/abuild -t asus/b360m-c`
  - `util/lint lint-stable`
  - checkpatch: 0 errors / 0 warnings on all 3 patches (run with `--no-signoff`; you
    must add your own Signed-off-by)
  - `scripts/gpio_check.py`: 228 pads, 0 unexplained differences
- **Fresh clone:** `git clone` → `scripts/setup.sh && scripts/build.sh` built the
  toolchain and all four variants from scratch (DoD #1 verified).
- **Independent audit:** done (`AUDIT.md`). One blocker was found and fixed: ramstage
  would have enabled every NCT6793D logical device missing from the devicetree,
  including the deep-sleep power controls. The SPD-provenance comment was corrected,
  and eight nits were fixed or justified (DECISIONS.md, "Audit").
- **Image checks:** `build.sh` asserts the descriptor, ME and GbE regions are
  byte-identical to `blobs/`. The only exception is D, which differs in exactly one
  descriptor byte.
- **Tooling:**
  - `scripts/setup.sh` (pinned clone, needed submodules, patches, crossgcc toolchain,
    blobs)
  - `scripts/build.sh`
  - `scripts/vendor_gpio.py` → intelp2m → `scripts/gen_gpio_c.py` (GPIO pipeline)
  - `scripts/gpio_check.py` (also checks a real `inteltool -G` with `--dump`)
  - `scripts/extract_blobs.sh`, `extract_vbt.py`, `gbe_mac.py` (set your MAC in GbE),
    `set_hap.py`, `vbt_dump.py`

## Feature status

| Feature | Status | Source |
|---|---|---|
| Serial console COM1 0x3F8 115200 8N1 from bootblock | implemented, unverified | Super I/O identified from vendor SMBIOS + DSDT; pin-mux writes replayed from vendor PEI |
| POST codes port 0x80 (LPC_DEBUG header) | implemented | coreboot default |
| GPIO (all 228 pads) | from vendor GPIO table, unverified | board PEIM table, applied in bootblock |
| DDR4, 4 slots | implemented, unverified | SPD 0x50-0x53 = standard layout and vendor config-block default (runtime vendor policy unknown); RCOMP from asrock/h370m (reference) |
| HDMI, DP1, DP2 (libgfxinit) | implemented, unverified | DDI map from vendor VBT |
| VGA (D-Sub via DP→VGA on DDI E) | FSP GOP only (B/C), unverified | VBT; libgfxinit cannot drive it on this GPU generation |
| SATA ×6, M.2_1 (SATA/PCIe), M.2_2 | implemented, unverified | manual + SMBIOS; M.2 root ports left to FSP/straps |
| USB 12×USB2 / 6×USB3 | implemented, unverified; OC not used | port names from SMBIOS (mapping assumed 1:1) |
| I219-V LAN | implemented, unverified | PCH GbE + vendor GbE region |
| ALC887 audio (+ HDMI audio) | implemented, unverified | verbs copied from vendor |
| PCIe x16, x1 ×2, PCI (ASM1083) | implemented, unverified | SMBIOS type 9 (RP4, RP5, RP6) |
| PCIe clocks | all free-running, no CLKREQ# | safe default (mapping unknown) |
| S3 | enabled (`HAVE_ACPI_RESUME`), unverified | coreboot/FSP |
| COM2, LPT, PS/2 | implemented, unverified | vendor DSDT resources |
| Other Super I/O LDNs (ACPI, GPIO/WDT, deep sleep, port-80 UART) | left untouched (power-on state) | not exposed by the driver |
| Fan control / HWM | not implemented (power-on defaults) | safety rule: no vendor fan values |
| TPM header | not implemented | — |
| ME disable (HAP) | variants D (SeaBIOS) and E (EDK2), location unverified on CNP-H | me_cleaner `-S` convention |

## Top first-boot risks

1. **No console at all.** The Super I/O pin-mux writes or the COM header levels are
   wrong, or a TTL adapter is on an RS-232 header. BRINGUP §3/§4 row 0.
2. **Memory training failure** on some slots. The DIMM0/DIMM1-to-slot order within a
   channel is inferred from FSP defaults. BRINGUP §5 tests one DIMM per slot.
3. **GPIO table differences.** The vendor GPIO table is applied in bootblock, but
   RC/FSP changes some pads afterwards (CLKREQ#, possibly others) that are not in the
   table. CLKREQ is not used (clocks free-run), which keeps that risk low; fixing it
   needs a real `inteltool -G`.
4. **PCIe topology.** All 24 root ports are enabled and FSP prunes them. The M.2
   root ports and the GbE lane come from soft straps and were not mapped. An FSP-S
   hang or a missing NVMe would point here.
5. **Display on A.** HDMI and DP should work; VGA does not work with libgfxinit at
   all. Use B (FSP GOP) for VGA.

Also note:
- Fans run at the Super I/O power-on default, probably full speed.
- A full-image flash built from the capsule replaces your board's MAC with ASUS's
  placeholder. Flash BIOS-region only, or rebuild from your own dump / with `MAC=`.

## ROM SHA256

From `out/SHA256SUMS` (committed ROMs). D shares A's BIOS region and differs from
A only in descriptor byte 0x102 (the HAP bit). E (= C + the same bit) is not
committed; `build.sh` builds and checks it the same way.

```
54fcc12070279b5b03925ebb2e17b766302effda7c41b9fbd823caa24bb8fddc  asus_prime-b360m-c_A_seabios_libgfxinit.rom
2cda68b8862488f81e3e563ed6f0c2b8bd8ea1c7f76563b808dc1bcbeeaa8cdd  asus_prime-b360m-c_B_seabios_fspgop.rom
8628f0bb502a9796a25260c42d54b85ecdf9c11c9ee80256a802213de21eaac3  asus_prime-b360m-c_C_edk2_fspgop.rom
355cbe460f75d5e2c0e09b14ba3ad869ab01bfe9fc4d47526f4a2510e7bc3cb8  asus_prime-b360m-c_D_seabios_libgfxinit_ME_HAP_UNVERIFIED.rom
5b3f7fed707c6870f97c93df61a90da71d8b1e5ae5d9783ed178da7a6fab7368  asus_prime-b360m-c_A_seabios_libgfxinit.bios-region.bin
647e49f71886ff7720780d36c8f000ace4f8e18b61d783d1c8419a4f8a8fc5e2  asus_prime-b360m-c_B_seabios_fspgop.bios-region.bin
4357c02ecf0c5a25c1b475ca8aae4f35456e9c3c96a5c43bdc6d1b1d28211dee  asus_prime-b360m-c_C_edk2_fspgop.bios-region.bin
5b3f7fed707c6870f97c93df61a90da71d8b1e5ae5d9783ed178da7a6fab7368  asus_prime-b360m-c_D_seabios_libgfxinit_ME_HAP_UNVERIFIED.bios-region.bin
```

## Read first

**BRINGUP.md** (flash procedure, serial pinout/levels, console milestones, test list,
what to capture), then **DECISIONS.md**.
