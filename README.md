# ML350 Gen9 manual fan control

Standalone Linux fan control for **HP/HPE ProLiant ML350 Gen9 with stock iLO 4 firmware 2.82 only**. Set an actual 1–100% PWM target, apply a CPU temperature curve, inspect status, or return to automatic cooling. All installed fans share one target.

No firmware flashing, downgrade, reboot, temperature spoofing or sensor disabling is involved. This is an unofficial tool using a narrowly verified, undocumented CHIF operation. Other models and firmware versions are rejected.

## Prerequisites

- Run on the physical ML350 Gen9 host: Linux x86-64, systemd, Python 3.9+, Intel `coretemp` sensors and the stock `hpilo` kernel driver.
- Root/sudo access, network access to this host's iLO, and iLO credentials authorized to read thermal data and clear the OEM fan adjustment.
- A separately acquired HPE CHIF library from **ilorest 7.4.0.0**, with its terms reviewed. No proprietary library or firmware is included.
- An independently verified copy of iLO's leaf TLS certificate and an accurate list of physically installed fans.
- Healthy installed fans and readable temperature sensors. The tested host had an iLO Advanced license; operation under other license levels has not been verified.

A percentage is a PWM request, not a guaranteed safe mechanical fan speed. Start high and observe temperatures under your own workloads. The firmware's original automatic control is the recovery mode.

## Install

These commands are for a new installation. **Do not run this installer alongside another fan controller.** It refuses active public or legacy Taelo fan services and never migrates private files. See [installation details](docs/installation.md) for updates and kernels without hpilo.

On Debian/Ubuntu, install prerequisites:

```sh
sudo apt install python3 kmod openssl git ca-certificates
git clone https://github.com/nieqttv/ML350-G9-MANUAL-FAN-CONTROL-NO-IMAGE-FLASH.git
cd ML350-G9-MANUAL-FAN-CONTROL-NO-IMAGE-FLASH
sudo modprobe hpilo
sudo modprobe coretemp
```

Acquire the exact HPE wheel yourself, without installing or running iLOrest. Review [the acquisition and licensing notes](docs/chif-dependency.md), then:

```sh
python3 -m pip download --only-binary=:all: --no-deps ilorest==7.4.0.0 -d .private-chif
python3 tools/extract_chif.py .private-chif/ilorest-7.4.0.0-py2.py3-none-any.whl \
  --destination .private-chif/extracted --accept-hpe-terms
sudo python3 install.py install
sudo install -o root -g root -m 644 .private-chif/extracted/ilorest_chif.so \
  /usr/local/lib/ml350-fan-control/ilorest_chif.so
```

Use your distribution's `python3-pip` package if pip is missing. The extractor verifies the wheel and x86-64 library hashes and executes no wheel code. Installation copies files and reloads systemd definitions; **it does not start or enable services**.

Edit the root-only files locally with `sudoedit`:

```sh
sudoedit /etc/ml350-fan-control/config.json
sudoedit /etc/ml350-fan-control/ilo-credentials.json
```

- In credentials, replace host, username and password. Use an iLO IPv4 address or DNS name, without a URL scheme or port. Never put passwords in command arguments or commit these files.
- Set `installed_fans` to every physically installed fan's iLO name. The example has fans 1–3; it is not automatic hardware detection. A missing, zero-speed or unhealthy configured fan rejects control. A running fan omitted from the list also rejects control.
- Leave `casaos: false` for standalone use.

Export iLO's leaf certificate using a trusted management route, verify its SHA256 fingerprint independently, and install it:

```sh
openssl x509 -in ilo-certificate.pem -noout -fingerprint -sha256
sudo install -o root -g root -m 600 ilo-certificate.pem \
  /etc/ml350-fan-control/ilo-certificate.pem
sudo ml350-fan preflight
sudo systemctl enable --now ml350-fan-guard.service ml350-fan-control.service
sudo ml350-fan status
```

Preflight is read-only. It checks local and remote model, the matching host UUID, firmware 2.82, certificate pin, CHIF identity/protocol, installed fans, all online CPU package/core sensors and configuration permissions. Credentials are sent only after the exact leaf certificate matches on the same connection. A certificate change is a hard failure.

Allow a few seconds for healthy controller and guard heartbeats. Status must report `ready: true` before applying a target. Startup restores automatic cooling; it never reactivates a saved manual setting or curve.

## Use

```sh
sudo ml350-fan status
sudo ml350-fan manual 50
sudo ml350-fan curve --file examples/curve.json
sudo ml350-fan curve --points '[[40,20],[50,30],[60,45],[70,65],[80,100]]'
sudo ml350-fan curve --saved
sudo ml350-fan automatic
```

Manual input must be an integer from 1 to 100. The CLI waits for the controller's acknowledgement and returns a nonzero exit code on failure. A command without an acknowledgement triggers automatic restoration rather than being reported as successful.

Curves accept 2–8 integer points: 20–85°C, 1–100%, increasing temperatures and nondecreasing outputs. The hottest package/core reading across the detected one or two CPUs controls the target; interpolation rounds up. Above the final point, its output is held until separate thermal protection intervenes. Applying a curve saves it to root-only `/var/lib/ml350-fan-control/curve.json`; `automatic` preserves it.

`examples/quiet-curve.json` contains `[[40,10],[50,13],[60,17],[70,21],[85,34]]` as an opt-in example. It is not the installed default or a recommendation for another host. No existing saved settings are imported or overwritten during installation.

## Recovery and safety

```sh
sudo ml350-fan automatic
sudo systemctl stop ml350-fan-control.service
sudo ml350-fan automatic
sudo ml350-fan status
sudo journalctl -u ml350-fan-control -u ml350-fan-guard -n 50 --no-pager
```

Keep the guard running if restoration is pending. Repair iLO connectivity, the certificate pin or CHIF availability and retry automatic control. A failed restoration stays pending; the software never claims an unreachable iLO accepted a reset.

- Each override has a **60-second firmware timer**, renewed before fewer than 20 seconds remain. An abandoned override expires even if the host or services stop responding.
- The independent guard retries unfinished changes and restores after a controller heartbeat older than 15 seconds. The controller also restores when the guard disappears.
- Default releases CHIF and clears the REST reduction independently, attempting both even if one fails. Controller shutdown and systemd's stop hook also restore.
- Missing sensors, PWM readback changes, fan faults and iLO warning/critical thresholds with a 5°C margin trigger restoration.
- CPU critical alarms or temperatures within 3°C of the reported critical limit force 100%. Protection releases below an 8°C margin. It does not alter the saved curve or firmware thresholds.

Polling, network latency and physical cooling limits still matter. These protections do not establish a safe minimum speed for every workload. See [troubleshooting](docs/installation.md#troubleshooting).

## Uninstall

From the repository directory:

```sh
sudo python3 install.py uninstall
```

Uninstall stops the controller, verifies automatic restoration, then disables/removes both services and the CLI. If restoration fails, removal aborts and retains the guard and program files. Credentials, certificate, saved curve and the separately acquired HPE library remain for recovery or reinstallation. Once cooling is confirmed automatic, you can remove those retained files yourself. The driver is not unloaded.

## Optional ZimaOS dashboard

Basic control needs no CasaOS, dashboard or network listener. Enable the administrator mailbox adapter with `casaos: true` only on a host that has the CasaOS user database and custom storage API. The existing Vue/CSS fragments are optional integration sources, not a standalone web application or an installer for a private dashboard. See [dashboard integration](docs/dashboard.md).

## Testing and research

```sh
python3 tests/run_tests.py
python3 install.py install --root /tmp/ml350-fan-stage
python3 install.py uninstall --root /tmp/ml350-fan-stage
```

The tests use fake iLO/CHIF transports and temporary files. Staging runs no systemctl, module loader, network request or fan operation. Linux CI also exercises real file locks and root-owned configuration checks. Mocked tests and staged installation do not establish new hardware compatibility.

The detailed tracing, prior experiments and original live validation are in [the historical research log](docs/research.md). Proprietary binaries, private credentials and authenticated response artifacts remain outside this repository.
