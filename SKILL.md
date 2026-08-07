---
name: cc-switch-adapter
description: >
  closed-pipe adapter for registering, migrating, dispatching, diagnosing, and
  explicitly governing skills through cc-switch. Use for skill installation,
  provider/profile changes, canonical IDs, SSOT projections, or parent-link
  failures.
---

# cc-switch adapter

`closed-pipe` means every mutation has one explicit route: cc-switch's unified
SSOT, one canonical DB row, per-app enable columns, and child projections.
Runtime state is authoritative: read `settings.json`, the DB schema, and the
filesystem before using repository documentation.

## Invariants

- SSOT is `skillStorageLocation` (`~/.agents/skills` for `unified`, otherwise
  `~/.cc-switch/skills`). App directories are projections, never credential or
  skill ownership records.
- A skill ID is `local:<single-name>` or `owner/repo:<safe/path>`. Its install
  `directory` is one safe, non-hidden path segment and is unique in `skills`.
- `park` creates the row with every `enabled_*` false and no projection.
  `install-enable` is the named-app form: projection first, then its DB flag.
- `live` is DB enable plus projection. A profile slot is a user snapshot and
  may be stale or dangling; it never proves that a skill is live.
- Official app profile scopes are Claude and Codex. Other apps use dispatch;
  they must not be written into profile skill arrays.
- Uninstall removes the skill row, SSOT/projections, and lock entry, but leaves
  profile snapshots untouched. `doctor` reports the resulting dangling ID;
  `slot scrub` is a separate, explicit user decision.

## Runtime-first workflow

```bash
python3 "$SKILL_DIR/doctor.py" --root "$ROOT"       # read-only baseline
python3 "$SKILL_DIR/remedy.py" --root "$ROOT"       # dry-run plan
```

`SKILL_DIR` is this installed directory. `ROOT` is optional and is used only
for an isolated fixture home. A parent `skills` directory that is a symlink is
a fatal parent-link condition; stop and run `migrate` before any mutation.

## Commands

| Intent | Command | Mutation |
| --- | --- | --- |
| Register or recover an SSOT skill | `pipe.py register --id ID --directory DIR --source PATH [--app APP]` | SSOT, row, optional app projection |
| Enable/disable one app | `pipe.py dispatch --id ID --app APP --enable\|--disable` | one projection and enable flag |
| Inspect or explicitly edit a snapshot | `pipe.py slot list\|add\|remove\|resnap\|scrub` | profile JSON only, with `--apply` |
| Remove a skill | `pipe.py uninstall --id ID [--keep-ssot] [--apply]` | row, SSOT/projections, lock; never profiles |
| Change a skill's identity or directory | `pipe.py migrate --from-id OLD --to-id NEW --directory DIR [--apply]` | preserves enables, projections, lock, and exact profile ID references |

All mutating commands are dry-run unless `--apply` is supplied, except
`register` and `dispatch`, which are direct closed-pipe operations. Registering
an existing ID never renames it and a directory collision is rejected; use
`migrate` so the old projection can be archived and the DB/profile transaction
is atomic.

## Profile and fat-snapshot policy

`null` means a profile app was never captured; `[]` means it was captured empty;
an ID list is a snapshot, not live state. If a bound profile contains IDs that
are not live, `doctor` reports a policy warning and points to `slot resnap` or
`slot scrub`; it never enables skills automatically. Identity migration is the
only automatic profile edit, and it rewrites the exact old canonical ID.

## Completion checks

1. Run `doctor.py --full` again. The target is zero FATAL and zero design
   ERROR; hygiene/policy notes must be understood, not hidden.
2. Confirm `content_hash.py` matches the DB and Github lock entry.
3. For a named app, confirm the child projection points to the SSOT leaf; for
   park, confirm all enable flags are false and no projection exists.
4. Never delete or hand-edit SSOT/projections to repair a finding. Use
   `migrate`, `register`, `dispatch`, or an explicit `slot` operation.

See `experience.md`, `project-slot.md`, `doctor.md`, `file-layout.md`, and
`db-schema.md` for evidence-oriented details.
