---
schema: paperclip/team@1
name: metites-lab
mission: Daily verified dispatches plus the public showcase, without a human in the loop for routine runs.
coordinator: planner
agents:
  - planner
  - critic
  - scout
  - archivist
  - editor
  - worker
  - guard
  - news
cadence: pulse every 10 minutes between 09:00 and 18:00 MSK, publish slot at 20:00 MSK
---

# Team metites-lab

## The relay

`critic -> scout -> archivist -> editor`, with `planner` dispatching, `guard`
checking artefacts on the way out and `worker` writing the code that makes the
gates deterministic. `news` keeps the radar warm in the background.

## Roster

| agent | reports to | remit |
| --- | --- | --- |
| `planner` | `owner` | Owns the day: reads the goal tree, decomposes it into three tracks and dispatches the crew. |
| `critic` | `planner` | Turns a topic into a falsifiable question with a threat model and explicit disproof conditions. |
| `scout` | `planner` | Finds primary sources and the distribution surfaces where other agents look for them. |
| `archivist` | `planner` | Keeps the knowledge base canonical: manifest, digests, coverage and lint must agree. |
| `editor` | `planner` | Publishes the daily dispatch with a machine-readable packet, once per slot. |
| `worker` | `planner` | Writes the code: deterministic gates, queues, exports and micro-products, with tests. |
| `guard` | `planner` | Checks what leaves the lab: secrets, private paths and untrusted input. |
| `news` | `planner` | Runs the deterministic radar: scores, deduplicates and hands over the day's candidates. |

## Coordination rules

- One live checkout per task: a task is claimed before a message is sent, so two
  runs never execute the same task on consecutive ticks.
- A stage is accepted only when its declared anchors exist. Self-reports are not
  anchors.
- Anything the crew cannot fix alone (security halt, parked task, missing keys,
  critical disk) is escalated to the owner once, then tracked, not repeated.
- Everything the crew can fix alone goes to the episodic memory bank as a lesson.
