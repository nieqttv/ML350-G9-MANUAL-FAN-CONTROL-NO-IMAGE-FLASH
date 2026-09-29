# ML350 Gen9 fan-control research

Investigation date: **29 September 2026**. Target: **HPE ProLiant ML350 Gen9, iLO 4 2.82**.

## Current result

**Actual 1–100% fan control is deployed on the ML350 Gen9 with stock iLO 4 2.82.** The existing ZimaOS dashboard now has a percentage slider, precise numeric entry, Default, an editable CPU fan curve and a temperature map. No host/iLO restart, firmware flash or downgrade was performed.

The first percentage test moved all three installed fans from automatic 21% to actual 50%, then restored Default. It combined the verified timed CHIF override with a narrowly traced platform-record update. The original REST adjustment is only a relative reduction; it is no longer presented as actual speed.

The custom curve uses Linux `coretemp` package/core readings from both processors, taking the hottest reading. The map uses sensor coordinates returned by this server's own iLO web endpoint; CPU readings are replaced with the faster host measurements. Credentials and firmware artifacts remain private.

## Requirements

- Expose safe faster/slower fan adjustment in the existing ZimaOS dashboard, if a verified control path exists.
- Keep the server running: no shutdown or host restart.
- Do not flash or downgrade iLO firmware.
- Preserve firmware thermal protection; do not falsify temperatures or disable sensors.
- Test only bounded requests supported by the firmware trace; do not use raw register writes, guessed internal messages, or reset commands.
- Keep credentials, session tokens, private certificates, and authenticated configuration out of this repository.

The dashboard's layout, grouping, themes, telemetry and graph-tooltip work is already deployed. This document records the fan-control investigation and its deployed result.

## Tested platform

| Item | Observation |
| --- | --- |
| Server | HPE ProLiant ML350 Gen9 |
| Management firmware | iLO 4 2.82, Advanced license |
| BIOS | P92, 2024-08-29, UEFI |
| CPUs | Two Xeon E5-2697A v4; 32 physical cores, 64 threads |
| Host | ZimaOS, Linux 6.12.25 |
| Host interfaces | Verified upstream hpilo module loaded live; local CHIF device available; no IPMI module |
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

## Earlier relative dashboard controls

The user confirmed that the dashboard slider produces an audible response, then requested a wider range and removal of routine timed restoration. The earlier deployed slider spanned **50–100% of automatic output** and has a **Default** button. It maps output to `FanPercentAdjust = 100 - output`, using the statically verified 0–50 range. The former 60-second test timeout has been removed. Moving right increases output back toward automatic cooling; it cannot exceed automatic output.

The current setting is held until another command or Default, subject to protection: installed-fan or temperature problems, loss of iLO readings, revoked administrator access, a missing guard, or controller failure trigger restoration to zero. Controller startup and shutdown also restore zero. A browser disconnect alone does not reset a healthy held setting. This is operational holding while the services run, not a promise to preserve overrides across a reboot.

Implementation:

- `stats-panel.js` and `stats-panel.css` render native controls and live installed-fan readings. Fan 4 is excluded based on the user's confirmation that it is absent.
- Root-only `fan_control.py` consumes `taelo_fan_request.json` from each current administrator's existing ZimaOS custom storage, and publishes acknowledgements through `taelo_fan_control.json`.
- Requests contain ID, creation time, output, and an optional mode (`automatic` or `full`). Full mode requires output 100; other values are rejected. Server-side checks enforce administrator role, freshness, integer bounds, rate limits and safe telemetry. Symlink and oversized request files are rejected. Existing requests are ignored at service startup.
- No new network listener is opened. The browser never receives iLO credentials. TLS pinning is checked before credentials are sent.
- `taelo-fan-control.service` monitors hardware; independent `taelo-fan-guard.service` restores default on an unfinished update or a controller heartbeat older than 15 seconds. Both use a shared lock and root-only state to avoid conflicting writes. Failed restoration remains pending and is retried; an unreachable iLO cannot be claimed to have received a reset.
- Services can connect only to iLO's address. No host, iLO, Docker or gateway restart was needed. Only the dashboard override and the newly introduced fan services were reloaded during deployment.

Validation covers bounds, malformed/stale requests, administrator checks, request-file symlinks, missing fans, temperature margins, failed restoration, apply/default state, and stale-heartbeat behavior. The final persistent mode was checked to retain a healthy setting beyond the former timeout. Browser tests used the actual served component with mocked authentication and responses: slider payloads, acknowledgements, rejected changes, Default, dark/light themes, mobile layout, and unmounting passed; rendered screenshots were inspected. Live administrator requests were also observed reaching the controller and receiving successful acknowledgements. The user independently reported that the controls work.

Persistent mode uses reported thermal warning/critical thresholds with a 5°C margin. The earlier short experiment's 5°C rise-from-baseline guard was removed for persistent use, because normal workload changes would otherwise reset the user's setting. Missing sensors and unhealthy installed fans still trigger restoration.

## Verified full-speed implementation

The local host route is now working. The unmodified upstream Linux 6.12.25 `hpilo` module was built using the running kernel configuration and GCC 13.3.0 in an isolated, resource-limited container. Kernel release/vermagic, module structure size, and all 49 required exported symbols matched. The configuration differences were compiler/binutils identification and an unrelated IPv6 reachability option. No force-load option was used. Loading the driver attached the existing `103c:3307` device and created `/dev/hpilo/d0ccb*` without restarting the server or iLO.

`load_hpilo.py` checks the kernel version, complete configuration hash and module hash before loading. Enabled `taelo-hpilo.service` orders this before the fan services. A changed kernel requires rebuilding; the current module is not blindly reused. Build files and compatibility evidence are retained in `/media/nvme/taelo-hpilo-build`. The official kernel archive SHA256 is `c8af780f6f613ca24622116e4c512a764335ab66e75c6643003c16e49a8e3b90`.

The CHIF library was extracted from the HPE `ilorest-7.4.0.0` wheel after verifying its PyPI SHA256, `bbe31c050f7ac79a8cf2fb48163655da5a4e9a4fe2ab88a05430639372624a9d`; its installer was not run. The library's generic ping was not accepted on this iLO. A traced read-only status command succeeded instead. `ilo_chif.py` checks that response for firmware 2.82 before issuing fan commands, validates response lengths, sequence numbers, command IDs and result codes, and closes the channel on failure.

Firmware evidence:

- The handler at ELF-layout address `0x0109b018` copies fixed arguments `fan p global lock 255` from file offset `0x0050d62c`. Resume at `0x0109b088` copies `fan p global unlock` from `0x0050d6a4`. Helper `0x010ce884` builds HEALTH selector 6; the retained lock routine is at `0x00e19684`.
- SMIF command `0x008c`, device 4, supports status, timed start and release. Durations are bounded at 3,600 seconds; the firmware ticker decrements the countdown and invokes release.
- The eight-second live test recorded **21% → 100% → 21% on all three fans**. Firmware expiry restored automatic control before the independent backup timer ran. The timer also completed successfully. Highest observed temperature was 73°C before the boost and 70–71°C during/after it.
- A second test used the actual administrator mailbox and deployed controller. Full speed was acknowledged, all three fans remained at 100% after a 12-second hold, and Default was acknowledged. Subsequent live readings confirmed 21% on every installed fan. The user independently confirmed the physical full-speed response.

The earlier Full speed implementation held this mode with a one-hour firmware timer. The current percentage implementation uses a 60-second timer and renews before 20 seconds remain; renewal briefly releases and reapplies the selected percentage. A process/host failure cannot make this firmware timer indefinite. Default releases the CHIF override **and** clears the REST reduction, attempting both even if one fails. The independent guard also covers full-speed mode; failed restoration stays pending. Lowering the existing automatic-output slider first releases any full-speed override.

Mocked backend tests cover mode transitions, timer renewal, stale-heartbeat restoration eligibility, partial restoration failure, invalid values and administrator checks. Browser tests use the actual served component with mocked authentication/telemetry and cover Full speed, Default, disabled slider during boost, acknowledgements, rejection handling, themes and mobile layout. Live mailbox/hardware testing is separate evidence. These tests do not establish every workload or a live one-hour renewal cycle.

## Verified actual percentage control

The original boost command hard-codes 255 internally. Its remaining argument is not a speed, and applying the REST reduction before the global override does not change the final PWM. The embedded-health FAN_SET route rebuilds an 8,000-byte cooling table; no table upload was attempted.

Further offline tracing found a targeted platform-record update:

- CHIF SMIF command `0x0200`, service 0, uses a 4,024-byte payload. Its dispatch registration is at ELF file offset `0x511c58`; the handler is at ELF-layout address `0x01088034`.
- External operation 7 enumerates record headers. Operation 6 reads one record. Operation 5 forwards a narrowly specified patch list to HEALTH's `platDefChifService`.
- The internal selector-6 handler at `0x00e43dcc` calls `0x00e3fa4c`, which resolves a record ID and patches the supplied field. This generic firmware interface is broader than a fan API, so the implementation intentionally exposes only one fixed field.
- This server's record 80 is type 3, 128 bytes long, named `Global PWM`. The lock bit is bit 0 of byte `0x59`; the PWM byte is `0x63`.
- The timed override changed only byte 89 in the initial before/after record read. A one-byte patch to offset 99 with raw value 128 produced **50% on fans 1–3**. Default cleared the lock, and the independent restore timer also ran.
- `ilo_chif.py` checks firmware, response framing, record length/type/ID/name, an active countdown with more than ten seconds left, and the lock before writing. It cannot select arbitrary record IDs or offsets. The target byte is read back afterward.
- Integer percentages use `ceil(percent × 255 / 100)`, matching iLO's downward integer conversion. The physical control has 8-bit PWM resolution; low requests are not a guarantee that a fan can sustain that mechanical speed. Zero/unhealthy installed-fan readings trigger Default.

The controller holds the selected target while healthy services run. A 60-second firmware timer bounds an abandoned override even if the host stops responding. The independent guard handles unfinished writes and missing heartbeats. Default releases the CHIF lock and clears REST reduction independently. No temperature sensor, thermal threshold, firmware image or persistent iLO configuration is modified.

Private evidence: `282-platform-chif-route.txt`, `282-platform-chif-operations.txt`, `282-platform-record-update.txt`, `platform-read-record-zero.bin`, `platform-global-pwm-baseline.bin`, and `percentage-first-test.json`.

An initial longer percentage test was interrupted by an administrator changing the slider. It is not counted as a completed renewal test. Subsequent tests detect a new administrator request and yield control without replacing it.

## Custom CPU fan curves

Details → Hardware → Cooling offers Manual and Curve editors. The curve has five editable temperature/speed points, a preview and an Apply/Save action. Default disables the override while retaining saved curve settings.

- `fan_curve.py` reads both `coretemp` packages and their 32 core sensors directly. It does not use iLO's CPU temperatures as the control input.
- The hottest package/core reading controls all installed fans. CPU readings update with the controller polling cycle, approximately every 3–5 seconds depending on iLO response time.
- Validation allows 2–8 points at 20–85°C and 1–100%, with strictly increasing temperatures, nondecreasing outputs and a final 100% point. The current editor displays five points.
- Linear interpolation determines the target. Increases of at least two percentage points, and any request for 100%, apply promptly. Decreases wait ten seconds and fall by at most five percentage points per step to avoid oscillation.
- Both packages and all expected cores must remain readable. CPU critical alarms, temperatures within 8°C of the reported critical limit, missing sensors, unhealthy fans or iLO temperature faults restore Default.
- Curve points persist in root-only `/var/lib/casaos/taelo-fan-settings/curve.json`. Controller startup restores automatic cooling; a saved curve is not automatically re-enabled after a reboot.
- Administrator commands use the existing authenticated custom-file API. Curve requests contain `id`, `createdAt`, `mode: "curve"` and `curve`; manual requests use `mode: "percentage"` and `output`. Status version is 3.

## Temperature map

The authenticated, certificate-pinned `GET /json/health_temperature` response supplies `xposition` and `yposition` for all 46 potential sensor locations. The currently installed hardware exposes 27 readings. The iLO page itself indexes a 16×16 mesh using those coordinates.

The native map preserves that grid and iLO's front-facing orientation: front at the bottom, rear at the top. It shows only present sensors, keeps a fallback row for any sensor without a position, and does not invent component locations. Colored halos indicate the readings around sensor points; they are not additional measured temperatures.

CPU 1/2 locations use host package/core temperatures, with the iLO coordinates unchanged. Other readings retain their iLO source and freshness checks. Hover, focus, click or keyboard selection shows the sensor name and value. Mobile keeps the full map visible and provides a sensor selector. `temperature-map.json` contains only sanitized coordinates and labels.

## Validation and deployment

- Python checks: `python3 tests/test_fan_control.py`, `python3 tests/test_ilo_chif.py`, and `python3 tests/test_fan_curve.py`.
- Tests cover exact packet layout, rejection of foreign records, range/type checks, timer requirements, target readback, restoration failures, curve interpolation/hysteresis, saved settings, hotter-CPU selection, missing sensors and critical temperatures.
- Browser checks use the actual served Vue component with mocked authentication/telemetry. They cover 1–100% entry, acknowledgements, Default, curve editing/validation, mapped coordinates, host CPU replacement, 27 sensor points, keyboard selection, both themes, mobile sizing and clean unmount. Rendered screenshots were inspected.
- These browser checks are separate from real administrator-mailbox/hardware tests. They do not establish every possible workload or the safe sustained minimum speed for each physical fan.
- Dashboard fragments in `dashboard/` mirror their injected sections in the canonical server `stats-panel.js` and `stats-panel.css`. Source changes are staged, checked, backed up and rebuilt with `apply.py`; only Taelo's dashboard/fan/metrics services are restarted.
- No host, iLO, Docker daemon or gateway restart was performed.

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

