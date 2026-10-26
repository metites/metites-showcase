# metites-company-template

An AI company as files: `COMPANY.md`, a team, eight role contracts, one project
and four recurring tasks — exported by a generator, validated by tests, portable
to another host.

```
python3 export_company.py               # write ./company
python3 export_company.py --check       # exit 1 if the tree drifted from the tables
python3 -m unittest test_company_template
```

Python 3.9+. Standard library only. No network access, no model in the package.

---

## The pain

A crew of agents usually lives as one long prompt plus a pile of state keys. Both
drift. The prompt grows until no one reads it, the state keys get renamed, and
nobody can answer three basic questions: which role owns this task, what goal does
it serve, and what does "done" mean for it this week.

The failure is structural rather than a matter of prompt quality. Roles are not
artefacts, so every run re-derives them slightly differently, and two runs can
execute the same task twice because nothing on disk says who claimed it.

This template makes the company an artefact tree with three properties:

| property | how it is enforced |
| --- | --- |
| every role is a file with a machine-readable contract | `agents/<slug>/AGENTS.md` with `schema`, `name`, `role`, `reportsTo`, `skills` |
| every link resolves | `reportsTo` must name an existing role or `owner`; `COMPANY.md` includes must exist as files |
| nothing private ships | home paths, API keys and tokens are scanned per file; the public audit must return zero findings |

## Layout

```
company/
  COMPANY.md                    mission, north star, H1/H2/H3, acceptance criteria
  teams/metites-lab/TEAM.md     roster, relay order, coordination rules
  agents/<slug>/AGENTS.md       8 roles: duties, reads, emits, never
  projects/PROJECT.md           milestones and artefacts
  tasks/<slug>/TASK.md          cadence, steps, acceptance, failure mode
```

The exported tree is generated: edit the `ROLES` and `TASKS` tables in
`export_company.py`, not the files, then re-export. `--check` fails when the two
disagree, which is what keeps a company description from rotting.

## The eight roles

| role | reports to | remit |
| --- | --- | --- |
| `planner` | owner | decomposes the goal tree into the day's tracks and dispatches |
| `critic` | planner | turns a topic into a falsifiable question with a threat model |
| `scout` | planner | finds primary sources and distribution surfaces with evidence |
| `archivist` | planner | keeps manifest, digests and lint canonical, writes the handoff |
| `editor` | planner | publishes the dispatch with a machine-readable packet |
| `worker` | planner | writes deterministic gates, queues and exports, with tests |
| `guard` | planner | audits everything that leaves the lab |
| `news` | planner | runs the deterministic radar and hands over candidates |

## The four tasks

`morning-goal-lint` (daily, 09:00), `news-hfs-sweep` (hourly, ≤ 60 min stale),
`daily-signal-dispatch` (publish slot), `aeo-discovery` (per workday, then after
every knowledge change). Each one declares inputs, outputs, an acceptance anchor
and a failure mode, so a run can be judged without reading its transcript.

## What the tests actually check

15 tests, each pinned to a file rather than to a claim:

- every `.md` starts with a parseable Paperclip frontmatter block and a non-empty body;
- exactly eight agents, unique slugs, all required fields non-empty;
- `reportsTo` resolves to a real role, and `planner` reports to `owner`;
- `COMPANY.md` includes, team roster and project task list all resolve to files;
- every task declares a real owner, inputs, outputs and an acceptance line;
- `COMPANY.md` names H1/H2/H3 and the acceptance criteria;
- zero home paths, zero key markers, zero matches of the public audit scanner;
- export is idempotent, `--check` detects drift and missing files, and `--force`
  is required to overwrite a file a human edited.

## Format reference

The file set (`COMPANY.md`, `teams/<team>/TEAM.md`, `agents/<slug>/AGENTS.md`,
`projects/PROJECT.md`, `tasks/<slug>/TASK.md`) and the frontmatter fields
(`name`, `role`, `reportsTo`, `skills`) follow the Paperclip company format as
approved for this package. The Paperclip specification files themselves are not
vendored here, so the generator emits the approved fields and the tests validate
them; it does not claim to reproduce an unseen schema version.

## Non-goals

This is not a runtime. It exports the description of a company; the scheduler,
the state store and the model routing stay with your own orchestration layer.
The template deliberately contains no prompts that depend on one vendor's API and
no scheduling daemon: those are the parts every team already has.

## License

MIT for the generator and the exported template. The role descriptions are
written for this crew; rename them freely.
