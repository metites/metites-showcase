---
schema: paperclip/task@1
id: morning-goal-lint
title: Morning goal lint
owner: planner
cadence: daily at 09:00 MSK, first action of the day
project: verified-daily-dispatch
inputs:
  - /goal
  - /pipeline
  - acceptance anchors on disk
outputs:
  - Drafts/goal-lint-latest.json
  - pipeline/goalLint
acceptance: Exit code 0, every declared criterion anchored, three daily tracks emitted.
---

# Morning goal lint

Owner: `planner`. Cadence: daily at 09:00 MSK, first action of the day.

## Steps

- Re-read the goal tree, never a cached copy of it.
- Check each declared criterion against a file digest or a command exit code.
- Report a criterion that is not declared instead of inventing it.
- Decompose the day into content, discovery and micro-product tracks.

## Acceptance

Exit code 0, every declared criterion anchored, three daily tracks emitted.

## Failure mode

If the acceptance anchor is missing, the task is not done: record the missing
anchor, hand the task back, and do not repeat the same attempt blindly.
