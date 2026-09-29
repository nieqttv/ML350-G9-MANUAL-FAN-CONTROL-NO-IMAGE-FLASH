# ML350 Gen9 fan-control research

Investigation date: **29 September 2026**. Target: **HPE ProLiant ML350 Gen9, iLO 4 2.82**.

## Current result

**The network path to the internal adjustment setter has been identified and accepts a zero-adjustment request on stock iLO 4 2.82.** No firmware flash, host restart, or iLO restart was performed.

The endpoint is `PATCH /redfish/v1/Chassis/1/Thermal/`, with the property `Oem.Hp.FanPercentAdjust`. It accepts zero with HTTP 200 and `Base.0.10.Success`, rejects an invented OEM property, and rejects 51 with `iLO.0.10.PropertyValueBadParam`. Static firmware tracing connects the thermal update handler to the bounded internal setter.

This corrects the initial inference from the misleading `Allow: GET, HEAD` header and missing property in GET responses: those observations did **not** mean the update path was unavailable.

**Live fan-speed adjustment and restoration are now verified:** a temporary adjustment of 5 moved all three installed fans from 21% to 20%; restoring zero returned all three to 21%. The user confirmed fan 4 is not physically installed, explaining the reported 0% fault for this test. No host/iLO restart or flash was performed. A native fan slider and Default button are now deployed under Details → Hardware in the ZimaOS dashboard.

This is a reduction relative to automatic cooling, not an absolute-speed setting. In particular, `FanPercentAdjust: 50` does not mean 50% fan speed and cannot be used to raise the current 21% output to 50%. Faster-than-normal or absolute-speed control remains unverified.

## Requirements

- Expose safe faster/slower fan adjustment in the existing ZimaOS dashboard, if a verified control path exists.
- Keep the server running: no shutdown or host restart.
- Do not flash or downgrade iLO firmware.
- Preserve firmware thermal protection; do not falsify temperatures or disable sensors.
- Test only bounded requests supported by the firmware trace; do not use raw register writes, guessed internal messages, or reset commands.
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

The user confirmed fan 4 is not installed. Its iLO Enabled/Critical/0% report is retained as raw telemetry but was excluded from the installed-fan health check for the bounded test. Fans 1–3 were monitored individually. iLO also reports a degraded embedded flash/SD write-verification self-test; this research did not alter that condition.

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

**Interpretation:** this is evidence of an internal adjustment path, not merely unused help text. The network setter has now been traced and tested at zero. Persistence, complete platform behavior and fail-safe behavior remain unverified. The nearby arithmetic alone is insufficient to promise a particular physical fan speed.

A subsequent static trace found a writer to the same adjustment byte. The health handler at virtual address `0x00e06d60` dispatches selector 15 to `0x00e06f00`. That branch reads an unsigned value from request offset 8, accepts values below 51, and writes its low byte to the field used by the adjustment calculation. Zero is accepted by this writer and bypasses the adjustment at the observed read site. A call to this handler exists at `0x00e079e8`.

This narrows the internal field range to **0–50 at this particular writer**. The follow-up trace below connects it to a network request. Zero bypasses the adjustment at the observed read site, but this does not prove it restores every possible cooling override. Supporting local reports: `282-adjustment-field-write.txt`, `282-adjustment-dispatch.txt`, `282-adjustment-structure-references.json`, and `282-adjustment-handler-callers.json`.

The CHIF message provides a separate lead for a temporary host-requested speed increase. Its entry point and request format have not been traced. It is not evidence of arbitrary slower/faster control.

The `FanPercentAdjust` string has references in generated REST property handling. The follow-up also found a thermal-service call at ELF-layout address `0x034a20cc` to a wrapper at `0x034fc3c8`. That wrapper constructs a health-service request with top-level selector 10, sub-selector 15 and the supplied value. The health-service dispatcher routes selector 10 to the previously identified handler. A registration references the name `HEALTH` and that dispatcher.

These are static ELF-layout addresses, not callable runtime addresses; embedded modules require their own address mapping and relocation. They are evidence references only. No internal RPC was injected.

### 4. Checking the new firmware lead against the running system

Initial checks used authenticated reads. Subsequent bounded PATCH tests were explicitly authorized by the user, retaining the prohibition on restarting either the host or iLO. Every connection checked the existing certificate pin before sending credentials.

- The thermal resource still returns `Allow: GET, HEAD` and no OEM adjustment object.
- `GET /redfish/v1/Schemas/HpThermalExt/` returns 404.
- `GET /redfish/v1/SchemaStore/en/HpThermalExt.json/` returns 500.
- `GET /redfish/v1/SchemaStore/en/Thermal.json/` succeeds with a gzip body. Its generic schema references `Oem.Hp` through `HpThermalExt.json` and marks that object writable.

### 5. Authorized live tests

The following requests targeted only the thermal endpoint. The HTTP response's legacy envelope sometimes contains a field named `error` even on success; the HTTP status and embedded message ID were inspected together.

| PATCH body | HTTP | Message | Interpretation |
| --- | ---: | --- | --- |
| `{}` | 400 | `Base.0.10.MalformedJSON` | Empty object is rejected by this implementation; not a method-support test |
| `{"Name":"Thermal"}` | 400 | `Base.0.10.PropertyUnknown` | Existing name reassertion rejected |
| `{"Oem":{"Hp":{}}}` | 400 | `Base.0.10.MalformedJSON` | Empty extension rejected |
| `{"Oem":{"Hp":{"FanPercentAdjust":0}}}` | 200 | `Base.0.10.Success` | Recognized zero-adjustment request accepted |
| `{"Oem":{"Hp":{"TaeloProbeOnly":0}}}` | 400 | `Base.0.10.PropertyUnknown` | Negative control confirms arbitrary OEM fields are not silently accepted |
| `{"Oem":{"Hp":{"FanPercentAdjust":51}}}` | 400 | `iLO.0.10.PropertyValueBadParam` | Rejected boundary matches the statically identified writer's range |

The value 51 was chosen only after inspecting the unsigned `< 51` check that precedes the field write. This initial batch did not apply an accepted positive adjustment; the later bounded test is documented below. No negative value, raw hardware access, hidden shell command, sensor change, or reset was tested.

Afterward, authenticated GET still worked, fans 1–3 remained at 21%, fan 4 retained its pre-existing critical 0% reading, and reported temperature health showed no faults. These observations establish request handling and unchanged observed fan readings, not successful physical speed modulation.

### 6. Monitored nonzero adjustment and restoration

After the user confirmed fan 4 is absent, a bounded live test applied `FanPercentAdjust: 5`, then restored zero. The temporary value is a relative reduction, not a request for 5% fan speed.

| Phase | Fan 1 | Fan 2 | Fan 3 | Samples |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 21% | 21% | 21% | 2 |
| Adjustment 5 | 20% | 20% | 20% | 5 |
| Restored adjustment 0 | 21% | 21% | 21% | 5 |

The test armed a separate systemd timer before applying the adjustment. It would restore zero after 35 seconds, independently of the test process. The test also restored zero in a `finally` block. The guard service subsequently ran successfully and logged `Zero adjustment restored`; it did not restart any existing service, the host, or iLO.

Monitoring checked installed fan health, sensor health, temperature thresholds with a 5°C margin, and a 5°C rise limit relative to baseline. No guard threshold was crossed. The greatest individual sensor rise observed was 2°C; the highest reading across all sensors stayed within 69–72°C during the recorded test. These short observations do not validate long-term cooling under every workload.

The user noticed an audible increase during the test. Restoration from 20% to 21% could explain that, but sound alone was not used as evidence. The telemetry sequence verifies the small adjustment and its restoration.

The user's requested absolute 50% speed was not applied: the confirmed API only reduces the automatic output. No negative value, undocumented upper value or alternate raw command was substituted.

Evidence: `live_adjustment_test.py`, `282-live-adjustment-test.json`, `282-live-adjustment-test.log`, and the successful `taelo-fan-test-restore-1790692752.service` journal. The system metrics service remained active. No persistent nonzero override was left behind.

## Next research questions

1. Live adjustment and zero restoration are demonstrated; before dashboard integration, define conservative bounds, monitoring, and an independent restore policy.
2. Establish persistence and client-loss behavior without host or iLO resets; the independent timer protected this experiment but does not prove firmware auto-reversion on client loss.
3. Treat the setting as an adjustment to automatic output, not an absolute percentage or per-fan control.
4. Trace the CHIF temporary fan-increase path separately if faster-than-normal cooling is required; its request and limits remain unverified.
5. Investigate why GET and the Allow header omit the accepted extension. Do not depend on them alone for capability detection.

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
- `282-health-main-dispatch.txt`, `282-rest-adjustment-wrapper-candidates.json`, `282-rest-adjustment-caller.json`
- `282-empty-patch-test.json`, `282-same-name-patch-test.json`, `282-empty-oem-test.json`
- `282-zero-adjustment-test.json`, `282-unknown-oem-control-test.json`, `282-rejected-boundary-test.json`

## References

- [HPE firmware repository](https://downloads.linux.hpe.com/SDR/repo/fwpp-gen9/current/)
- [Official hp-health package](https://downloads.linux.hpe.com/SDR/repo/mcp/debian/pool/non-free/hp-health_10.80-1874.10_amd64.deb)
- [HPE iLO 4 REST documentation](https://hewlettpackard.github.io/ilo-rest-api-docs/ilo4/)
- [Airbus iLO4 toolbox](https://github.com/airbus-seclab/ilo4_toolbox), especially `scripts/iLO4/ilo4_extract.py` and `ilo4lib.py`
- [Community iLO4 unlock research](https://github.com/kendallgoto/ilo4_unlock), including `research/2022-02-18-building-279.md`
- [HPE-iLO-Fan-Watch](https://github.com/bitwire-it/HPE-iLO-Fan-Watch): third-party project targeting other generations; its compatibility and safety claims are not validation for this ML350.

## Change log

- 2026-09-29: recorded stock-interface and host-library investigation, unpacked official 2.82 firmware, identified external-adjustment and CHIF leads, and checked the generic schema against the running thermal resource.

- 2026-09-29 follow-up: traced REST-to-health dispatch, tested zero and the rejection boundary without resets, corrected the earlier interface-support inference, and retained the fan-4 fault as the limit on cooling-reduction tests.
