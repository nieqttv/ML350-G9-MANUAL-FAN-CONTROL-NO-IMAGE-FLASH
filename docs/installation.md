# Installation details

## Files and repeatability

The installer owns these locations:

- Python modules and ownership marker under `/usr/local/lib/ml350-fan-control/`.
- `/usr/local/bin/ml350-fan`.
- Two units under `/etc/systemd/system/`.
- Initial root-only templates under `/etc/ml350-fan-control/`, created only if missing.
- The state directory `/var/lib/ml350-fan-control/`, with no default curve written.

Runtime state is under `/run/ml350-fan-control/`. Lease, lock and CLI mailbox files are root-only. Status is sanitized and readable for the optional dashboard. Credentials and certificate are mode 600 under a mode 700 directory. The independently acquired CHIF library is root-owned and must not be writable by other users.

Repeating an installation preserves credentials, configuration, certificate, CHIF and curve. Existing unowned program/unit files and symbolic-link destinations are refused. No service is started by install.

For an update to this public installation:

```sh
sudo ml350-fan automatic
sudo systemctl stop ml350-fan-control.service ml350-fan-guard.service
sudo python3 install.py install
sudo ml350-fan preflight
sudo systemctl start ml350-fan-guard.service ml350-fan-control.service
```

Do not run this sequence on the original private Taelo installation without a separately planned migration. The installer refuses active legacy fan services and never reads their private kernel manifest, library, credentials or saved curve. Also check for other third-party fan controllers before starting services.

## Stock hpilo driver

`sudo modprobe hpilo` uses your distribution's module for its currently running kernel. The guard unit uses `load_hpilo.py` to load this driver before startup; it does not build a module, use insmod on a private binary, force-load anything, unload a driver or reboot.

If the module is unavailable, install your distribution's matching kernel module package, if it can be added without a reboot. Some appliance kernels, including the original ZimaOS host, omit hpilo. Those hosts need a module built for the exact running kernel, configuration, compiler ABI and exported symbols, potentially with Secure Boot signing. This public installer does not automate that build or package the original server's module. Do not reuse another server's `.ko`. If an appropriate stock driver cannot be supplied without a reboot, stop here and plan that separately.

Likewise, `coretemp` must expose package readings and every online physical core. SMT threads share a physical core reading. One or two CPUs with different core counts are supported by topology checks; missing or duplicate package/core sensors fail closed. The controller freezes the detected topology at startup so a disappearing CPU/sensor cannot silently reduce monitoring.

## Certificate trust

The pin is the SHA256 of the complete DER leaf certificate, not a hostname or public-key-only match. The same TLS connection is checked before Basic authentication. Redirects are not followed.

You may capture a candidate leaf certificate without authentication:

```sh
openssl s_client -connect ILO_ADDRESS:443 -showcerts </dev/null 2>/dev/null \
  | openssl x509 -out ilo-certificate.pem
openssl x509 -in ilo-certificate.pem -noout -fingerprint -sha256
```

A capture alone does not establish trust. Compare the fingerprint through an independent trusted management route before installing it as the pin. When iLO's certificate legitimately changes, restore automatic control and verify the new fingerprint independently before replacing the pin. Do not disable pinning or automatically trust a changed certificate.

## Configuration paths

`examples/config.example.json` contains the supported fields. `ML350_FAN_CONFIG` can select an alternate root-owned configuration file for direct Python invocations or an explicitly configured systemd drop-in. Never put secrets in that environment variable.

The shipped units use standard runtime/settings/CasaOS paths. If you change paths, update `ReadWritePaths`, `RuntimeDirectory` and the environment in **both** units to match. Retain shared state/lock paths and the independent guard. Reload systemd and restart only these services after returning to automatic control.

## Troubleshooting

- **Not ready:** inspect `status`, `preflight` and both service journals. A healthy guard heartbeat is required for manual control.
- **Wrong host/firmware:** only ML350 Gen9 and iLO 4 2.82 are verified. Preflight compares the configured iLO's system UUID with the host's DMI UUID. Do not disable the check.
- **Library mismatch/load failure:** use the exact wheel and x86-64 member, root ownership, and the pinned hash. Confirm the native library's dependencies are available.
- **Temperature/fan fault:** repair the hardware or sensor source. Never omit an installed fan to suppress a fault. A physically absent fan that iLO reports as faulty can be omitted only after physical verification.
- **Changed CPU topology:** return to automatic control, confirm all installed CPUs and cores are visible, then restart the controller to discover the topology.
- **Certificate changed/authentication failed:** verify the pin and credentials locally. Do not paste credential files or private authenticated responses into bug reports.
- **Restoration pending:** keep the guard active, fix connectivity/CHIF, and retry `automatic`. Firmware expiry bounds CHIF abandonment; REST reduction needs a successful reset request.
- **Uninstall failed:** program files and guard remain available for recovery. Resolve the failed reset and retry uninstall.

## Isolated testing

`python3 tests/run_tests.py` runs the existing packet/curve/controller checks plus portable setup and CLI safety tests. No test uses real credentials or hardware. Linux is required for actual flock/ownership checks; Windows can run the portable cases with a clearly marked test-only flock substitute.

`install.py --root DIRECTORY` creates a staged filesystem tree and never invokes systemctl, modprobe, CHIF or iLO. Stage outside the source directory. Its configuration paths describe the eventual Linux destinations. No staged unit is enabled, started or connected to hardware.
