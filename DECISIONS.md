# DECISIONS — ASUS PRIME B360M-C coreboot port

Every assumption, and every value that does not come straight from your hardware,
is listed here with its source, a confidence level and how to check it on the board.

Confidence: **H** high (vendor firmware is unambiguous, or Intel docs/spec),
**M** medium (one indirect source, or reference-board convention),
**L** low (best guess, chosen to be the safe option).

"Vendor image" always means `board-data/vendor/PRIME-B360M-C-ASUS-3202.CAP`
(BIOS 3202, 2021-07-10). It is the only input that was provided.

## D-000 Input gap: no hardware dumps at all — H

- **Situation:** `board-data/` held no `notes.md`, no `dumps/` and no external-programmer
  dump. The only upload was the ASUS update capsule (`.CAP` plus `BIOSRenamer.exe`, which
  I deleted).
- **What I did:** derived everything I could from the vendor image instead
  (descriptor, ME, GbE, VBT, GPIO table, HDA verbs, Super I/O init, SMBIOS slot and port
  tables, DSDT). Everything else comes from reference boards or is set to a safe default,
  and the entries below say which.
- **Verify:** bring the dumps listed in BRINGUP.md §7, especially
  `inteltool -G`, `lspci -nnvvv -t`, `superiotool -deV` and the external SPI dump.

## D-001 Capsule = full SPI image — H

- **Finding:** the `.CAP` is a 0x800-byte AMI capsule header followed by a complete
  16 MiB image. The flash descriptor signature sits at 0x810.
- **Use:** `scripts/extract_blobs.sh` strips the header and extracts the regions to
  `blobs/`.
- **Source priority:** if you drop your own 16 MiB programmer dump (`*.bin` or `*.rom`)
  into `board-data/vendor/`, it is used instead of the capsule.

## D-002 GbE region from the capsule is a template — H

- **Finding:** the capsule's GbE region has the ASUS placeholder MAC `88:88:88:88:87:88`.
  The NVM checksum word (0x3F) is `0xFFFF`; with the "checksum valid" bit (word 0x03
  bit 0) clear, Linux e1000e recomputes the checksum on first probe.
- **Consequence:** flashing a full image built from the capsule replaces your board's
  real MAC with the placeholder. LAN should still work, but every board built this way
  gets the same MAC.
- **Mitigation:**
  1. Flash the BIOS region only (keeps your IFD, ME and GbE). This is the default
     procedure in BRINGUP.md.
  2. Or put your SPI dump into `board-data/vendor/`.
  3. Or build with `MAC=<sticker MAC> scripts/build.sh`; `scripts/gbe_mac.py` sets the
     MAC and fixes the checksum.

## D-003 Flash descriptor left byte-identical — H

- **Finding:** coreboot's default `UNLOCK_FLASH_REGIONS` rewrote FLMSTR1-5 to
  `0xffffffff`.
- **Decision:** set `CONFIG_DO_NOT_TOUCH_DESCRIPTOR_REGION=y`. `scripts/build.sh`
  checks that the descriptor in every ROM is byte-identical to `blobs/descriptor.bin`.
- **Exception:** variant D, where exactly one byte (the HAP strap) may differ, and the
  build checks that too.
- **Consequence:** host write access stays as the vendor set it (IFD and ME read-only,
  BIOS and GbE writable). Internal flashing works only for the BIOS region; a full image
  needs the external programmer.

## D-004 ME firmware — H

- **Finding:** CSME 12.0.64.1551 (consumer), taken unmodified from the capsule.
- **Difference from your board:** your board's ME region also holds runtime state in MFS.
  The capsule's copy is factory-fresh, so a full-image flash resets ME state (harmless
  for coreboot).
- **Variant D:** `me_cleaner -S` sets only the HAP bit and does not touch the ME
  partitions.

## D-005 Boot Guard — H (for "not provisioned in firmware")

- **Finding:** the FIT has 1 header plus 4 microcode entries. There is no Startup ACM
  (type 2), no Key Manifest (0x0B) and no Boot Policy Manifest (0x0C).
- **Reasoning:** a board with Boot Guard fused on cannot boot without an ACM, KM and BPM.
  The vendor firmware boots, so verified/measured Boot Guard is not active.
- **Not checked:** the fuse state (`intelmetool -b`). Please bring it.

## D-006 GPIO table source — M-H

- **Source:** board PEIM `2accd044-284c-432f-9a1a-4cde31036c9f` (4 KiB, ASUS) holds a
  228-entry `GPIO_INIT_CONFIG[]` in Intel Coffee Lake RC format that covers every CNP-H
  pad exactly once. The identical table appears at flash 0xF6258C and 0xFE258C (main and
  backup PEI FV).
  - The PEIM depends only on the PCD PPI, so it runs early in PEI (pre-memory).
  - A second module, `3eaf5e3a…`, holds Intel CRB tables (scattered pads, several
    boards). These are not used.
- **Conversion:** `scripts/vendor_gpio.py` turns each entry into DW0/DW1/HOSTSW_OWN the
  way RC `GpioConfigurePad()` does, and writes a mask of the bits the table really
  determines.
  - Inputs: pad encoding and enum values from Intel's `GpioPinsCnlH.h` and
    `GpioConfig.h` (Slim Bootloader copies).
  - Output: a synthetic inteltool-format dump, `board-data/dumps/inteltool-G-synthetic.txt`.
  - That dump goes through util/intelp2m with the new `cnl-h` platform, then
    `scripts/gen_gpio_c.py` (restores DRIVER ownership).
- **Unknowns:**
  - Fields the vendor leaves at "default" keep their hardware reset value, which I don't
    know without a dump. In practice that is RXEVCFG for GPIO inputs (assumed `OFF`,
    affects only interrupt edge detection; routing is disabled).
  - RC/FSP reconfigures some pads after this table (e.g. CLKREQ#, see D-012). Those
    changes are not in the vendor table.
- **Verify:** `inteltool -G` under vendor firmware, then
  `scripts/gpio_check.py --dump <file>`.

## D-007 GPIO programming time — M

- **Decision:** the whole table is applied in `bootblock_mainboard_init()`, right after
  the COM1 console is up.
- **Why:** the vendor PEIM is pre-memory, and every SMBus/LPC pad in the table keeps its
  native function, so console and SPD reads are unaffected.

## D-008 intelp2m `cnl` is wrong for PCH-H — H

- **Finding:** the `cnl` platform models CNL-LP. Its PADRSTCFG remap gives wrong reset
  sources for GPP_A, GPP_B, GPP_G and GPD on PCH-H.
- **Decision:** add `-p cnl-h` (patch 0001). The correct maps come from
  `soc/intel/cannonlake/gpio_cnp_h.c`.

## D-009 Super I/O = Nuvoton NCT6793D @ 0x2E — H

- **Identification:**
  - SMBIOS type 34 says "Nuvoton NCT6793D".
  - DSDT `SIO1`: `SP1O=0x2E`, entry key 0x87, exit key 0xAA, HWM `IO3B/IOHW=0x290`
    length 0x10.
  - DSDT `DCAT`: LDN map UART A=2, UART B=3, LPT=1, KBC=5, CIR=6.
- **Driver:** new `superio/nuvoton/nct6793d` (patch 0002), modeled on nct6796d.
  - `pnp_dev_info` lists only the logical devices with I/O resources: LPT, UART A/B,
    KBC, CIR, HWM and CIR wake-up. This came out of the audit (A-1).
  - Reason: coreboot creates and *enables* every `pnp_dev_info` entry the devicetree
    does not list. The other LDNs (ACPI 0x0A, WDT/GPIO groups 0x07-0x09/0x0D/0x0F,
    LDN 0x12, port-80 UART 0x14, deep-sleep 0x16) are therefore not exposed and keep
    their power-on state.
  - The header still defines them; the bootblock programs LDN 0x12 CR EB directly,
    as the vendor does.

## D-010 Super I/O early init copied from vendor PEI — H

- **Source:** vendor PEIM `9029f23e…` table (AMI `{port, and, or}` triplets), decoded:
  - CR27: clear bit 2, set bit 4
  - CR2A: clear bit 6 and bits 1:0
  - CR2F: clear bit 1
  - LDN12 CRE B: clear bits 5:4
  - KBC 0x60/0x64, IRQ1
  - UART A 0x3F8
- **Also:** the AMI status-code modules clear CR2A bit 7 (UART A pin routing), which is
  exactly what `SUPERIO_NUVOTON_COMMON_COM_A` does.
- **Decision:** the bootblock replays these writes. No other global CRs are touched.
- **Unknown:** what each pin-mux bit means without the datasheet. Keeping the vendor
  values is the safe choice.

## D-011 Hardware monitor / fans — H (safety rule)

- **Finding:** no vendor fan register values could be extracted (the SIO DXE driver has
  no recognisable table).
- **Decision:** the HWM LDN only gets its base address (0x290, as in the vendor DSDT).
  No SmartFan / PECI programming happens, so fans run with Nuvoton power-on defaults
  (normally full speed). Expect it to be loud.
- **Verify:** fans spin at boot; `sensors` under Linux.

## D-012 PCIe clocks: all free-running, no CLKREQ — L (safe default)

- **Problem:** the CLKSRC → root port / GbE mapping is set at runtime by AMI code and is
  not in any table I could find. The vendor GPIO table leaves `SRCCLKREQ#` pads
  (GPP_B5-B10, GPP_H0-H9) as GPIO inputs; RC switches the used ones to native later.
- **Decision:** `PcieClkSrcUsage[0..15] = PCIE_CLK_FREE`,
  `PcieClkSrcClkReq[*] = PCIE_CLK_NOTUSED`. Every reference clock runs all the time.
- **Effect:** every device gets a clock whatever the routing. The cost is no
  CLKREQ-based power management (no L1 substates) and slightly more power and EMI.
- **Verify:** `inteltool -G` under vendor firmware (CLKREQ pads that are native = used),
  plus `lspci -vv` LnkCtl/L1SS.

## D-013 Root ports: all 24 enabled — M

- **Known:** vendor SMBIOS type 9 gives PCIEX16=00:01.0, PCIEX1_1=00:1c.3 (RP4),
  PCIEX1_2=00:1c.4 (RP5), PCI slot=00:1c.5 (RP6, ASM1083 bridge).
- **Unknown:** the M.2_1/M.2_2 root ports and the GbE lane.
- **Decision:** all RP1-24 are enabled. The soft straps decide lane ownership, and FSP
  disables ports without lanes or links (the AMI default also enables all RPs). Slot
  descriptors are set for RP4, RP5 and PEG.
- **Verify:** `lspci -tv` under vendor firmware.

## D-014 USB port map — M; over-current mapping — L

- **Port names:** from vendor SMBIOS type 8 and the manual: U31G2_12/U31G2_34 (rear Gen2),
  U31G1_56 (header), USB78 (header), LAN_USB910 (rear), USB1112 (header). I assumed they
  map 1:1 to PCH USB2 ports 1-12 and USB3 ports 1-6, which is ASUS's naming practice and
  matches the B360 maximum of 12 USB2 / 6 USB3.
- **OC pins:** OC0-OC5 are native in the GPIO table, but the port → OC mapping is unknown,
  so all ports use `OC_SKIP`. The ports still get power; the board's power switches
  limit current in hardware, but the OS won't see OC events.
- **Tuning:** `USB2_PORT_MID` / `USB3_PORT_DEFAULT` (FSP defaults, no RVP tuning).
- **Verify:** plug a device into each port and compare with `lsusb -t`.

## D-015 SATA — H/M

- **Finding:** 6 ports (SATA6G_1-6 = ports 0-5) per the manual and SMBIOS. M.2_1 in SATA
  mode shares SATA6G_2 (manual).
- **Decision:** all 6 ports enabled. No hot-plug, no DevSleep (DEVSLP0/1 pads are native
  per the vendor table, but DevSleep stays off as the safe default).

## D-016 Memory: SPD 0xA0/0xA2/0xA4/0xA6 — L/M (corrected after audit A-2)

- **Finding:** four DDR4 UDIMM slots (DIMM_A1/A2/B1/B2, 2DPC).
  - The vendor FSP-M default UPD has an **empty** SPD table.
  - The vendor runs FSP in dispatch mode. Its platform PEIM `eeee611d` holds a
    config-block default `{0xA0,0xA2,0xA4,0xA6}`, and a setup-driven policy-update path
    that can copy `{0xA2,0xA0,0xA2,0xA0}` instead (that table is selected by board ID).
  - Which one this board ends up with could not be established from the image.
- **Decision:** spd[0..3] = Ch A DIMM0, Ch A DIMM1, Ch B DIMM0, Ch B DIMM1.
- **Rcomp / DQ / CA:** `rcomp_resistor {121,75,100}`, `rcomp_targets {60,26,20,20,26}`,
  `dq_pins_interleaved=1`, `vref_ca_config=2`. These are the CFL-S desktop values used
  by asrock/h370m-itx_ac. The same values are one of the Intel desktop RVP entries in
  the vendor module `1051ec65` (also board-ID selected) — M.
- **Safety:** SPD is read-only SMBus. A wrong mapping means no memory or swapped
  DIMM0/DIMM1 ODT, not damage.
- **Verify:** see BRINGUP.md §5 (one DIMM in each slot alone; `decode-dimms` addresses
  under vendor firmware).

## D-017 Display: VBT and DDI mapping — H

- **VBT:** IntelGopVbt FFS file `56752da9…` (`$VBT SKYLAKE`, BDB 221, 4449 bytes),
  copied unmodified as `data.vbt`. The legacy VBIOS option ROM's own VBT (BDB 209) has the
  same child devices.
- **DDI mapping:**
  - DDI B = DP1 (DP++, AUX B)
  - DDI C = DP2 (DP++, AUX C)
  - DDI D = HDMI
  - DDI E = DP-only on AUX A, i.e. the DP-to-VGA converter feeding the D-Sub port
- **Note:** the manual (rev 3) lists 2×DP + HDMI + D-Sub on the rear panel.

## D-018 libgfxinit and VGA — M

- **Port list:** HDMI3, DP1, DP2, HDMI1, HDMI2.
- **VGA:** not supported by libgfxinit on this GPU generation.
  - `Valid_Port(Analog)` needs `Has_PCH_DAC`, which is false for Skylake-family GPUs.
  - On CNP, `PCH_DAC` has no GMBUS pin pair.
  - So `Analog` was removed from the list (audit A-4). VGA output therefore needs FSP
    GOP (variant B/C).

## D-019 HDA verbs — H

- **Source:** vendor HDA verb PEIM `60c33d7a…`, copied verbatim:
  - subsystem 1043:86ca
  - AFG reset ×4
  - pin configs for NID 0x11-0x1f
  - coefficient 0x07=0x09c8 on NID 0x20 (written twice, as the vendor does)
- **Not used:** the alternative pin sets in the same module (other front-panel modes).
- **iDisp codec:** the vendor has no verb table for it, so coreboot has none either.

## D-020 ACPI — M

- **Decision:** a standard CNL DSDT, plus the Super I/O SSDT generated by the
  `superio/common` generator (COM1, COM2, LPT, PS/2).
- **From the vendor DSDT:** nothing board-specific besides the SIO data. Its GPE
  handlers are generic Intel RC. GPE0 group routing (GPP_C/K/E) is taken from H370M.
  - GPP_D23 is SCI-armed exactly as in the vendor table, but GPP_D is not mapped to
    GPE0 and no handler exists in either DSDT. It is an input, so this is harmless
    (audit A-3).

## D-021 CPU power / VR — H

- **Decision:** no overrides.
  - PL1 = TDP, PL2 = 1.25×TDP (Intel default, coreboot common code).
  - IccMax comes from the CFL-S datasheet table in `soc/intel/cannonlake/vr_config.c`.
  - TCC offset 0; PROCHOT/THERMTRIP untouched (FSP defaults).
- No overclocking, no undervolting.

## D-022 SLP_Sx assertion widths, power-fail state — H

- **Decision:** not set, so FSP defaults apply. After power loss the board stays off
  (coreboot default).

## D-023 TPM — not implemented

- The LPC TPM header is not enabled in this first image (priority 11).

## D-024 Toolchain — H

- **Used:** coreboot crossgcc at commit c49935a4 (GCC 15.2.0, binutils 2.46.1, NASM 3.02,
  IASL 20251212).
- **How:** `make crossgcc-i386 CPUS=4 BUILDGCC_OPTIONS=-m` (the `-m` flag uses the
  coreboot tarball mirror because github.com is blocked here), plus `make iasl`. Host:
  Ubuntu 24.04 gcc/gnat 13.3.
- The Docker SDK fallback was not needed.
- **Arch Linux:** `scripts/setup.sh` installs packages with pacman (`gcc-ada`
  provides GNAT), and `scripts/build-arch.sh` wraps setup + build.
  - Verified in a clean Arch container (host GCC/GNAT 16.2.1): the crossgcc 15.2
    toolchain and all variants A-D build.
  - The EDK2 payload needs ImageMagick (`convert`) for the boot logo. It is now in
    both package lists.

## D-025 EDK2 (variant C) — H

- **Built:** variant C uses coreboot's default EDK2 payload (MrChromebox fork,
  UefiPayloadPkg) + FSP GOP.
- **Network:** github.com web pages return 403 from this VM, but git over HTTPS works.
  So `build.sh` checks with `git ls-remote` and only skips C (writing
  `out/*_C_*.SKIPPED.txt`) when GitHub is really unreachable.
- **Footprint:** the EDK2 clone with recursive submodules is about 7 GB.

## D-026 coreboot pin — H

- **Pin:** `main` @ c49935a44f99585488dec654bd4f3eefe262160c (2026-11-26).
- **Patches:** the series in `patches/` applies on top of it.

## D-027 Signed-off-by / trailers — H

- The patches carry no `Signed-off-by:`. The DCO is a statement only you can make.
  `git commit --amend -s` each patch before you send it to Gerrit.
- checkpatch runs with `--no-signoff` for that reason.
- The AI attribution trailer is written `Co-authored-by:` (checkpatch's preferred
  casing) in the coreboot series.

## D-028 Variant D: HAP bit location on CNP-H — L/M (unverified)

- **Asked for:** "variant A with me_cleaner (HAP)".
- **Blockers:**
  - coreboot's `USE_ME_CLEANER` Kconfig does not support Cannon/Coffee Lake.
  - me_cleaner (in-tree and upstream master) cannot parse CSME 12 images: it requires
    `$FPT` at ME+0x0/0x10, but this image starts with a CSE layout table and its FPT
    is at +0x20E000.
  - coreboot's ifdtool has a per-platform HAP table without CNL and reports "HAP bit
    location not known for platform".
- **What I did:** `scripts/set_hap.py` does exactly what `me_cleaner -S` does for any
  ME >= 11: set PCHSTRP0 bit 16, nothing else. It is applied to variant A's finished
  ROM, so A and D differ in exactly one byte (descriptor offset 0x102, bit 0 = PCHSTRP0 bit 16; checked by
  build.sh).
- **Why not skip D:** the vendor PCHSTRP0 is 0x00000000. This strap word is the CSME
  strap word on SPT/KBP. The expected failure mode of a wrong bit is "no boot / ME
  error", which your programmer recovers. No I/O-voltage strap is known to live in
  this word.
- **Naming:** `_ME_HAP_UNVERIFIED`. Test D last.
- **Variant E:** the same strap change applied to variant C (EDK2), added on request.
  `build.sh` checks that E differs from C in exactly that byte and that its BIOS
  region is identical to C's.
- **Verify:** HECI (00:16.0) disappears and the coreboot log reports the ME
  disabled. If D does not boot, reflash A: that proves the location is wrong.

## D-029 Super I/O LPT DMA, COM2, LPT, PS/2 enabled — M

- **Settings:**
  - LPT: 0x378, IRQ 7, no DMA (DRQ 4 = none).
  - COM2: 0x2F8, IRQ 3.
  - PS/2: 0x60/0x64, IRQ 1/12.
- **Source:** the vendor DSDT `_PRS`.
  - `UAR2` prefers 0x2F8/IRQ 3.
  - `LPTE` prefers 0x378/IRQ 5 and allows IRQ 5,6,7,9-12. I kept the legacy IRQ 7,
    which is in that list.
  - The KBC setup (0x60/0x64, IRQ 1) is the same as the vendor PEI.
- Enabling these logical devices does not change pin multiplexing, which only the
  global CRs of D-010 do.

## Audit (Phase 5) — findings and resolution

- **Auditor:** an independent subagent with no access to my reasoning. It re-derived the
  facts from the vendor image.
- **Full report:** `AUDIT.md`; the findings are summarised here.
- **Independently confirmed:**
  - **GPIO:** the right table (applied by `eeee611d` before memory init); 228/228 pads
    match; no GPIO outputs.
  - **Super I/O:** the bootblock writes are byte-identical to the vendor PEI table;
    no fan register writes.
  - **Other data:** slots, HDA verbs and VBT/DDI mapping match the vendor.
  - **Regions and config:** IFD, ME and GbE are identical in A/B/C, and D changes only
    the HAP bit. No power, voltage or thermal overrides.

| # | Severity | Finding | Resolution |
|---|---|---|---|
| A-1 | BLOCKER | Super I/O LDNs that the devicetree does not list (ACPI, GPIO/WDT groups, LDN 0x12, port-80 UART, deep-sleep VLDNs) were allocated *enabled* by ramstage and their CR30 bits written. The vendor never touches them. | **Fixed.** The driver exposes only the LDNs with I/O resources; the devicetree lists all of them (CIR and CIR wake-up `off`). The generated `static.c` now holds exactly 2e.0/1/2/3/5/6/b/e. Writing `off` to CIR/CIR wake-up assumes their power-on default is off — verify with `superiotool -deV`. |
| A-2 | SHOULD-FIX | The romstage.c comment claimed the SPD table came from the vendor FSP-M defaults; it does not. | **Fixed.** Comment reworded and TODO added; D-016 corrected and downgraded to L/M. Values unchanged (standard, harmless). |
| A-3 | NIT | GPP_D23 is SCI-armed but routes nowhere. | **Kept** (vendor-identical, input only); the devicetree comment now says so. |
| A-4 | NIT | `Analog` in gma-mainboard.ads never works on this generation. | **Fixed.** Removed from the list; docs say VGA needs FSP GOP. |
| A-5 | NIT | USB uses OC_SKIP although OC0-5 pads are native. | **Kept.** The mapping is unknown (D-014). |
| A-6 | NIT | The vendor locks its GPIO pads; coreboot leaves them unlocked. | **Kept.** This is hardening only and has no functional effect. Add locks after the table is verified on hardware. |
| A-7 | NIT | Full ROMs carry the capsule's placeholder MAC and factory ME. | **Documented** (D-002, BRINGUP §0/§2). Rebuild from your dump, or use `MAC=`. |
| A-8 | NIT | gpio_check.py did not report fields coreboot writes as 0 where the vendor keeps the reset value. | **Fixed.** They are now listed per field as "assumed 0, confirm with --dump"; there are still 0 unexplained differences. |
| A-9 | NIT | USB connector labels in the devicetree are assumptions. | **Fixed.** The comments now say so (TODO verify). |
| A-10 | NIT | All PCIe clocks free-running. | **Kept** (D-012, the safe default). |
