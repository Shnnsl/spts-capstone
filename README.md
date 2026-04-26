# Smart Production Tracking System (SPTS)

SPTS is a FastAPI-based backend system for tracking production downtime and calculating OEE in a manufacturing environment.

## Current Features

- Create downtime events
- Calculate downtime duration automatically from start and end time
- Auto-approve downtime events of 25 minutes or less
- Require supervisor approval for downtime events greater than 25 minutes
- Create supervisor messages for longer downtime events
- Prevent invalid time entries
- Prevent overlapping downtime events for the same machine
- View pending downtime events
- Approve pending downtime events
- Calculate OEE
- Simple role-based access with mock users

## Run the Project

```bash
uvicorn app.main:app --reload