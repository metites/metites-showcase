---
schema: paperclip/task@1
id: daily-signal-dispatch
title: Daily signal dispatch
owner: editor
cadence: in the publish slot, one issue per slot
project: verified-daily-dispatch
inputs:
  - pipeline/activeTask
  - handoff dossier
  - canonical note
outputs:
  - @metites_signal issue
  - channel/publishedIssues
acceptance: Strict lint and public audit at exit code 0, packet block present, issue number incremented once.
---

# Daily signal dispatch

Owner: `editor`. Cadence: in the publish slot, one issue per slot.

## Steps

- Critic sharpens the question, scout collects primary sources.
- Archivist ingests, lints and writes the handoff.
- Editor publishes with the packet and increments the issue counter.

## Acceptance

Strict lint and public audit at exit code 0, packet block present, issue number incremented once.

## Failure mode

If the acceptance anchor is missing, the task is not done: record the missing
anchor, hand the task back, and do not repeat the same attempt blindly.
