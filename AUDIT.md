# Independent audit report (Phase 5)

> Written by an independent reviewer agent against the port *before* the audit fixes
> (findings A-1 to A-10). The resolution of each finding is in DECISIONS.md, section "Audit".
> Line numbers refer to that earlier revision.

# Independent audit: coreboot port for ASUS PRIME B360M-C

Scope: `src/mainboard/asus/b360m-c/`, `src/superio/nuvoton/nct6793d/`, `util/intelp2m/platforms/cnlh/`, `patches/`, `scripts/`, `out/`, `build/{A,B,C,D}`.
Method: I re-derived the facts from the vendor image (BIOS 3202) myself, with my own decoders: GPIO_INIT_CONFIG bitfields, the TE/PE disassembly (ndisasm), the SMBIOS, the VBT and the SIO init tables. I used the porter's derived data only for cross-checking. Nothing under `/home/user/ACoreboot` was modified (`git status` is clean).

Note on addresses: "file X" means an offset inside the extracted section file. Volume offsets in `parse.txt` are relative to the BIOS region, which starts at SPI 0x300000, so the BIOS boot block volume `61c0f511` @0xc80000 is mapped at 0xfff80000.

## Summary

| # | Severity | Area | One-line |
|---|----------|------|----------|
| 1 | **BLOCKER** | Super I/O / devicetree | Every LDN or VLDN missing from devicetree.cb is enabled in ramstage, including deep-sleep power control, the watchdogs, the GPIO blocks and the port-80 UART |
| 2 | SHOULD-FIX | romstage.c | The SPD-address comment is wrong. The FSP-M UPD defaults are 0, and the vendor policy has two competing tables. The value used is standard but unverified |
| 3 | NIT | devicetree GPE | GPP_D23 is configured for SCI, but GPP_D is not mapped to GPE0, so the event goes nowhere. The vendor has no handler either |
| 4 | NIT | gma-mainboard.ads | `Analog` (D-Sub) is a dead entry on Skylake-generation libgfxinit with CNP, so VGA will not light in variants A and D |
| 5 | NIT | devicetree USB | OC_SKIP everywhere, although the vendor puts 6 USB2_OC# pads in native mode |
| 6 | NIT | gpio.c | The vendor locks the pads (GpioLockDefault); coreboot leaves every pad unlocked |
| 7 | NIT | out/*.rom | The full images carry the capsule's placeholder GbE MAC 88:88:88:88:87:88 and the capsule's ME region |
| 8 | NIT | scripts/gpio_check.py | Bits coreboot writes as 0 in fields the vendor leaves at default are not reported |
| 9 | NIT | devicetree comments | The USB port-to-connector labels and "U31G1_56" are guesses; SMBIOS type 8 carries no port numbers |
| 10 | NIT | PCIe clocks | All 16 CLKSRC are free-running and CLKREQ is unused. This is safe; the vendor mapping is not established |

No GPIO output, no native-function difference, no voltage, power-limit, overclocking or thermal override, and no fan-control write was found. The IFD, GbE and ME regions are bit-identical to the vendor in A, B and C. D differs only in the HAP bit.

---

## Findings

### 1. BLOCKER: unlisted Super I/O logical devices are enabled by ramstage
**Files:**
- `src/mainboard/asus/b360m-c/devicetree.cb:128-158`
- `src/superio/nuvoton/nct6793d/superio.c:59-99` (`pnp_dev_info`)

**Evidence:**
- **Only 6 PnP devices are static.** `build/A/mainboard/asus/b360m-c/static.c` has only `2e.0`, `2e.1`, `2e.2`, `2e.3`, `2e.5` and `2e.b` (lines 1973-2709).
- **Every other entry is allocated as an enabled device.** `pnp_enable_devices()` (`src/device/pnp_device.c`) calls `alloc_find_dev()` for every `pnp_dev_info` entry. `__alloc_dev()` sets `dev->enabled = 1` ("By default devices are enabled", `src/device/device.c:103-104`) and appends the device to the same bus.
- **Ramstage then writes their enable bits.** `enable_static_devices()` (`src/device/root_device.c`) walks the sibling list, so it also reaches the appended devices. For each one it calls `ops->enable = pnp_alt_enable` → `pnp_set_enable(dev, 1)`, and later `pnp_enable_resources()` does the same.

In effect, ramstage sets these CR30 bits, none of which the vendor's PEI SIO table touches:
- LDN 6 (CIR)
- LDN 7 bits 0-2 (GPIO6/7/8)
- LDN 8 bits 0,1,3,4,7 (WDT1, GPIO0, GPIO base, WDT_MEM, GPIO1)
- LDN 9 bits 0-3 (GPIO2-5)
- LDN A (ACPI)
- LDN D (BCLK/WDT2)
- LDN E (CIR wake-up)
- LDN F (GPIO push-pull/open-drain)
- LDN 0x12 (fan/PWM pin-mux LDN)
- LDN 0x14 (port-80 UART)
- LDN 0x16 bits 0,1,3,4,5,6,7 (DS5, DS3, PCHDSW, DSWWOPT, DS3OPT, DSDSS, DSPU)

The vendor PEI table is in `9029f23e`, file 0x6f0 (39 entries). It only does:
- the global CR 0x27/0x2a/0x2f read-modify-writes
- LDN12 CR EB
- KBC (LDN 5)
- UART A (LDN 2)

The LDN 0x16 bits drive the Super I/O's power-rail and deep-sleep control. Enabling DS5, DS3, PCHDSW and so on without vendor data is exactly the kind of unreviewed pin-driving change the safety goals forbid.

For comparison, upstream NCT6791D boards list every LDN. `asus/maximus_vii_hero/devicetree.cb:82-139` and `asrock/z97_extreme4` set 2e.16, 116, 316, 416, 616 and 716 to `off` and only 2e.516 (DS3OPT) to `on`.

**Fix:**
1. Remove `{ NULL, NCT6793D_LDN12 }` from `pnp_dev_info`. The bootblock uses `PNP_DEV(0x2e, 0x12)` directly and does not need a ramstage device, and writing CR30 of LDN 0x12 has no known meaning.
2. List every remaining LDN and VLDN explicitly in devicetree.cb:
   - 2e.6, 7, 107, 207, 8, 108, 308, 408, 708, 9, 109, 209, 309, d, e, f and 14: `off`
   - 2e.a: `on`, with no register writes
   - 2e.16, 116, 316, 416, 616 and 716: `off`
   - 2e.516: `on`

   This is the upstream NCT679x pattern and very likely the power-on state. Mark it "verify with `superiotool -deV` under vendor firmware" once a dump is possible.

### 2. SHOULD-FIX: SPD address provenance is wrong in `romstage.c:8-15`
- **The comment is false.** It says the addresses are the "FSP-M UPD defaults that the vendor firmware also uses". But the vendor FSP-M default UPD (`CFLUPD_M` at SPI 0xd17b64 and 0xe87b64) has `SpdAddressTable` (+0xA6) = `00 00 00 00`, `RcompResistor`/`RcompTarget` = 0, and `DqPinsInterleaved`/`CaVref` = 0.
- **The vendor runs FSP in dispatch mode.** The FSP-M volume `52f1afb6` holds its own PeiCore, SiInitPreMemFsp and FspInitPreMem. The SA policy therefore comes from the platform PEIM `eeee611d`, and that module contains both:
  - a config-block default {A0, A2, A4, A6}: file 0xc6e0, copied by the LoadDefault routine at 0xfffb5efc, which also sets SMBus base 0xEFA0
  - a policy-update routine that copies {A2, A0, A2, A0} (file 0xc6dc) into the same block, at 0xfffb515d. It sits on the setup-driven update path called from 0xfffb0d89.
- **So the vendor's effective mapping is not established from the image.**
- **Impact is limited.** This is read-only SMBus traffic. A wrong value causes no-memory or DIMM0/DIMM1 swaps (sub-optimal ODT), not damage.
- **Rcomp:** {121, 75, 100} / {60, 26, 20, 20, 26} matches one of Intel's desktop RVP entries in vendor `1051ec65` (file 0x43e4). That table is selected by board ID, so ASUS's choice is unknown. This is acceptable as a reference-board value.

**Fix:** reword the comment to "standard 0xA0..0xA6 layout (Intel config-block default); vendor policy unverified". Add a TODO to confirm with `decode-dimms` and the slot population under the vendor BIOS.

### 3. NIT: GPP_D23 SCI does not route (`devicetree.cb:8-10`, `gpio.c:138`)
- The vendor table entry is 03030017 03148da1 00000601: GPIO, ACPI-owned, RxInv, SCI\|Level, HostDeep, unlocked. `gpio.c` reproduces it exactly, and `gpi_enable_gpe()` sets GPI_GPE_EN.
- GPE0 DW0/1/2 = GPP_C/K/E, so GPP_D never reaches GPE0.
- The vendor DSDT `_GPE` has no handler for it either (only `_L37`, `_L69`, `_L61`, `_L62`, `_L66`, `_L6F`, `_L26`, `_L72`).
- The vendor's own GPE-DW policy is board-ID dependent (`1051ec65` sets K/G/E for H-PCH RVP IDs).
- This is harmless. Fix the misleading comment ("no GPIO based GPE handlers" is true, but D23 is armed).

### 4. NIT: `gma-mainboard.ads:16-22`, `Analog` is a dead entry
- **libgfxinit never validates the port.** `Config.Valid_Port (Analog)` is only set when `Has_DDI_E and Has_PCH_DAC` (`haswell_shared/hw-gfx-gma-port_detect.adb:87-98`), and `Has_PCH_DAC` is False for Skylake generation (`hw-gfx-gma-config.ads.template:275`).
- **EDID cannot be read either.** On CNP, `GMBUS_Alternative_Pins` maps `PCH_DAC` to `PIN_PAIR_SELECT_NONE` (`hw-gfx-gma-i2c.adb:139-145`).
- **The VBT agrees the converter has no DDC pin.** DDI E (the VGA converter) is a DP child with `ddc_pin=0` and AUX A.
- **Effect:** the D-Sub port will not come up under libgfxinit (variants A and D). FSP GOP variants should be unaffected.
- **The rest of the list is consistent with the VBT** (DP1/HDMI1 = DDI B, DP2/HDMI2 = DDI C, HDMI3 = DDI D).
- **Fix:** keep the entry if you like, but correct the comment and the documentation ("VGA only with FSP GOP").

### 5. NIT: USB over-current (`devicetree.cb:45-72`)
- The vendor GPIO table puts GPP_E9-E12 and GPP_F15/F16 in NF1 (USB2_OC0#..OC5#), HostDeep.
- coreboot uses OC_SKIP on every port. This is not hazardous, because current limiting is done by the board's power switches and fuses and OC# is only reported. The OC pin-to-port map is unknown.
- AFE tuning (USB2_PORT_MID) is from the reference board, not the vendor.

### 6. NIT: pad locking (`gpio.c`)
- The vendor GPIO_CONFIG `LockConfig` = 0 (GpioLockDefault, meaning the RC locks the pad) for 226 pads, and 3 (unlock) for GPP_D23 and GPD2.
- coreboot uses `PAD_LOCK(UNLOCK)` for all pads. This is security hardening only. Optionally use `_PAD_CFG_STRUCT_LOCK` or `PAD_CFG_*_LOCK` for the native and unused pads later.

### 7. NIT: full ROM images contain a placeholder MAC and the capsule ME
- `out/*.rom` regions 0x1000-0x2fff come from the capsule (MAC 88:88:88:88:87:88) and 0x3000-0x2fffff from the capsule ME. Flashing a full image externally would overwrite the board's own GbE region (the real MAC) and its ME state.
- The documentation already says to flash the BIOS region only (`Documentation/mainboard/asus/b360m-c.md:50-53,102-106`).
- **Recommendation:** either ship only `*.bios-region.bin`, or rebuild the full images from the owner's chip backup (IFD, GbE and ME taken from the backup).

### 8. NIT: `scripts/gpio_check.py` logic
- **The logic is sound.** It uses `PAD_DW0_MASK`, the CNP-H `rst_map`/`rst_map_gpd`, HOSTSW_OWN, and reads the table from the real `gpio.o`. It reproduces my result: 185 explained (RXEVCFG=OFF on GPIs where the vendor leaves the reset value) and 0 unexplained.
- **Limitation 1:** `extra_set = cmask & ~vmask & cbv` only flags bits coreboot sets to 1. Fields coreboot forces to 0 in fields the vendor leaves at default are never reported, for example RXEVCFG=LEVEL and route=0 on NF pads.
- **Limitation 2:** the default reference is the porter's own JSON.
- Neither limitation hides a problem on this board, because I compared against my own decode.

### 9. NIT: USB comments (`devicetree.cb:46-71`)
- Vendor SMBIOS type 8 (file `daf4bf89`) has connector names only, no port numbers. One record reads 'U31G2_56', while the manual says U31G1_56.
- Because all ports share one configuration, the labels are cosmetic, but they should be marked as unverified.

### 10. NIT: PCIe clocks (`devicetree.cb:12-33`)
- Running all 16 sources free with CLKREQ unused is electrically safe; it only costs power and EMI.
- The vendor policy for CLKSRC was not established from the image.

---

## Verified as correct (OK-verified)

### GPIO
- **Table identity.** The ASUS board PEIM `2accd044-284c-432f-9a1a-4cde31036c9f` (FV_BB, TE .data RVA 0x300, file 0x170) holds 228 consecutive 12-byte GPIO_INIT_CONFIG entries 0x03000000..0x030b000b. That is exactly every CNP-H pad: A24, B24, C24, D24, E13, F24, G8, H24, I15, J12, K24, GPD12.
- **How the PEIM publishes it.** Its entry point calls InstallPpi(0xfffe33f4). The PPI is GUID {38965bb5-8097-40f5-b742-8cc14a649b64}, and its body is {&{?, 0xfffe258c (table), 0xE4 = 228}, &SSID table}. The SSID table includes 00:1f.3 → 0x104386ca, which matches `hda_verb.c`.
- **Right table, applied pre-memory.** The consumer is `eeee611d` (FV_BB, pre-memory):
  - 0xfffb2d65 locates the PPI and sets PCD 0x25/0x26 to the table pointer and count, or to 0 if the PPI is absent.
  - 0xfffb0afc → 0xfffb27c5 then calls GpioConfigurePads(count, table), from the pre-memory init sequence at 0xfffb0262.
  - So the ASUS table, not an RVP table, is the one applied, and it is applied before memory. Applying it in `bootblock_mainboard_init()` is equivalent.
- **The RVP tables are not applied.** Intel RVP tables also exist (`eeee611d` file 0x9000/0x91e0/0xb828/0xba08, `3eaf5e3a`, `59add62d`, `1051ec65`). Those contain GPOs, for example GPP_A21/A22, K13 and B3 driven high. They are selected through PCD 0x25 in `1051ec65`, but `eeee611d` overwrites that PCD in both paths, and the ASUS table covers every pad in any case.
- **Pad-by-pad comparison.** My independent decode and comparison (`compare_gpio.py` against the preprocessed `gpio.c` with the real coreboot headers) shows 228/228 pads with 0 mismatches. It covers PMODE, RX/TX disable, RXINV, TX state, IRQ route, trigger, PADRSTCFG through the CNP-H GPP and GPD maps, termination and HOSTSW_OWN. The only extra write is RXEVCFG=OFF on 185 GPIs, which equals the hardware reset value.
- **No GPIO outputs in either table.** The native outputs are identical to the vendor: A5 LFRAME#, A9/A10 CLKOUT_LPC (20k pull-down), B12 SLP_S0#, B13 PLTRST# (Deep), B14 SPKR (20k pull-down), E4/E5 DEVSLP0/1, E8 SATALED#, F14 NF2 = PS_ON#, GPD4/5 SLP_S3#/S4#, GPD11 LANPHYPC.
- **Reset domains.** The vendor RC encoding (ResumeReset=1, HostDeep=3, PlatformReset=5) maps onto coreboot as follows:
  - GPP: RSMRST=00, DEEP=01, PLTRST=10
  - GPD: RSMRST=11, DEEP=01, PLTRST=10
  - For example, GPD2/3/4/5/11 RSMRST give PADRSTCFG 11 and GPP_C12/H13/H16 RSMRST give 00.

### Devicetree, Super I/O and serial
- **Slots:** vendor SMBIOS type 9 gives PCIEX16 = 00:01.0, PCIEX1_1 = 00:1c.3 (RP4), PCIEX1_2 = 00:1c.4 (RP5), PCI (ASM1083) = 00:1c.5 (RP6). This matches the devicetree.
- **Super I/O resources:** SMBIOS type 34 says "Nuvoton NCT6793D", and the vendor DSDT has SIO1 at 0x2E with LPTE LDN1, UAR1 LDN2, UAR2 LDN3, PS2K/PS2M LDN5, HHMD LDN 0xB, IOHW 0x290 and IOHL 0x10. These match the devicetree resources (0x378/IRQ7, 0x3f8/IRQ4, 0x2f8/IRQ3, 0x60/0x64 with IRQ1/12, HWM 0x290). `gen1_dec = LPC_IO(0x290, 0x10)` gives 0x000c0291. The manual lists 2 COM headers and an LPT header.
- **Bootblock Super I/O init.** The six read-modify-writes in `bootblock.c:21-28` are byte-for-byte the vendor `9029f23e` sequence: CR27 &FB, CR2A &BF, CR27 &EF\|10, CR2F &FD, CR2A &FC, LDN12 CR EB &CF.
- **UART A routing.** `nuvoton_enable_serial()` clears CR2A bit 7, which is identical to the vendor's debug-serial tables in SEC/PeiCore/CpuMpPei (CR2A &7F, then LDN2 at 0x3F8 enabled).
- **Ordering.** `bootblock_soc_early_init()` (2E/2F decode) runs before `bootblock_mainboard_early_init()`, and the GPIO setup runs after `bootblock_soc_init()`.
- **No HWM or fan-control writes.** Nothing in the mainboard or the nct6793d driver writes the HWM index/data ports (0x295/0x296), and `SUPERIO_NUVOTON_COMMON_HWM` is not selected. Only the LDN B base and enable bit are written, so the fan registers keep their power-on defaults. Note: LDN12 EB[5:4] and CR2A[1:0] are the FAN5/PWM5 mux bits (Linux nct6775 usage). This matches the vendor, and SMBIOS lists only CPU_FAN, CHA_FAN1 and CHA_FAN2.

### HDA, VBT and display
- **HDA verbs.** The vendor verb table is in `60c33d7a` (file 0x4a0, pointer at file 0x5b0) and `hda_verb.c` is identical to it:
  - SSID 0x104386ca and 4× 0x0017ff00
  - pins 0x11=40330000, 0x12=411111f0, 0x14=01014010, 0x15=01813040, 0x16/0x17=NC, 0x18=01a1904f, 0x19=02a19050, 0x1a=99130120, 0x1b=02214030, 0x1c=NC, 0x1d=40200001, 0x1e/0x1f=NC
  - coefficient 7 = 0x09c8 written twice
  - The alternate overrides at file 0x5c4/0x5f8 are setup-option variants (AC97 front panel, S/PDIF) and are correctly not used.
- **VBT.**
  - `data.vbt` is identical to the vendor FFS `56752da9-de6b-4895-8819-1945b6b76c22` ("$VBT SKYLAKE", BDB 221, 0x1161 bytes, checksum valid; SPI 0xb712f4 and 0xbf12f4).
  - The only other VBT (BDB 209) is inside the legacy VGA option ROM `a0327fe0` and has the same port layout.
  - The decoded children are:
    - DDI A: placeholder entry, type 0x1806
    - DDI B: DP++, DDC 1, AUX B
    - DDI C: DP++, DDC 2, AUX C
    - DDI D: HDMI, DDC 3
    - DDI E: DP, no DDC, AUX A (the VGA converter)

### Images and configuration
- **Regions.** IFD, GbE and ME in out/A, B, C and build/A, B, C are bit-identical to the vendor (0x0-0x2fffff).
- **Variant D:** exactly 1 byte differs, at 0x102 (00→01). FPSBA = 0x100 (FLMAP1 0x5a100208), so this is PCHSTRP0 bit 16, the CNP HAP bit. A and D BIOS regions are identical (sha256 4633b586…).
- **Configs.** `out/*.config` have TTYS0_BASE 0x3f8, CONSOLE_SERIAL_115200, LCS 3, POST_IO_PORT 0x80, and VALIDATE_INTEL_DESCRIPTOR. `DISABLE_HECI1_AT_PRE_BOOT` is not set.
- **No platform-risk overrides.** romstage sets only `UserBd` and memcfg, and the devicetree sets no power-limit, TCC, voltage or overclocking registers.
- **Checksums:** `out/SHA256SUMS` verifies.

### Patches and tools
- **Patches.** `patches/*.patch` equal `git format-patch c49935a4` of the tree, apart from blank lines between concatenated patches.
- **intelp2m.** The `cnlh` platform reset remapping matches `gpio_cnp_h.c` (GPP 00/01/10 → RSMRST/DEEP/PLTRST, GPD unchanged). `go vet` and `go test ./platforms/cnlh ./platforms/cnl` pass.

## Not verifiable from the image
- The PCIe CLKSRC/CLKREQ to root-port map.
- The USB OC map and USB2 AFE values.
- The vendor's effective SPD table (see #2).
- The vendor's DXE or runtime Super I/O state for the LDNs in #1.
- Any GPIO toggling done by DXE or SMM drivers (no table-driven GPO writes were found in PEI beyond the ASUS table).
- These need a `superiotool`/`inteltool` dump under the vendor firmware when hardware becomes available.
