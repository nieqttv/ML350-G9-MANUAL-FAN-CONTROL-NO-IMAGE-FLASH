# ML350 Gen9 fan-control research

Investigation date: **29 September 2026**. Target: **HPE ProLiant ML350 Gen9, iLO 4 2.82**.

## Current result

**Safe live manual fan control has not been implemented or verified.** Offline inspection of the official 2.82 firmware found more than command-help strings: executable ARM code references an external fan adjustment and performs percentage arithmetic. The REST implementation also contains a `FanPercentAdjust` property model.

Those findings establish useful research leads, not a working public control interface. On the tested ML350, the thermal endpoint advertises `GET, HEAD`, returns no `Oem.Hp.FanPercentAdjust`, and does not provide the referenced extension schema. No experimental control request has been sent.

The investigation remains open. The next question is how, or whether, an authorized host or management request can reach this internal adjustment on this platform without changing firmware.

## Requirements

- Expose safe faster/slower fan adjustment in the existing ZimaOS dashboard, if a verified control path exists.
- Keep the server running: no shutdown or host restart.
- Do not flash or downgrade iLO firmware.
- Preserve firmware thermal protection; do not falsify temperatures or disable sensors.
- Do not test guessed register writes or undocumented command payloads on the production server.
- Keep credentials, session tokens, private certificates, and authenticated configuration out of this repository.

The dashboard's layout, grouping, themes, telemetry and graph-tooltip work is already deployed. This document concerns the unresolved fan-control work.

## Tested platform

| Item | Observation |
| --- | --- |
| Server | HPE ProLiant ML350 Gen9 |
| Management firmware | iLO 4 2.82, Advanced license |
| BIOS | P92, 2024-08-29, UEFI |
| CPUs | Two Xeon E5-2697A v4; 32 physical cores, 64 threads |
| Host | ZimaOS, Linux 6.12.25 |
| Host interfaces | No loaded hpilo/IPMI module or corresponding device node |
| hwmon | CPU, NVMe and network-device sensors; no exposed `fan*`/`pwm*` control |
| Cooling telemetry | Fans 1–3 approximately 20%; fan 4 reports Enabled/Critical and 0%; fans 5–8 absent |

Fan 4's status is a reported fault, not a confirmed physical diagnosis. iLO also reports a degraded embedded flash/SD write-verification self-test. Neither condition was altered during this research.

## Evidence and interpretation

### 1. Stock management interfaces

- Authenticated `GET /redfish/v1/Chassis/1/Thermal/` succeeds. Its `Allow` header is `GET, HEAD`.
- The response contains fan and temperature readings, but no OEM fan-adjustment property.
- SSH `show /system1/fan1` reports `VariableSpeed=Yes` and a desired percentage. The object's available verbs are `cd`, `version`, `exit`, and `show`, not `set`.
- Installed web pages for fans, temperatures, power and access settings were inspected. No manual fan setter was found.
- Unauthenticated web 404 responses can hide authentication requirements; they were not treated as proof that a resource does not exist.
- iLO's documented BIOS `ThermalConfig` values are `OptimalCooling`, `IncreasedCooling`, and `MaxCooling`. BIOS pending changes apply after a server reset. The tested system does not expose the expected BIOS settings link; its current profile remains unverified. No pending change was queued.

**Limit:** absence from these interfaces does not prove that every undocumented control path is impossible.

### 2. Host-side HPE utilities

The official `hp-health_10.80-1874.10_amd64.deb` was downloaded and parsed as an archive. It was **not installed**, and its programs were **not executed**.

- `hpasmcli` contains `do_show_fans`, but no fan setter was found in its usage text or symbol table.
- `HelpShowPWM` resolves to `SHOW POWERMETER`; it is not evidence of pulse-width fan control.
- `do_enable_thermal_shutdown` is a two-byte return stub in this binary.
- `libhpasmintrfc64.so.3.0` exports generic request/transport functions such as `hpIoctlRequest`. That does not establish a fan-control request code.
- The background executables `hpasmxld`, `hpasmlited`, and `hpasmpld` have stripped symbols. Their internals were not exhaustively disassembled, so a hidden request cannot be excluded by the symbol scan.
- The host's i801 SMBus currently exposes memory SPD devices. No active bus probing or raw register writes were performed.

Package SHA-256:

```text
86b1394999581d38b6c86debbd9083b053d1a337f1d90d0ed4bc2ec4d6cb19c9
```

### 3. Direct inspection of official iLO 4 2.82 firmware

Source package:

<https://downloads.linux.hpe.com/SDR/repo/fwpp-gen9/current/firmware-ilo4-2.82-1.1.i386.rpm>

The RPM payload was decompressed and its CPIO archive parsed without installing the RPM or executing an updater. The extracted `ilo4_282.bin` was unpacked using the format and compression algorithm documented by Airbus's iLO4 toolbox, adapted for Python 3.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| HPE RPM | 14,142,862 | `8f00faa42404cb26b8a6cda483a8ed36ea2f3ee31b1e33876f4a238d7fc0389b` |
| `ilo4_282.bin` | 16,784,150 | `36b8fb26119d22da71798e8e126916675e04cc0f8df8538e4029c29ba64b8675` |

The hashes identify the examined downloads; they are not an independent HPE signature verification. Downloads used HTTPS from HPE's repository.

Extracted sizes matched the component headers:

| Component | Decompressed bytes |
| --- | ---: |
| Userland ELF | 24,095,056 |
| Main kernel | 794,624 |
| Recovery kernel | 794,624 |

All offsets below are **file offsets in the decompressed userland ELF**, not offsets in the original firmware image. Virtual addresses refer only to this exact 2.82 image and are not instructions to write memory.

| File offset | Component | Evidence |
| --- | --- | --- |
| `0x39eb58` | `.health.elf.text` | `Fan speed adjusted externally, %d%%, old speed: %d, new speed: %d` |
| `0x39eb9c` | `.health.elf.text` | `Fan speed external adjustment ignored due to high fan speeds` |
| `0x3a5474` | `.health.elf.text` | `fan_blowout: Locking the Fan speed to %d` |
| `0x4bae4c` | `.chif.elf.text` | `Fan speed temporarily increased to blowout by host software for %u seconds` |
| `0x12f9d50` | `.restserver.elf.text` | `FanPercentAdjust` |
| `0x12f9d8c` | `.restserver.elf.text` | `HpThermalExt.1.0.0` |

Static ARM disassembly with Capstone 5.0.6 found PC-relative references to both external-adjustment messages. Around virtual address `0x00e12eb8`, the code reads a byte at an internal structure offset of 9, bypasses the adjustment when zero, checks a speed threshold, and performs arithmetic involving `100 - adjustment` and the existing speed before logging the change. The high-speed branch references the ignored-adjustment message.

**Interpretation:** this is evidence of an internal adjustment path, not merely unused help text. The exact public setter, supported platform conditions, persistence, complete limits, and fail-safe behavior have not been established. The nearby arithmetic alone is insufficient to choose a safe value or promise a particular fan speed.

A subsequent static trace found a writer to the same adjustment byte. The health handler at virtual address `0x00e06d60` dispatches selector 15 to `0x00e06f00`. That branch reads an unsigned value from request offset 8, accepts values below 51, and writes its low byte to the field used by the adjustment calculation. Zero is accepted by this writer and bypasses the adjustment at the observed read site. A call to this handler exists at `0x00e079e8`.

This narrows the internal field range to **0–50 at this particular writer**. It does not establish a callable host/network command: the enclosing message transport, authorization and platform conditions remain untraced. Nor does it prove that zero restores every aspect of normal operation. No request using these values was sent. Supporting local reports: `282-adjustment-field-write.txt`, `282-adjustment-dispatch.txt`, `282-adjustment-structure-references.json`, and `282-adjustment-handler-callers.json`.

The CHIF message provides a separate lead for a temporary host-requested speed increase. Its entry point and request format have not been traced. It is not evidence of arbitrary slower/faster control.

The `FanPercentAdjust` string has references in generated REST property handling. Generated serialization/deserialization code does not prove that the running platform registers a writable service for it.

### 4. Checking the new firmware lead against the running system

Only authenticated reads were used, with the existing certificate pin checked on the same TLS connection before sending credentials.

- The thermal resource still returns `Allow: GET, HEAD` and no OEM adjustment object.
- `GET /redfish/v1/Schemas/HpThermalExt/` returns 404.
- `GET /redfish/v1/SchemaStore/en/HpThermalExt.json/` returns 500.
- `GET /redfish/v1/SchemaStore/en/Thermal.json/` succeeds with a gzip body. Its generic schema references `Oem.Hp` through `HpThermalExt.json` and marks that object writable.

**Unresolved discrepancy:** the generic schema and compiled property model contain an extension that the observed live resource does not expose. Schema metadata must not be mistaken for platform support. No PATCH, guessed extension value, or hidden fan command was attempted.

## Next research questions

1. Trace the thermal-service registration and update callbacks to determine why `FanPercentAdjust` is omitted on this system.
2. Trace the enclosing transport and authorization for the identified internal adjustment writer; establish whether an accessible host or management request reaches it on this platform.
3. Trace the CHIF temporary fan-increase path separately; establish its duration, limits, and applicability to ML350 Gen9.
4. If useful, compare official 2.77 and 2.82 binaries offline to distinguish removed diagnostic commands from retained thermal-control logic. Do not flash either image.
5. Before any production control experiment, establish input bounds, authorization, automatic-control restoration, persistence, and behavior if the client or connection fails. Validate uncertain hardware behavior on a matching spare system first.

No working command is being withheld: no safe usable command has been established yet.

## Other options and their limits

- **BIOS cooling profiles:** documented and require no downgrade, but are not live per-fan percentage controls and require reset to apply.
- **Modified older iLO firmware:** outside the user's requirements. Community research describes removal of diagnostic fan utilities in later versions and failed attempts that can stall/reset iLO. Existing strings do not make those commands safe to invoke.
- **External PWM controller/interposer:** a separate hardware possibility, not a verified ML350 solution. It needs exact pinout, voltage, polarity, tachometer behavior and fail-safe validation, followed by physical installation. Do not modify running fan wiring.
- **Temperature spoofing:** undermines the thermal information used for protection and is not an acceptable substitute for a validated control interface.

## Evidence retained privately

Raw package data, extracted firmware, disassembly and sanitized read results are retained under the server's root-only `fan-research` directory alongside the dashboard sources. Proprietary firmware binaries and machine-specific authenticated responses are not committed here.

Important local evidence files include:

- `hpe-binary-strings.json`, `elf-symbols.json`, `daemon-symbols.json`
- `282-firmware-findings.json`, `282-sections.json`
- `282-candidate-disassembly.json`, `282-adjustment-arithmetic.txt`
- `282-byte9-stores.json` (candidate stores only; not identified setters)
- `Thermal-schema.json`, `assessment.md`

## References

- [HPE firmware repository](https://downloads.linux.hpe.com/SDR/repo/fwpp-gen9/current/)
- [Official hp-health package](https://downloads.linux.hpe.com/SDR/repo/mcp/debian/pool/non-free/hp-health_10.80-1874.10_amd64.deb)
- [HPE iLO 4 REST documentation](https://hewlettpackard.github.io/ilo-rest-api-docs/ilo4/)
- [Airbus iLO4 toolbox](https://github.com/airbus-seclab/ilo4_toolbox), especially `scripts/iLO4/ilo4_extract.py` and `ilo4lib.py`
- [Community iLO4 unlock research](https://github.com/kendallgoto/ilo4_unlock), including `research/2022-02-18-building-279.md`
- [HPE-iLO-Fan-Watch](https://github.com/bitwire-it/HPE-iLO-Fan-Watch): third-party project targeting other generations; its compatibility and safety claims are not validation for this ML350.

## Change log

- 2026-09-29: recorded stock-interface and host-library investigation, unpacked official 2.82 firmware, identified external-adjustment and CHIF leads, and checked the generic schema against the running thermal resource.
