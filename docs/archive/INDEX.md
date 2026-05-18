# Archive Index

Pointers to archived `PROJECT_LOG.md` session entries and implemented `DECISIONS.md` entries. The agent reads this only when it needs context older than what's in the active files.

## Sessions

- [2026-04](sessions/2026-04.md) — Scheduled auto-run; New/Viewed states + design system enforcement; International support (country/region/currency); Design overhaul (zinc/emerald, posted_at, matches page); PostHog overhaul + LLM retry; Profile componentization + signup flow
- [2026-03](sessions/2026-03.md) — Score reasoning on cards; PostHog report tool; 512MB VM memory optimization

## Decisions

- [2026](decisions/2026.md) — Salary from LLM training data (no external comp); 4 scoring workers post-VM-upgrade; App/DB VMs scale independently; `is_closed` vs `user_status` axes; subprocess+curl for Gemini; Orphan drain + backlog scoring pass + per-source budget; Zombie run reaper; Score thresholds 60/75/85; Design system (zinc/emerald/no-blue); Favorites in localStorage; `is_new` via `run_id`; First-run via scored-count
