# Events API — Client Guide

This is a concise guide to consume the Events backend from a client app. The server runs at `http://localhost:1345` by default (see `app.py`). All protected endpoints require `Authorization: Bearer <token>`.

## Auth & Roles

- Login to obtain JWT: `POST /auth/login` → `{ token }`
- Get current user and role: `GET /auth/me` → `{ id, name, email, role }`
- Roles: `admin | moderator | user`
- Admin-only: create, update, delete events
- All authenticated users: RSVP create/delete, list own RSVPs

## Events

- List events
  - `GET /events?status=upcoming&cursor=<id>|<date>&limit=20`
  - Defaults: `status=upcoming`, `limit=20`
  - Sort: `startsAt desc, id desc`
  - Returns: `{ items: Event[], nextCursor?: string }`
  - Example:
    ```bash
    curl "http://localhost:1345/events?status=upcoming&limit=10"
    # next page if nextCursor exists
    curl "http://localhost:1345/events?status=upcoming&cursor=<id>|<iso>&limit=10"
    ```

- Get event
  - `GET /events/:id`
  - Returns: `Event`
  - Example:
    ```bash
    curl "http://localhost:1345/events/8f7b8b2a-7f0a-4f6f-a1f5-2c1e2b7bdbab"
    ```

- Create event (admin)
  - `POST /events`
  - Headers: `Authorization: Bearer <token>`, `Content-Type: application/json`
  - Body: `{ "title": "...", "type": "...", "startsAt": "2025-01-05T17:00:00Z", "host": "...", "capacity": 150 }`
  - Returns: created `Event`
  - Example:
    ```bash
    curl -X POST "http://localhost:1345/events" \
      -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
      -d '{ "title":"Live Q&A", "type":"Live Q&A", "startsAt":"2025-01-05T17:00:00Z", "host":"Emman", "capacity":100 }'
    ```

- Update event (admin)
  - `PATCH /events/:id`
  - Headers: `Authorization: Bearer <token>`, `Content-Type: application/json`
  - Body: Partial update, e.g. `{ "startsAt": "2025-01-06T17:00:00Z", "status":"upcoming" }`
  - Returns: updated `Event`
  - Example:
    ```bash
    curl -X PATCH "http://localhost:1345/events/<id>" \
      -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
      -d '{ "title":"Updated Title", "capacity":120 }'
    ```

- Delete event (admin)
  - `DELETE /events/:id`
  - Headers: `Authorization: Bearer <token>`
  - Returns: `204`
  - Example:
    ```bash
    curl -X DELETE "http://localhost:1345/events/<id>" -H "Authorization: Bearer $TOKEN"
    ```

## RSVPs

- RSVP create
  - `POST /events/:id/rsvp`
  - Headers: `Authorization: Bearer <token>`, `Content-Type: application/json`
  - Body: `{ "status": "going" }`
  - Returns: `{ eventId, userId, status }`
  - Example:
    ```bash
    curl -X POST "http://localhost:1345/events/<id>/rsvp" \
      -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
      -d '{ "status":"going" }'
    ```

- RSVP delete
  - `DELETE /events/:id/rsvp`
  - Headers: `Authorization: Bearer <token>`
  - Returns: `204`
  - Example:
    ```bash
    curl -X DELETE "http://localhost:1345/events/<id>/rsvp" -H "Authorization: Bearer $TOKEN"
    ```

- List RSVPs for current user
  - `GET /me/rsvps?cursor=<id>&limit=50`
  - Headers: `Authorization: Bearer <token>`
  - Returns: `{ items: Array<{ event: Event, status }>, nextCursor?: string }`
  - Example:
    ```bash
    curl "http://localhost:1345/me/rsvps?limit=20" -H "Authorization: Bearer $TOKEN"
    # next page
    curl "http://localhost:1345/me/rsvps?cursor=<last_rsvp_id>&limit=20" -H "Authorization: Bearer $TOKEN"
    ```

## Event Model

- `id`: string (UUID)
- `title`: string
- `type`: string (e.g., Live Q&A, Meditation)
- `startsAt`: ISO string (`YYYY-MM-DDTHH:MM:SSZ`)
- `host`: string
- `status`: `upcoming | past`
- `capacity`: number (optional)
- `createdBy`: user id (admin)
- `createdAt`: ISO string
- `updatedAt`: ISO string

## Pagination

- Events: use `nextCursor` string from response on subsequent calls
  - Format: `<eventId>|<startsAtISO>`
- RSVPs (current user): use numeric `nextCursor` equal to last RSVP id

## Errors

- `400` invalid payload (e.g., bad date, negative capacity, wrong RSVP status)
- `401` unauthorized (missing/invalid token)
- `403` forbidden (non-admin on admin endpoints)
- `404` not found (missing event)
- `409` conflict (duplicate RSVP or capacity reached)
- `429` rate limited (reserved for future use)
- `500` server error

## Notes

- `startsAt` accepts `Z`-suffixed ISO strings; stored UTC and returned as ISO with `Z`
- Capacity is optional; when set, RSVPs are limited to capacity
- Past events cannot be RSVPed

