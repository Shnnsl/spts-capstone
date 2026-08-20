# Smart Production Tracking System (SPTS)

**Manufacturing Execution and Industrial IoT Prototype**

SPTS is a manufacturing application connected to a physical Raspberry Pi tabletop production prototype. It processes authenticated sensor events, detects downtime, calculates OEE and waste, and displays production data in role-based dashboards.

<p align="center"><img src="screenshots/spts%20physical%20tabletop%20system.jpg" alt="SPTS physical tabletop production system" width="900"></p>

## Overview

SPTS provides:

- Live production visibility and production counts
- Automatic downtime detection and recovery
- Availability, Performance, Quality, and Overall Equipment Effectiveness (OEE)
- Finalized-waste analytics without misclassifying temporary work in progress
- Role-based dashboards for line workstations, supervisors, managers, and administrators
- Raspberry Pi / PLC-style integration with five physical FC-51 sensors
- Authenticated production-event delivery with retries and duplicate protection

## Physical Industrial IoT Prototype

SPTS connects a manual tabletop conveyor and five sensors to the FastAPI backend through a Raspberry Pi:

```text
Physical sensors → Raspberry Pi PLC client → Wi-Fi → Authenticated REST API
→ FastAPI production, downtime, and OEE processing → Role-based dashboards
```

The conveyor is manually operated with its own controller. The Raspberry Pi reads sensor inputs only: it does not start, stop, power, or change the speed of the conveyor, and SPTS performs no motor control.

## System Architecture

The system separates physical sensing, edge delivery, API processing, database storage, and dashboards.

<p align="center"><img src="docs/diagrams/spts%20high%20level%20architecture.png" alt="SPTS high-level architecture" width="820"></p>

The Raspberry Pi acts as a PLC-like edge device. It converts sensor detections into authenticated API events and keeps undelivered events in a local queue when SPTS is unavailable.

<p align="center"><img src="docs/diagrams/spts%20raspberry%20pi%20edge%20architecture.png" alt="SPTS Raspberry Pi edge architecture" width="820"></p>

## Physical Sensor Configuration

| Sensor | GPIO | Purpose | Production meaning |
|---|---:|---|---|
| S1 | GPIO17 | Input Material Counter | Each unique S1 detection represents 50 input material units |
| S2 | GPIO27 | Filler state | Sustained blockage triggers automatic downtime |
| S3 | GPIO22 | Cartoner state | Sustained blockage triggers automatic downtime |
| S4 | GPIO23 | Case Packer state | Sustained blockage triggers automatic downtime |
| S5 | GPIO24 | Finished Goods Counter | Each unique S5 detection represents 12 finished goods units |

<p align="center"><img src="docs/diagrams/spts%20gpio%20sensor%20configuration.png" alt="SPTS GPIO sensor configuration" width="820"></p>

A supporting photograph of the prototype wiring is available in [screenshots/raspberry pi gpio sensor wiring.jpg](screenshots/raspberry%20pi%20gpio%20sensor%20wiring.jpg).

## Production Event Processing

<p align="center"><img src="docs/diagrams/spts%20physical%20sensor%20event%20processing.png" alt="SPTS physical sensor event processing" width="820"></p>

- The PLC client authenticates with SPTS and submits events over REST.
- Each event carries a UUID for idempotency and duplicate protection.
- The API validates the sensor/event combination and caller permissions.
- A local SQLite-backed edge queue retains events during connectivity failures.
- Retry processing delivers the original event when service returns.
- Accepted events update production counts, downtime state, and OEE data.

## Line Monitoring

The Line Monitoring view shows production counts, `RUNNING` / `DOWNTIME` state, sensor states, runtime, OEE, finalized waste, and downtime history using data returned by the backend.

<p align="center"><img src="screenshots/spts%20line%20monitoring.jpg" alt="SPTS Line Monitoring dashboard" width="760"></p>

## Automatic Downtime Detection

```text
Sustained S2 / S3 / S4 blockage → automatic downtime for affected machine
→ same sensor condition clears → downtime closes → line returns RUNNING
→ completed interval remains in downtime history
```

Brief sensor interruptions do not create downtime. Persisted deadlines allow detection to recover safely after an application restart. Detection and recovery screenshots have not been added to this repository yet, so this section intentionally avoids broken image links.

## Role-Based Dashboards

The Supervisor dashboard shows operational OEE/APQ, finalized waste, downtime, approval, and alert KPIs. The Manager dashboard focuses on OEE, waste, downtime, risk, and line-level metrics. Both read their production data from the backend.

<p align="center"><img src="screenshots/spts%20supervisor%20dashboard.jpg" alt="SPTS Supervisor dashboard" width="760"></p>

<p align="center"><img src="screenshots/spts%20manager%20dashboard.jpg" alt="SPTS Manager dashboard" width="760"></p>

## Raspberry Pi PLC Communication

The Raspberry Pi client uses `gpiozero` to read the sensors and JWT authentication to submit events to a protected FastAPI REST endpoint. It acts as a PLC-like input client, not a motor controller.

<p align="center"><img src="screenshots/raspberry%20pi%20spts%20communication.png" alt="Raspberry Pi communicating with SPTS" width="820"></p>

## Offline Queue and Recovery

```text
SPTS unavailable → event retained locally → delivery retries → SPTS restored
→ original event delivered → queue returns to zero
```

<p align="center"><img src="screenshots/plc%20offline%20queue%20recovery.png" alt="PLC client offline queue recovery" width="900"></p>

MQTT or a message broker is not part of the current implementation.

## OEE and Waste Analytics

- **Availability** — runtime as a proportion of planned production time
- **Performance** — ideal production time for finished output as a proportion of runtime
- **Quality** — finished goods units as a proportion of input material units
- **Overall OEE** — Availability × Performance × Quality
- **Waste %** — Finalized Waste Units ÷ Input Material Units × 100

Unaccounted material units remain work in progress while a trial is active. They become finalized waste units only when an authorized user finalizes the trial, so temporary WIP is not reported as waste.

## Security

- JWT authentication with configurable expiration
- One-way password hashing and role-based access control (RBAC)
- Operator / Line Workstation, Supervisor, Manager, and Administrator roles
- Protected PLC and application API operations
- Secrets loaded from a local, Git-ignored `.env` file

No credentials or tokens are documented in this README.

## API

FastAPI publishes interactive Swagger UI and machine-readable OpenAPI documentation at `/docs` while the API is running.

<p align="center"><img src="screenshots/spts%20fastapi%20swagger%20api.jpg" alt="SPTS FastAPI Swagger API" width="620"></p>

## Testing and Validation

The current automated SPTS baseline is **57 tests passed**.

<p align="center"><img src="screenshots/spts%20automated%20test%20results.png" alt="SPTS automated test results showing 57 tests passed" width="820"></p>

Validation includes physical end-to-end Raspberry Pi operation, automatic downtime detection and recovery, offline event recovery, duplicate protection, authenticated PLC communication, and OEE/waste/dashboard/RBAC behavior.

## Technology Stack

| Area | Technologies |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy, SQLite, REST APIs, JWT |
| Frontend | HTML, CSS, JavaScript |
| Edge / IoT | Raspberry Pi, `gpiozero`, FC-51 sensors, REST, local SQLite event queue |
| Development | Git, GitHub, VS Code, pytest, Swagger / OpenAPI |

## Getting Started

1. Create and activate a Python virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env`, replace its placeholders, and set `SPTS_SEED_PASSWORD` if you plan to run `app/seed.py`.
4. Start the API with `uvicorn app.main:app --reload`.
5. Serve `frontend/` with a local static server and sign in through `login.html`.

The API documentation is available at `http://127.0.0.1:8000/docs` by default.

## Project Structure

```text
.
├── app/                  # FastAPI routes, models, security, and persistence
├── frontend/             # Role-based browser dashboards and assets
├── tests/                # API, OEE, downtime, dashboard, and RBAC tests
├── screenshots/          # Physical-system and application evidence
├── docs/diagrams/        # Architecture and engineering diagrams
├── .env.example          # Environment configuration template
├── .gitignore
├── README.md
└── requirements.txt
```

Runtime databases, queues, caches, local environments, and credentials are intentionally excluded from the public repository.

## Additional Technical Documentation

- [UML Class Diagram](docs/diagrams/spts%20uml%20class%20diagram.png)
- [Entity Relationship Diagram](docs/diagrams/spts%20entity%20relationship%20diagram.png)
- [Downtime Approval Workflow](docs/diagrams/spts%20downtime%20approval%20workflow.png)
- [PLC Client Project Structure](docs/diagrams/spts%20plc%20client%20project%20structure.png)
- [Requirements-to-Implementation Traceability](docs/diagrams/spts%20requirements%20to%20implementation%20traceability.png)

## Future Enhancements

The following are possible future directions and are **not** current functionality:

- Industrial PLC integration
- MQTT or enterprise message-broker support
- Cloud deployment and an enterprise database
- SAP / ERP integration
- Predictive maintenance
- AI-assisted production analysis
- Multi-line and multi-site scaling

## Copyright

Copyright © 2026 Nesil Sahin. All rights reserved.

This project is publicly available for portfolio and demonstration purposes. It is not released under an open-source license. Permission is not granted to copy, modify, distribute, or reuse the source code or project materials without prior written permission.

---

The prototype has been tested with the physical Raspberry Pi sensor setup. Software line states describe sensor-derived production conditions; they do not command or confirm the conveyor motor state.
