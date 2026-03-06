# HEARTBEAT.local.md — Example Override

Copy this file to `config/HEARTBEAT.local.md` (gitignored) to add personal thresholds and context. The loader merges HEARTBEAT.md with HEARTBEAT.local.md at runtime. If HEARTBEAT.local.md is missing, the heartbeat runs on public defaults only.

---

## Goals (local overrides)

- Stale goal threshold: N days without progress (e.g. 5).
- List any goal tags or names that always warrant a nudge.

---

## Calendar (local overrides)

- Event tags or keywords that mean "always surface" (e.g. "interview", "doctor").
- Lead time in minutes for "meeting starting soon" (e.g. 15).

---

## Email (local overrides)

- Unread count threshold above which to surface (e.g. 20).
- Sender patterns or labels that are high-priority.

---

## Wellbeing Check-in (local only — never commit real content)

- Time window (e.g. 13:00–19:00) and minimum hours between check-ins (e.g. 36).
- Any personal signals or triggers go here; this file must not be committed.

---

## Coding Tasks (optional — P2)

- Stalled task threshold: days since last activity (e.g. 3).
- Open TODOs or uncommitted work older than N hours (e.g. 24).
- Repo path(s) to check (e.g. ~/Projects/active/agents/remy).
