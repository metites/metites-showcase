# recall-ladder

Read a zero-result memory recall honestly, and choose the threshold from the data
instead of from habit.

```
python3 recall_ladder.py explain --response bank.json --threshold 0.25
python3 recall_ladder.py lesson --file lesson.md
```

Python 3.9+. Standard library only. No network access, no model in the decision path.

---

## The pain

A vector or reranking memory bank answers `{"ok": true, "results": []}` for two
completely different situations:

- nothing relevant exists, and you should record a new lesson;
- six relevant records were retrieved, and the relevance threshold threw all of
  them away.

Both look like `kept: 0`. Both look like "memory is empty". A pipeline that treats
them the same starts writing duplicate lessons in the first case and loses its
existing knowledge in the second — and nothing in the logs distinguishes the two,
because the API answered `ok`.

This is the same defect as reading "no results" as "nothing to do": the absence of
a result set is not the absence of data. `recall-ladder` separates the four facts
behind one number and shows the threshold curve that produced it.

| verdict | what is true | exit code |
| --- | --- | --- |
| `ok` | at least one record survived the threshold | 0 |
| `threshold_ate_all` | records existed, the threshold dropped them | 3 |
| `bank_empty` | the bank answered, and there is nothing in it | 0 |
| `source_unreachable` | the bank did not answer; the empty list means nothing | 4 |

## Quickstart

```bash
$ python3 recall_ladder.py explain --response bank.json --threshold 0.25
threshold_ate_all: kept 0/6 at 0.25
best score: 0.22 | recommended: 0.15
next: снизить порог до 0.15
  >= 1.0   keeps 0
  >= 0.5   keeps 0
  >= 0.35  keeps 0
  >= 0.25   keeps 0
  >= 0.15  keeps 6
  >= 0.0   keeps 6
```

The same call with `--json` emits the full evidence block: status, kept, total,
best score, the whole ladder, the recommended rung, and the next action.

The recommendation never goes below `--floor` (default `0.15`). If even the floor
keeps nothing, the tool returns `null` and says "change the query, not the number":
lowering a threshold until something appears is how a bank turns into noise.

## The lesson contract

Recording the lesson is the other half of the loop. `lesson` validates the shape we
write back to the bank, so a later recall can trust it:

```
claim:    what we now believe, one falsifiable sentence (>= 20 characters)
anchor:   sha256:<digest> or a repo path — machine-checkable, not "I looked"
evidence: where the claim comes from (>= 20 characters)
```

```bash
$ python3 recall_ladder.py lesson --file lesson.md
lesson rejected: [{'code': 'missing_fields', 'fields': ['anchor']}]
```

A lesson without an anchor is an opinion, and opinions are what made the recall
look empty in the first place.

## Input shapes

`explain` accepts a bank response (`{"ok": …, "results": […]}`), a bare list of
results, or a list of scores. Each result needs one score field: `rerankerScore`,
`score` or `relevance`. Missing scores and non-object rows are rejected with a
usage error instead of being silently counted as zero — a record with an unknown
score is not a record with score 0.

## What is verified

36 tests, all green (`python3 -m unittest test_recall_ladder`): parsing of four
response shapes, the four verdicts, the threshold-equality boundary, every ladder
rung, the floor rule, all four CLI exit codes, stdin input, and six lesson-contract
cases. There is no claim in this README that is not pinned by one of them.

## Non-goals

`recall-ladder` does not embed, does not rerank and does not call any service. It
reads a response you already have and a threshold you already chose. Tuning the
embedding model, the chunking and the query expansion is your part of the loop.

## License

MIT.
