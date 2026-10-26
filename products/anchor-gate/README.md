# anchor-gate

Deterministic acceptance gates and attempt budgets for multi-agent pipelines.

```
python3 anchor_gate.py govern --spec pipeline.json --state state.json
```

Python 3.9+. Standard library only. No network access, no model in the acceptance path.

---

## The pain

A multi-agent pipeline asks a stage "are you done?" and the stage answers
"yes". That answer is a self-report, and self-reports are wrong in a specific,
predictable way: they are wrong most often exactly when the work is hardest.

The failure is structural, not a matter of prompt quality. A model asked to
judge its own output is being asked to be strict about the thing it just
produced. Under pressure to finish, the cheapest way to satisfy the question is
to say yes — and nothing downstream can tell the difference, because "done" is
not an artifact.

`anchor-gate` removes the question. A stage is accepted only when the anchors
declared in its spec are satisfied by things that exist outside the model:

| anchor kind | accepted when |
| --- | --- |
| `nonempty` | the state field is not empty |
| `file` | the file exists and is at least `minBytes` long |
| `sha256` | the file's real digest matches what the state claims (`prefix` mode for short hashes) |
| `true` | the field is literally `true`, not `"yes"` |
| `equals` | the field equals a declared value |
| `cmd` | an argv list exits with the expected code (no shell, no string interpolation) |

The verdict is a JSON object a script can read, and the exit code is stable.
Nothing in that path can be talked into a different answer.

## What it adds beyond the anchors

Three problems appear the moment a gate exists:

1. **Retry budgets.** A broken anchor retried forever is a hung pipeline. Every
   failed attempt is counted, and the pipeline parks when the budget runs out.
   The budget is per stage: moving to another stage starts a fresh count, so a
   healthy stage never inherits another stage's failures.
2. **Terminal states.** `PARKED` and `SECURITY_HALT` are declared as halt
   stages. Reaching one is not a failure to retry but a decision to stop.
3. **Backward edges.** Sometimes the right answer is "the input was
   insufficient, go back", not "retry here". A `bounceSignal` moves the pipeline
   to an earlier stage, resets the budget and increments `backwardBounces`.

## CLI

```
python3 anchor_gate.py verify --spec pipeline.json --state state.json
python3 anchor_gate.py govern --spec pipeline.json --state state.json [--dry-run]
```

`verify` reports the anchors. `govern` verifies and then decides, persisting the
updated state (unless `--dry-run`). Example output:

```json
{
  "action": "anchor_failed",
  "reason": "anchor failed, attempt 1 of 2",
  "stage": "archivist",
  "attempts": 1,
  "maxAttempts": 2,
  "anchorOk": false,
  "failedChecks": [
    {"kind": "file", "field": "handoffFile", "ok": false, "detail": "66 bytes < minBytes 300"},
    {"kind": "sha256", "field": "handoffSha256", "ok": false, "detail": "`handoffSha256` is empty"}
  ],
  "dryRun": false
}
```

### Exit codes

| code | action | meaning |
| --- | --- | --- |
| 0 | `proceed` | every anchor satisfied, carry on |
| 1 | `anchor_failed` | anchor failed, budget remains, retry the stage |
| 2 | — | spec, state or a path in them cannot be used |
| 3 | `park` | budget exhausted, the stage is parked |
| 4 | `halt` | terminal stage, stop the pipeline |
| 5 | `bounce` | input was insufficient, go back to an earlier stage |

Note that `1` is "correctly refused", not "the tool broke": that is the value a
CI job wants.

## Spec schema

```json
{
  "specVersion": "1.0",
  "maxAttempts": 2,
  "parkStage": "PARKED",
  "haltStages": ["PARKED", "SECURITY_HALT"],
  "bounceSignal": {"field": "verdict", "value": "CONTEXT_INSUFFICIENT", "to": "scout"},
  "stages": {
    "archivist": {
      "next": "editor",
      "anchors": [
        {"field": "handoffFile", "kind": "file", "minBytes": 300},
        {"field": "handoffSha256", "kind": "sha256", "of": "handoffFile", "prefix": true},
        {"cmd": ["python3", "tools/lint.py", "--strict"], "kind": "cmd", "expect": 0, "timeout": 120}
      ]
    }
  }
}
```

Anchor options: `minBytes` (`file`), `of` and `prefix` (`sha256`), `value`
(`equals`), `cmd` / `expect` / `timeout` (`cmd`).

Relative paths in the state resolve against the directory of the spec file, so a
spec can be committed next to its artifacts and used from anywhere.

## State schema

`anchor-gate` reads a plain JSON object and writes back only what it owns:

```json
{"stage": "archivist", "stageAttempts": 0, "attemptsStage": "archivist",
 "handoffFile": "handoff.md", "handoffSha256": "d68a1aa70a8a", "verdict": "OK"}
```

It adds `stageAttempts`, `attemptsStage`, and on bounce `backwardBounces`. It
never invents domain fields. The state file is written atomically
(temp file + rename), so a crash mid-decision cannot leave half a state.

## Try it

```bash
cp -r examples /tmp/agdemo && cd /tmp/agdemo
printf 'Handoff notes for the archivist stage.\n%.0s' {1..20} > handoff.md
python3 - <<'PY'
import hashlib, json, pathlib
d = hashlib.sha256(pathlib.Path("handoff.md").read_bytes()).hexdigest()
s = json.loads(pathlib.Path("state.json").read_text())
s["handoffSha256"] = d[:12]
pathlib.Path("state.json").write_text(json.dumps(s, indent=2))
PY
python3 /path/to/anchor_gate.py govern --spec pipeline.json --state state.json
```

Delete `handoff.md` and run it twice to watch the budget exhaust and the stage
park.

## Tests

```bash
python3 -m unittest discover -s . -p "test_*.py" -v
```

23 tests, standard library only, no fixtures on disk beyond `tempfile`.

## What this is not

- Not a scheduler and not an orchestrator. It does not call agents, own a queue
  or decide what work exists. It answers one question: is this stage's output
  real?
- Not a judge of quality. An anchor proves existence and integrity, not merit.
  A 300-byte file can still be a bad file; a second gate (`cmd`) is where
  content review belongs.
- Not a sandbox. A `cmd` anchor runs whatever the spec tells it to run, with the
  spec author's privileges. Treat a spec file as code you review before running,
  because it is.

## Open-core model

- **Free (this directory, MIT):** the `anchor-gate` CLI, the six anchor kinds,
  the attempt budget, park/halt/bounce semantics, the tests. Enough to gate a
  pipeline on its own.
- **Paid: `Metites Pipeline & Memory Vault Starter Kit`** — the parts that are
  ours and are not in the free CLI: reference specs for the
  scout → archivist → editor pipeline this tool was extracted from, the spec
  validator plus CI recipes (`pre-commit`, GitHub Actions, cron), the
  memory-bridge pattern (durable external bank for `Experiences`, kept off the
  hot path, results treated as evidence rather than citation), and the
  incident notes from running it daily on a 3.7 GiB host.

The split is honest: the gate is a gate whether or not anyone pays. What is
sold is the accumulated operational detail, not permission to have correct
acceptance logic.

## Provenance

Extracted from the `metites_pulse.py` governance layer of the Metites agent
crew, where `verify_stage_anchor`, `evaluate_governance` and `halt_gate` (108
lines, 16 tests) ran the scout → archivist → editor pipeline against a real
knowledge base. This package is the portable subset: no owner paths, no host
assumptions, no dependencies.
