# Optional ZimaOS/CasaOS integration

The CLI, curve storage, guard and control do not depend on CasaOS. This adapter is only for an existing administrator-authenticated ZimaOS custom-storage dashboard.

## Backend adapter

Return to automatic cooling and stop only the public controller before editing configuration. Set `casaos: true` and `casaos_users` to the CasaOS storage root (normally `/var/lib/casaos`). Preflight reads `db/user.db` and requires its administrator tables. Restart the public controller after preflight passes; keep the guard running.

The controller checks the current administrator IDs on every cycle. It creates `taelo_fan_control.json` symlinks in administrator custom-storage directories, pointing to the public runtime status. It consumes `taelo_fan_request.json` written through the existing authenticated custom-file API. Non-administrators cannot apply commands; losing administrator status restores automatic control. Existing requests are ignored at startup, and new requests have strict freshness, size, type, no-symlink and rate-limit checks.

Status uses version 3. Curve requests use `{id, createdAt, mode: "curve", curve}`; manual requests use `{id, createdAt, mode: "percentage", output}`; Default uses `{id, createdAt, mode: "automatic", output: 100}`. Times are Unix seconds; request IDs are 8–80 characters. Acknowledgements identify the request and its result.

## Frontend fragments

`dashboard/fan-controls.js`, `dashboard/fan-and-temperature.css` and `dashboard/temperature-map.js` are fragments from the original custom Vue dashboard. They depend on that host component's Vue bindings, authenticated API object, administrator check and telemetry sources. They are not drop-in CasaOS extension packages. Integrate them into your own existing component using those bindings and the mailbox contract above; no public installer injects or rebuilds a private dashboard.

The temperature map and historical power collector are optional research/dashboard components. `ilo_metrics.py` still describes the original private telemetry deployment and is intentionally not installed or started by the public setup. Basic CLI fan control uses neither it nor its private database paths.

Only sanitized status is exposed to the dashboard; credentials stay root-only. No HTTP listener is added. Do not give the browser root CLI access or iLO credentials.

## Removing the adapter

Return to automatic control, stop the public controller, remove only symlinks whose target is `/run/ml350-fan-control/status.json` from the CasaOS custom-storage directories, set `casaos: false`, and restart the controller. Remove frontend fragments from your component using its normal deployment process. Do not remove links belonging to the original private installation. The program uninstaller retains those directories and does not rebuild any dashboard.
