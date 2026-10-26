---
schema: paperclip/task@1
id: news-hfs-sweep
title: News radar sweep
owner: news
cadence: at most hourly while the snapshot is older than 60 minutes
project: verified-daily-dispatch
inputs:
  - sources config
  - Drafts/news-radar/history.json
outputs:
  - Drafts/news-radar/latest.json
  - pipeline/newsRadar
acceptance: Snapshot digest recorded, no source missing from the audit list.
---

# News radar sweep

Owner: `news`. Cadence: at most hourly while the snapshot is older than 60 minutes.

## Steps

- Fetch every source with a timeout and a size cap.
- Pre-rank with the deterministic lexicon, then judge only the leading candidates.
- Drop items already seen in history and store the rest.

## Acceptance

Snapshot digest recorded, no source missing from the audit list.

## Failure mode

If the acceptance anchor is missing, the task is not done: record the missing
anchor, hand the task back, and do not repeat the same attempt blindly.
