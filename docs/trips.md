# Trip preparation

Administrators open **الرحلات** (`/trips`) to create a trip with its date,
meeting point, departure time, destination, default participant fee and notes.
Trip data is scoped to the active Tahfiz. Sheikh and auditor accounts do not
have trip-management access.

- Add existing enrolled/guest students, or guests by name and optional phone.
- Create buses, cars or named groups. Assign a group during registration,
  individually in participant details, or in bulk from the participants tab.
- A student can be independent or linked to an active adult participant.
  Mark an adult as **بالغ مسؤول** in participant details (adult guests can be
  added directly). Reassign their active dependents before cancelling or
  demoting an adult. Checking an adult never checks their children automatically.
- Record the total amount received, partial payment, or **إعفاء** with an
  optional reason. Exempt participants remain on headcount lists and have no
  outstanding balance. Exemption and cancellation preserve any money already
  received; adjust the recorded amount only when it has actually been refunded.
- Start **تجمع الصباح** and additional named headcounts throughout the day.
  A new round includes all active participants and starts every check as pending.
  Use group filters to check one bus/car/group, or display everyone. Every person
  must be checked separately; previous rounds remain read-only. Historical group
  assignments stay intact when a participant moves to another group.
- Late additions enter the current round as pending. Cancelling a participant
  removes them from the open round and future rounds but preserves previous
  rounds. Reopening a completed trip preserves its previous rounds and permits
  a new headcount.

Search supports Arabic spelling variants and diacritics, reordered name terms,
student codes, phone numbers, sheikhs and responsible adults. `/` focuses search.
The workspace refreshes every 15 seconds while visible, except during edits.
A group is complete only when it has at least one expected participant and every
one is explicitly present. Empty groups never show an “everyone present” claim.

All mutations are audited. Trip locks serialize roster/round changes, and
participant/check versions reject stale edits from another organizer. Database
migration `20261018_32` adds trip tables without changing existing attendance or
subscription data. Trip payment records are separate from monthly subscriptions.
