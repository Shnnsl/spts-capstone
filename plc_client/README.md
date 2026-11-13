# SPTS PLC Client

A standalone Raspberry Pi edge client that reads five active-low FC-51 sensors and forwards durable, idempotent production events to SPTS. It does not run FastAPI, compute OEE/downtime, manage users, control conveyors, or modify the SPTS application.

## Architecture

`FC-51 sensors -> gpiozero/mock backend -> transition processor -> SQLite queue -> authenticated REST client -> SPTS`

Events enter SQLite before network delivery. A background worker sends the oldest event first and deletes it only after an HTTP success. The original UUID remains unchanged across retries, so SPTS can acknowledge duplicates safely.

## GPIO and sensor mapping

| Sensor | BCM GPIO | Station | Behavior/event |
|---|---:|---|---|
| S1 | 17 | INPUT | CLEAR -> ACTIVE emits `PRODUCT_DETECTED` |
| S2 | 27 | FILLER | Changes emit `SENSOR_ACTIVE` / `SENSOR_CLEAR` |
| S3 | 22 | CARTONER | Changes emit `SENSOR_ACTIVE` / `SENSOR_CLEAR` |
| S4 | 23 | CASE_PACKER | Changes emit `SENSOR_ACTIVE` / `SENSOR_CLEAR` |
| S5 | 24 | FINISHED_GOODS | CLEAR -> ACTIVE emits `CASE_DETECTED` |

FC-51 sensors are active-low. GPIO mode uses `DigitalInputDevice(pin, pull_up=None, active_state=False)` with the configured debounce time. Initial GPIO levels establish state without emitting a false startup event.

## Install

Python 3.10+ is recommended.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Raspberry Pi: source .venv/bin/activate
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env`, enter the SPTS line-workstation credentials, and keep `.env` private. The JWT exists only in process memory and neither passwords nor tokens are logged.

## Configuration

| Variable | Purpose | Example |
|---|---|---|
| `SPTS_API_BASE_URL` | SPTS origin, no trailing path | `http://192.168.1.22:8000` |
| `SPTS_USERNAME` / `SPTS_PASSWORD` | API credentials | required |
| `SPTS_LINE_ID` | Production line | `LINE-01` |
| `GPIO_MODE` | `mock` or `gpiozero` (`gpio` remains an alias) | `mock` |
| `LOG_LEVEL` | Python log level | `INFO` |
| `HTTP_TIMEOUT` | Request timeout seconds | `10` |
| `HTTP_RETRIES` | Retries after initial attempt | `3` |
| `QUEUE_PATH` | Durable SQLite file | `data/event_queue.sqlite3` |
| `DEBOUNCE` | GPIO debounce seconds | `0.08` |
| `LOG_PATH` | Writable application log file | `logs/spts-plc-client.log` |
| `SPTS_CLIENT_VERSION` | Displayed client release | `1.0.0` |
| `SPTS_TERMINAL_STATUS_ENABLED` | Enable interactive local status | `true` |
| `SPTS_TERMINAL_STATUS_FORCE` | Show status even when stdout is not a TTY | `false` |
| `SPTS_TERMINAL_STATUS_INTERVAL_SECONDS` | Status refresh period (>0) | `2` |
| `SPTS_HEARTBEAT_ENABLED` | Enable local-only heartbeat log | `false` |
| `SPTS_HEARTBEAT_INTERVAL_SECONDS` | Heartbeat period (minimum 5s) | `30` |

Change the API address by editing only `SPTS_API_BASE_URL`, then restart the client.

## Run in mock mode (Windows)

Set `GPIO_MODE=mock`, then run `python main.py`. Enter `S1` through `S5` to toggle a sensor; `status` prints states and `quit` exits. For S1/S5, one command activates and counts, the next clears without counting. Imports do not require gpiozero on Windows.

## Run on Raspberry Pi with SPTS

Wire sensor output pins to the mapped BCM GPIO pins and share ground. Confirm FC-51 output voltage is safe for Raspberry Pi 3.3 V GPIO before connection. Set `GPIO_MODE=gpiozero`, verify the laptop API is reachable (for example `curl http://192.168.1.22:8000/health`), then run `python main.py`. The configured account needs `LINE_WORKSTATION`, `SUPERVISOR`, or `ADMINISTRATOR` access to the production-event endpoint.

Login is `POST /auth/login` with JSON credentials. The bearer token is kept only in memory. A 401/403 clears it and triggers login again. Network/HTTP failures use bounded exponential retries; undelivered events remain in SQLite for the next attempt or restart. Successful duplicate acknowledgements remove the queued event.

## Systemd installation

1. Copy this project to `/opt/spts-plc-client` and create its virtual environment.
2. Create `/opt/spts-plc-client/.env`; use `GPIO_MODE=gpiozero` and protect it with `chmod 600`.
3. Adjust `User`, `Group`, and paths in `systemd/spts-plc-client.service.example` if needed.
4. Copy it to `/etc/systemd/system/spts-plc-client.service`.
5. Run `sudo systemctl daemon-reload && sudo systemctl enable --now spts-plc-client`.
6. Inspect with `systemctl status spts-plc-client` and `journalctl -u spts-plc-client -f`.

## Safe shutdown and troubleshooting

Stop with Ctrl+C or `sudo systemctl stop spts-plc-client`; queued events persist. Do not delete the configured SQLite queue while events are pending.

- Authentication failure: verify credentials/account role and laptop time.
- Connection failure: check Wi-Fi, laptop firewall, API address, and port 8000.
- No GPIO edges: verify BCM numbering, common ground, active-low wiring, sensor voltage, and `GPIO_MODE=gpiozero`.
- Duplicate logs after an uncertain connection: expected and safe; SPTS deduplicates by UUID.
- Rapid false edges: increase `DEBOUNCE` modestly and inspect wiring/power noise.

## Verification

Run `python -m pytest -q` and `python -m compileall -q .`. Keep real credentials only in ignored `.env`; `.env.example` contains placeholders.

## Version Information

The centralized code version is in `version.py` and defaults to `1.0.0`. `SPTS_CLIENT_VERSION` can override the displayed deployment label. Startup logs the client version, API URL, line, GPIO mode, queue path, and debounce interval—never credentials or tokens.

## Runtime Status Display

The display is local diagnostics only; it does not create a web server or dashboard. On an interactive terminal, `SPTS_TERMINAL_STATUS_ENABLED=true` refreshes a compact view of API reachability/version, authentication, queue and dead-letter depth, deliveries, retries, recent communication/event details, and stable S1–S5 states. It disables itself for redirected/noninteractive stdout unless `SPTS_TERMINAL_STATUS_FORCE=true`. Status rendering writes directly to the terminal and does not flood the log file.

## SPTS API Health Check

Startup calls unauthenticated `GET /health` and records `api_version` when returned. A failure logs a warning and startup continues; normal queued-event retry behavior remains active.

## Heartbeat Limitation

The inspected SPTS API currently has no compatible authenticated device-heartbeat endpoint. Therefore heartbeat is disabled by default. When explicitly enabled, it only records a local diagnostic log at the configured interval. It never calls `/plc/production-event` or any endpoint that changes production counts, downtime, OEE, or line state. SPTS cannot show PLC online/offline until a future dedicated backend endpoint exists.

## Viewing Queue Depth

With the virtual environment active:

```bash
python event_queue.py data/event_queue.sqlite3
```

This reports pending and dead-letter counts without modifying either collection.

## Viewing Dead-Letter Events

Non-retryable backend rejections are moved atomically to durable dead-letter storage with event ID, event payload, reason, HTTP status, and UTC failure time. They are never automatically deleted. Inspect safely with:

```bash
python event_queue.py data/event_queue.sqlite3 --dead-letters
```

Credentials, JWTs, and authorization headers are not part of event payloads or dead-letter records.

## Startup Sensor-State Synchronization

GPIO mode reads each input during initialization and records its current stable state without emitting an event. This prevents startup from creating a false product/case count or state transition. Mock mode starts all sensors `CLEAR`.

## Fixed GPIO Mapping Validation

Startup validates the immutable trial mapping shown above. Duplicate sensor IDs/GPIO pins, wrong pins or stations, unsupported IDs, and incompatible count/state semantics stop startup before monitoring begins.

## Security Notes

Use a least-privilege SPTS account and protect `.env` with filesystem permissions. JWTs remain memory-only. Logs and terminal output exclude passwords, tokens, authorization headers, and full authentication responses. Keep the queue and log directories writable only by the service account where practical.

## Recommended Raspberry Pi Deployment Order

1. Review and test this release on Windows in mock mode.
2. Copy the project to the Pi only during an approved deployment window.
3. Create the Pi virtual environment and install `requirements.txt`.
4. Create and protect `.env`; select `gpiozero` mode.
5. Verify sensor voltages, common ground, and fixed BCM mapping with the conveyor fully manual.
6. Confirm `/health`, credentials, firewall, and time synchronization.
7. Run interactively and validate S1–S5 transitions plus queue recovery.
8. Review logs and dead letters.
9. Only after acceptance, install and enable the provided systemd unit.

The conveyor remains fully manual. This client reads sensors and forwards events only; it contains no conveyor or relay control.
