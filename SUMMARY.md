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

- **2026-11-27, variant C (EDK2 + FSP GOP):** boots Arch Linux.
- **2026-11-27, variant E (C + PCHSTRP0[16]):** boots too. It was written as a full
  image, so the capsule's GbE region (placeholder MAC) is on the board. The owner's
  captures are in `board-data/dumps/coreboot/2026-11-27-E/` and show:
  - **Boot path:** bootblock → romstage → FSP-M (MRC cache) → ramstage → FSP-S →
    EDK2 → Linux, with one DIMM.
  - **GPIO:** `gpio_check.py --dump` finds 2 differences on 228 pads.
    - GPP_J1 becomes `CPU_C10_GATE#`, set by FSP (`PmcCpuC10GatePinEnable`, default
      on).
    - GPP_A12 has its receive buffer switched off later in boot.
    - Neither drives a pin wrongly.
  - **PCIe:** FSP keeps RP6 (ASM1083 → PCI slot), RP7 and RP8 (x1, no link), RP9
    (x4, NVMe at 8 GT/s x4) and RP21 (x4, no link). That is 11 lanes; with the GbE
    lane it's B360's 12.
    - RP4 and RP5, which the vendor SMBIOS gives for the x1 slots, have no lanes, so
      the x1 slots are RP7/RP8 (labels moved, TODO confirm with a card).
    - The M.2 sockets: M.2_1 is RP9 (owner confirmed); M.2_2 is RP21, the only
      other x4 port.
  - **Working:** I219-V link with traffic (placeholder MAC), the ALC887 codec, USB
    (keyboard/mouse via a hub on USB2 port 10), HDMI, and all 6 AHCI ports.
  - **The ME still ran normally** (HECI 00:16.0 present, operation mode 0). So
    PCHSTRP0[16] is **not** the HAP bit on CNP-H, and variants D/E were removed. The
    ME can now be disabled with the `me_state` option (BRINGUP §9).
  - C with `me_state=Disable` set through nvramtool: ME in Soft Temporary Disable
    (HFSTS1 0x80032044, mode 3, error 2), and HECI is hidden.
    Capture: `board-data/dumps/coreboot/2026-11-27-C-me_state/`.
  - **Two issues found and fixed:**
    - i915 warned that DDI E (VGA) had 0 lanes. The board now selects
      `SOC_INTEL_GFX_ENABLE_DDI_E_BIFURCATION`.
    - "LPC IO decode base 0!" came from an empty HWM I/O resource, which is no
      longer assigned.

## What was built

- **coreboot:** main @ c49935a4 + 3 patches (`patches/`):
  1. `util/intelp2m: Add Cannon Lake PCH-H platform`. The `cnl` profile is LP-only and
     maps PADRSTCFG wrongly for PCH-H.
  2. `superio/nuvoton: Add NCT6793D`.
  3. `mb/asus: Add PRIME B360M-C`: board, documentation page and index entry.
- **ROMs (`out/`):**
  - A: SeaBIOS + libgfxinit
  - B: SeaBIOS + FSP GOP
  - C: EDK2 + FSP GOP (hardware-tested)
  - Each as a full 16 MiB image plus a BIOS-region file.
- **Checks:** all pass (`scripts/check.sh`):
  - `util/abuild -t asus/b360m-c`
  - `util/lint lint-stable`
  - checkpatch: 0 errors / 0 warnings on all 3 patches (run with `--no-signoff`; you
    must add your own Signed-off-by)
  - `scripts/gpio_check.py`: 228 pads, 0 unexplained differences
- **Fresh clone:** `git clone` → `scripts/setup.sh && scripts/build.sh` built the
  toolchain and all variants from scratch (DoD #1 verified, also on Arch Linux).
- **Independent audit:** done (`AUDIT.md`). One blocker was found and fixed: ramstage
  would have enabled every NCT6793D logical device missing from the devicetree,
  including the deep-sleep power controls. The SPD-provenance comment was corrected,
  and eight nits were fixed or justified (DECISIONS.md, "Audit").
- **Image checks:** `build.sh` asserts the descriptor, ME and GbE regions are
  byte-identical to `blobs/`.
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
| DDR4, 4 slots | **1 DIMM works in DIMM_B2** (SPD 0x53, confirmed); DIMM_A1/A2/B1 unverified | SPD 0x50-0x53 = standard layout and vendor config-block default (runtime vendor policy unknown); RCOMP from asrock/h370m (reference) |
| HDMI, DP1, DP2 | **HDMI works** (FSP GOP + i915); DP and libgfxinit unverified | DDI map from vendor VBT |
| VGA (D-Sub via DP→VGA on DDI E) | FSP GOP only (B/C); DDI E lanes fixed for i915; unverified | VBT; libgfxinit cannot drive it on this GPU generation |
| SATA ×6, M.2 (RP9, RP21) | **NVMe x4 works in M.2_1 (RP9)**; AHCI 6 ports up; disks/SATA-M.2 unverified | hardware lspci |
| USB 12×USB2 / 6×USB3 | **works** (port 10 confirmed); full map unverified; OC not used | port names from SMBIOS (mapping assumed 1:1) |
| I219-V LAN | **works** (link + traffic) | PCH GbE + vendor GbE region |
| ALC887 audio (+ HDMI audio) | **codec detected and configured**; playback unverified | verbs copied from vendor |
| PCIe x16, x1 ×2, PCI (ASM1083) | **ASM1083 enumerates (RP6)**; x1 slots on RP7/RP8 (inferred); x16 unverified | hardware lspci + SMBIOS |
| PCIe clocks | all free-running, no CLKREQ# | safe default (mapping unknown) |
| S3 | enabled (`HAVE_ACPI_RESUME`), unverified | coreboot/FSP |
| COM2, LPT, PS/2 | implemented, unverified | vendor DSDT resources |
| Other Super I/O LDNs (ACPI, GPIO/WDT, deep sleep, port-80 UART) | left untouched (power-on state) | not exposed by the driver |
| Fan control / HWM | not implemented (power-on defaults) | safety rule: no vendor fan values |
| TPM header | not implemented | — |
| ME disable | `me_state` option (HECI soft disable), **works** (CMOS backend tested). C: setup menu (CFR, untested); A/B: nvramtool. HAP strap bit **did not work** | coreboot CSE common code |

## Top first-boot risks

1. **No console at all.** The Super I/O pin-mux writes or the COM header levels are
   wrong, or a TTL adapter is on an RS-232 header. BRINGUP §3/§4 row 0.
2. **Memory training failure** on some slots. DIMM_B2 is confirmed (SPD 0x53); the
   other slots follow by symmetry. BRINGUP §5 tests one DIMM per slot.
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

From `out/SHA256SUMS`.

```
b299a73840d9f905bcbcc447196d7f86835c16ba19d52fa3a037f8a113537763  asus_prime-b360m-c_A_seabios_libgfxinit.rom
4c6ce80f1e2dcb0cec4aa06ff630a60c49971fc28e00dc7ee7fed0e4905e788e  asus_prime-b360m-c_B_seabios_fspgop.rom
24e21d8b60b75b56bcafdea31c3ad9811473dbda09d8bcdb627aa4cf3ff61d1b  asus_prime-b360m-c_C_edk2_fspgop.rom
7c1bbd9c73d58357bcd56d5fb2e080eec722dd150587a21faf738d724f35668e  asus_prime-b360m-c_A_seabios_libgfxinit.bios-region.bin
f46704aa4eb884be24ab3705ecaab876db5c4b06d19ebd5acff06e140fd51282  asus_prime-b360m-c_B_seabios_fspgop.bios-region.bin
31d290c79e21699861096d6e1e8b271e315f7ce40dda5bcd84073a8b56c147ad  asus_prime-b360m-c_C_edk2_fspgop.bios-region.bin
```

## Read first

**BRINGUP.md** (flash procedure, serial pinout/levels, console milestones, test list,
what to capture), then **DECISIONS.md**.
