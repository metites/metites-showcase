---
schema: paperclip/task@1
id: aeo-discovery
title: AEO discovery and showcase build
owner: scout
cadence: once per workday, then after every new research note or knowledge change
project: verified-daily-dispatch
inputs:
  - goal-lint discovery track
  - Wiki/
outputs:
  - Drafts/aeo-research-<date>.md
  - Drafts/public-showcase/
acceptance: Showcase files parse, robots allows every AI crawler, public audit at exit code 0.
---

# AEO discovery and showcase build

Owner: `scout`. Cadence: once per workday, then after every new research note or knowledge change.

## Steps

- Find the surfaces where other agents look for sources and record evidence per surface.
- Rebuild the showcase from canonical notes and published packets.
- Audit every generated file before it is considered publishable.

## Acceptance

Showcase files parse, robots allows every AI crawler, public audit at exit code 0.

## Failure mode

If the acceptance anchor is missing, the task is not done: record the missing
anchor, hand the task back, and do not repeat the same attempt blindly.
