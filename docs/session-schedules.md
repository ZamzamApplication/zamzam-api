# Weekly halaqa schedules

Administrators manage tenant-scoped schedules at `GET/POST /session-schedules`,
`PUT /session-schedules/{id}`, and `POST /session-schedules/{id}/skip`.

Create/update fields: `name` (optional), `weekdays` (Sunday=0 through Saturday=6),
`start_date`, optional `end_date`, IANA `timezone` (default `Africa/Cairo`),
`membership_mode` (`all`, `categories`, `students`), `member_ids`, and `is_active`.
Updates and skips require `expected_version`; a stale version returns 409.
A skip also takes `date`.

A server task runs at startup and every minute, preparing occurrences from today
through seven days ahead in each schedule's timezone. It does not create past
sessions. The API machine must stay running; Fly's configuration keeps one
machine active. The image includes tzdata for timezone and daylight-saving rules.

Occurrence dates have a database uniqueness constraint. Creation and its receipt
commit together, and each schedule takes a database write lock. Multiple workers,
restarts, and failed transactions cannot create duplicate occurrences. Deleting
an occurrence's session retains its receipt and sets the session ID to null,
preventing recreation. Existing manual sessions in single-session mode are
reported as conflicts without being overwritten.

All-student rosters use active students at creation. Category schedules resolve
current category memberships when each session is generated. Selected-student
schedules include only selected, currently active students. Selected membership
requires multiple-session mode. Disabling that setting suspends generation of
selected-roster schedules rather than broadening attendance to everyone.

Edits and pauses affect subsequent creation; existing sessions are retained.
The clients explain this and let administrators skip individual upcoming dates.
Skipping archives only untouched, unconfirmed occurrences and keeps their data.
Confirmed sessions, edited attendance, Quran progress, or session version changes
prevent a skip with 409. Regular session lifecycle controls remain available.
Schedules and skip actions are audited. Attendance and confirmation stay manual.
