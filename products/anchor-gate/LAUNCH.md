# LAUNCH — anchor-gate

Packaging for `anchor-gate`, the first micro-product of the Metites lab.
Built per `.agents/skills/product-packaging/SKILL.md`, after the product passed all
four machine checks of alienability (see **Guardrail evidence** at the end).

---

## 0. Voice of Customer & 3-Tier Competitive Brief

**Honesty note on the voice of customer.** We have `0` recorded interviews with
external engineers. The quotes below are verbatim lines from our own artifacts —
roundtable archives and handoff dossiers of the lab that shipped this tool — with
the file they were written in. When external interviews exist, they go here with
the same discipline: a date, a source, and no paraphrasing.

| verbatim line (ours, from the lab) | recorded in |
| --- | --- |
| "Пайплайн спрашивает стадию «ты готов?» и стадия отвечает «да». Это самоотчёт." | `Drafts/roundtable-archive/goalDiscussion.json` |
| "Проверять приёмку по якорю на диске: sha256 файла, размер state, код возврата тестов." | `Drafts/roundtable-archive/worker-deliveries.json` |
| "Не принимать самоотчёт агента без внешнего якоря реальности." | `/goal` anti-goals, `App State` |
| "Два исполнителя на одну задачу за 10-минутный тик — потому что на диске никто не сказал «я взял»." | `Drafts/roundtable-archive/pulseTickProtocolDiscussion.json` |

**3-tier comparison.**

1. **Direct alternatives (the same job, done another way).**
   - *LLM-as-judge in the prompt.* Fails for the documented reason: the judge is
     asked to be strict about the text it just produced, and "yes" is the cheapest
     answer. It leaves no artifact, so nothing downstream can tell.
   - *Retry libraries (`tenacity`, `backoff`, custom loops).* They bound attempts,
     not acceptance: three retries of a stage that reports "done" are three
     self-reports, not one verified artifact.
   - *CI for the pipeline code.* It proves the script runs, not that the stage's
     output is real.
2. **Adjacent (solves a neighbouring problem).**
   - *Workflow engines with human-in-the-loop interrupts (LangGraph, Temporal,
     Durable Pi stages).* Excellent at pausing a run; the pause still needs an
     oracle that says "this stage is done". `anchor-gate` is that oracle and
     nothing else.
   - *Eval frameworks (promptfoo, DeepEval).* They score model outputs offline
     against datasets; they do not gate a live stage on a file digest.
3. **Non-consumption (what people do instead — the real competitor).**
   - *A human reads the diff and clicks approve.* Works until the volume or the
     night shift makes it a rubber stamp; then it is a self-report with a human
     name on it.
   - *A checklist in a doc.* Drifts from the pipeline on the first rename, and
     nobody notices, because a stale checklist still renders.
   - *"We look at the logs."* Logs describe what ran, not what was accepted.
   We are not better than a careful human reviewer; we are the same rule applied
   at 03:00 without a person, and with an exit code instead of an opinion.

**Non-Goals.** `anchor-gate` is not a scheduler, not an observability platform,
not a prompt library, and not an eval harness. It has no model in the acceptance
path on purpose: the day acceptance needs an LLM, the whole point is lost.

**Leading vs lagging metrics.**

- *Leading (we control, weekly):* number of stages with a declared anchor, share
  of runs where acceptance came from an artifact rather than a claim, attempt
  budget consumed per stage, time-to-detect a lying stage in our own pipeline.
- *Lagging (the market decides, quarterly):* GitHub stars and forks, installs of
  the released package, inbound questions that cite a specific rule, paid kit
  conversions. Lagging metrics are recorded, never used to justify a feature.

## 1. One-line pitch (≤ 60 characters)

```
Deterministic acceptance gates for agent pipelines
```

## 2. Problem vs Reality Anchor

**The standard approach:** the pipeline asks the stage *"are you done?"* and the
stage answers *"yes"*. That answer travels through the orchestrator as a boolean,
and everything downstream — retries, notifications, publishing, billing — treats
it as fact.

**Why it breaks in production:** a model asked to judge its own output is being
asked to be strict about the thing it just produced. Under pressure to finish, the
cheapest way to satisfy the question is to say yes. The failure is not random
stupidity; it is the rational answer to the question asked. And nothing
downstream can catch it, because *"done"* is not an artifact — there is nothing to
check.

We hit this inside our own crew, and the report came from a function that had no
model in it at all:

```python
return {"ok": True, "mode": "spooled", "durable": False}   # before
```

The memory write had failed; the record was only queued to a local file. The
caller saw `ok: true` and moved on. The status was technically honest — the field
said `durable: false` — but every caller checked `ok`. We fixed it by making
`ok: true` exist only for `mode: "live"`, and the lesson generalised immediately:
**a status field that means "no error occurred" is not the same as evidence that
the effect happened.**

`anchor-gate` applies that lesson by removing the question. A stage is accepted
only when the anchors in its spec are satisfied by objects that exist outside the
model:

| anchor kind | accepted when |
| --- | --- |
| `nonempty` | the state field is not empty |
| `file` | the file exists and is at least `minBytes` long |
| `sha256` | the file's real digest matches the claim (`prefix` mode for short hashes) |
| `true` | the field is literally `true`, not `"yes"` |
| `equals` | the field equals a declared value |
| `cmd` | an argv list exits with the expected code (no shell) |

The second thing we learned the hard way is in the product too: the attempt
counter is **per stage**. In our first version it was global, so a healthy stage
inherited an earlier stage's failures and parked itself. A gate that stops good
work is worse than no gate, because it teaches people to bypass gates.

## 3. 30-second quickstart

```bash
python3 anchor_gate.py govern --spec examples/pipeline.json --state examples/state.json --dry-run
```

Against the shipped `examples/` (a `handoff.md` that is too small and has no
recorded hash), the real output is:

```json
{
  "action": "anchor_failed",
  "reason": "anchor failed, attempt 1 of 2",
  "stage": "archivist",
  "attempts": 1,
  "maxAttempts": 2,
  "anchorOk": false,
  "failedChecks": [
    {
      "kind": "file",
      "field": "handoffFile",
      "ok": false,
      "detail": "37 bytes < minBytes 300"
    },
    {
      "kind": "sha256",
      "field": "handoffSha256",
      "ok": false,
      "detail": "`handoffSha256` is empty"
    }
  ],
  "dryRun": true
}
```

Exit code `1`. Fix the artifact, record the real digest, run the same command
again:

```json
{
  "action": "proceed",
  "reason": "every anchor satisfied",
  "stage": "archivist",
  "attempts": 0,
  "maxAttempts": 2,
  "anchorOk": true,
  "failedChecks": [],
  "dryRun": false
}
```

Exit code `0`. Drop `--dry-run` to let it persist the attempt budget; run it twice
with a broken anchor and the stage parks instead of retrying forever.

## 4. Product Hunt / GitHub release block

**Tagline (≤ 60):**

```
The gate that ignores what your agent says about itself
```

**First comment (from the author):**

> We build a small autonomous crew that runs on one 3.7 GiB laptop. Four agents
> hand work to each other: research, archive, edit. The handoffs were failing and
> every failure looked the same — a stage reported success, and the next stage
> discovered there was nothing there.
>
> The bug that made me write this was embarrassing in the useful way. One function
> in our memory client returned `{"ok": true}` when the write had actually failed
> and only been queued to a local spool file. The field `durable: false` was right
> there in the same dict. Every caller checked `ok`. So for two weeks we believed
> we had durable memory; what we had was a file that got appended to.
>
> The fix was one line, and it generalised into a rule: never accept a status
> where you can check an artifact. `anchor-gate` is that rule with an interface.
> A stage declares what must exist — a file of at least N bytes, a matching
> sha256, a lint command that exits 0 — and the gate checks the objects, not the
> prose. If the artifact is not there, the stage does not pass, no matter how
> confident the report was.
>
> Two things we deliberately put in, both from bugs in our own first version.
> Attempts are counted **per stage**, because a global counter parked a healthy
> stage for crimes committed by an earlier one. And `PARKED` is a real terminal
> state, not a retry with extra steps, because a permanently broken anchor has to
> stop the pipeline rather than spin.
>
> 23 tests, standard library only, no network calls, no model in the acceptance
> path. It is not a scheduler and not an orchestrator — it answers exactly one
> question: is this stage's output real?

**Open-core continuation:** the free CLI is the gate, and it stays useful without
paying for anything. The paid **Metites Pipeline & Memory Vault Starter Kit** is
for people who want the assembled version: reference specs for the
research → archive → edit pipeline this was extracted from, CI recipes
(pre-commit, GitHub Actions, cron), the memory-bridge pattern we use for external
episodic memory (kept off the hot path, retrieved facts treated as evidence rather
than citation), and the incident notes from running it daily on constrained
hardware. Nothing in the paid kit is required for the gate to be correct — that
split is the point.

## 5. Habr / Telegram announcement

> **Мы перестали спрашивать у агента, закончил ли он работу**
>
> Наша команда из четырёх агентов живёт на ноутбуке с 3.7 ГиБ ОЗУ. Передача
> работы между этапами сломалась одинаково: этап сообщал «готово», следующий
> этап находил пустоту. Виновником оказалась не модель, а наша собственная
> функция, которая возвращала `ok: true`, когда запись фактически упала в
> локальный буфер вместо базы. В том же словаре честно стояло
> `durable: false` — но все проверяли `ok`.
>
> Правило, которое мы вывели: не принимать статус там, где можно проверить
> артефакт. Из него вырос `anchor-gate` — детерминированный гейт приёмки этапов.
> Этап объявляет, что должно существовать: файл не меньше N байт, совпадающий
> sha256, линтер с кодом 0. Гейт проверяет объекты, а не формулировки. Нет
> артефакта — этап не принят, как бы уверенно ни звучал отчёт.
>
> Внутри то, что обычно забывают: бюджет попыток считается **на этап** (иначе
> здоровый этап паркуется за грехи предыдущего), `PARKED` — настоящий
> терминальный статус, а не повтор с лишними шагами, а «данных не хватило»
> возвращает конвейер на шаг назад и сбрасывает счётчик.
>
> 23 теста, только стандартная библиотека, ни одного сетевого вызова, модель в
> контуре приёмки не участвует. Код и примеры — в репозитории, ссылка в первом
> комментарии.

## 6. Guardrail evidence

The packaging skill requires these three checks before a package is built. Results
from this build, all reproducible:

```
python3 scripts/audit_public.py --file Drafts/product-candidates/anchor-gate/LAUNCH.md
  → public audit ok                                        exit 0
grep -c '/home/<owner>/' anchor_gate.py test_anchor_gate.py README.md LAUNCH.md
  → 0  0  0  0
python3 -m unittest discover -s Drafts/product-candidates/anchor-gate -p "test_*.py"
  → Ran 23 tests — OK
```

One honest note, because the skill also requires running the repo-wide gate: the
repository-wide `audit_public.py` currently exits `1` on 14 pre-existing owner-path
leaks in `Raw/Sources/` and `Wiki/` that predate this package and are queued for
the archivist. None of them is in `anchor-gate/`; the package itself is clean, and
publishing it does not require that debt to be cleared.

No claim above exceeds what the tests demonstrate: six anchor kinds, per-stage
attempt budgets, three terminal actions (`park`, `halt`, `bounce`), atomic state
writes and a documented exit-code contract. There are no benchmarks in this
document, because we have not run any.
