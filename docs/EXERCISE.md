# Candidate Brief — Dispatch Triage Agent

**Time budget:** 90 minutes. Work in this repo, commit as you go.

You have inherited a small LangGraph + FastAPI + JSON-RPC sub-agent from a teammate who
has left. It decides whether an incoming field-service work order gets a technician booked
automatically, gets queued for a human coordinator, or gets rejected. It is about to sit
behind a parent orchestrator that will send it real ticket traffic.

Read [`README.md`](../README.md) first — it documents the **intended** behaviour, the
intended graph flow, and the dispatch rules. **Treat the README as the specification:
where the code and the README disagree, the README is right.**

🎬 [`docs/dispatch-rules.html`](dispatch-rules.html) animates the same rules if you prefer
to see them run.

---

## Setup

```bash
uv sync --extra dev
uv run pytest -q
```

You should see **11 failed, 40 passed**. Each part below covers one defect area, with the
failing tests already written against it. The three areas are independent and live in
different layers, so you can work them in any order and watch the failure count drop.

**Ground rules for every part:**

1. Reproduce the failure first, and describe in your own words what the code actually
   does versus what the README says it should do.
2. Fix the cause, not the symptom. Keep changes surgical.
3. Do not weaken, skip, or delete a test to make it pass. If you believe a test asserts
   the wrong thing, say so and justify it.

---

## Part 1 — Two tickets take the wrong road (≈30 min)

**Layer:** the graph — `src/dispatch_agent/graph/`

Two different tickets come out of the graph having walked a path the README does not
describe. The `audit` list is your microscope: it records every node that actually ran, in
order.

### Symptom A — the capacity rule is only half applied

`capacity_check` is where the README's capacity rule lives. Both clauses must hold before a
ticket is booked: `free_minutes >= estimated_minutes + CAPACITY_BUFFER_MINUTES`, **and**
`estimated_minutes <= MAX_AUTO_DISPATCH_MINUTES` (240). Two tickets say otherwise:

```jsonc
// 1. no slack left — the buffer clause should have queued this
{ "estimated_minutes": 90 }        // depot reports 110 free; the rule wants 90 + 30 = 120
→ { "decision": "auto_dispatch", "technician_id": "SFO-02-CERTIFIED-01" }   // ✗

// 2. a full-day job — the job-size clause should have queued this
{ "estimated_minutes": 300 }       // depot reports 480 free; ceiling is 240
→ { "decision": "auto_dispatch", "technician_id": "SFO-02-CERTIFIED-01" }   // ✗
```

Both come back `auto_dispatch` with a technician attached. The pattern behind them: the
branch is taken whenever the depot's raw number merely covers the job. The buffer is gone
and the ceiling is gone — the depot's last 20 minutes of slack get promised away, and a
five-hour job is booked as if it were routine.

Note what is *not* wrong. `free_minutes` in the response is the depot's real number, and
`capacity_check` itself evaluates both clauses correctly — set a breakpoint in it and you
will watch it get the right answer.

> Hint: `capacity_check` computes the verdict; a separate router function chooses the
> branch. Ask what `capacity_check` puts into state for that decision, then grep for who
> reads it. If the answer is "nobody", you have found a second, drifted copy of a rule that
> is supposed to live in exactly one place — and the fix is to delete the copy, not to
> patch it.

### Symptom B — a junk ticket goes shopping for a technician

A ticket with an empty `asset_id` is invalid, and `validate` does spot it — the node
computes exactly the right error string. But the ticket does not come back `rejected`; it
sails on to `capacity_check`, burns a depot lookup, and comes out the far end as an
ordinary undecided-but-serviceable work order.

```
   ticket: asset_id = ""        ← validate knows this is garbage

   📡  the depot receives an availability lookup for it anyway
   🔧  and the ticket carries on through nodes that only real work should reach
   📄  rejection_reason comes back empty — as if nothing was ever wrong

   (the test asserts the depot is never called — and counts the calls)
```

The README's **short-circuit rule** says an invalid ticket goes straight to `finalize` with
an audit of exactly `["validate", "triage", "finalize"]`, because a malformed ticket must
not burn a downstream depot lookup or momentarily hold a technician slot that a real ticket
could have used.

> Hint: the router that implements the short-circuit is right there in `nodes.py` and reads
> correctly — take it at its word and ask instead whether the thing it reads ever arrives.
> A LangGraph node does not mutate state in place; the dict it **returns** is the update
> that gets merged. Anything a node computes and does not return never happened as far as
> the rest of the graph is concerned. Print the state your node returns, not the state it
> holds.

### What must hold when you are done

| Ticket | `decision` | `audit` |
|---|---|---|
| `NO_POWER`, 90 min, depot 480 free | `auto_dispatch` | `validate, triage, capacity_check, assign_technician, finalize` |
| `NO_POWER`, 90 min, depot 110 free | `needs_scheduling` | `validate, triage, capacity_check, queue_for_scheduling, finalize` |
| `NO_POWER`, 300 min, depot 480 free | `needs_scheduling` | `validate, triage, capacity_check, queue_for_scheduling, finalize` |
| `asset_id=""` | `rejected` | `validate, triage, finalize` |
| `WARRANTY_QUESTION` | `rejected` | `validate, triage, finalize` |

**Relevant tests:** `tests/test_graph_flow.py` — `test_thin_capacity_queues_the_ticket`,
`test_capacity_buffer_is_respected`, `test_oversized_job_never_auto_dispatches`,
`test_invalid_ticket_is_rejected_without_calling_the_depot`, `test_invalid_duration_is_rejected`.
`test_dispatched_ticket_runs_every_node_in_order` and
`test_job_at_the_auto_dispatch_ceiling_still_dispatches` are green — keep them that way.

---


## Part 2 — The depot cache remembers the wrong things (≈25 min)

**Layer:** `src/dispatch_agent/services/availability_client.py`

Every site runs **two independent technician pools** — `certified` (safety and urgent work)
and `general` (routine work). They have separate capacity. `capacity_check` asks the depot
for the free minutes of one specific *site + pool* pair, and answers are cached to spare the
downstream service.

Two things go wrong, and they share a home in this one file.

### Symptom A — a blip becomes permanent

The fail-closed rule is deliberate: an unusable depot means `0` free minutes, so the ticket
falls through to `needs_scheduling` rather than booking a technician on a guess. What is not
deliberate is how long that `0` sticks around.

```
  09:00  depot times out         →  (SFO-02, certified) = 0    ✓ fail closed, correct
  09:01  depot is healthy again  →  (SFO-02, certified) = 0    ✗ depot says 480
  17:00  depot still healthy     →  (SFO-02, certified) = 0    ✗ and never asked again
```

The depot is never contacted again for that pair for the life of the process. Every safety
ticket at that site is queued for a human all afternoon because of one timeout at nine in
the morning. README §"Availability lookups" is explicit: `0` is a fallback, not an answer,
and must never be remembered.

### Symptom B — a brand-new client is born already knowing things

```
   client A  ─ ask (BBB-01, certified) ─→  240      ✓ that is A's depot answer

   client B  ─ created fresh, never used before
   client B  ─ ask (BBB-01, certified) ─→  240      ✗ B's depot answers 15
```

Two `AvailabilityClient` instances are supposed to be independent — including the
long-lived one the graph itself holds. Today something written through one is visible
through the other, even though `__init__` reads as though every client gets its own.

> Hint: both symptoms are visible in `AvailabilityClient` alone — no graph, no network.
> Instantiate two in a REPL, hand each a stub, and after every lookup print what each
> client has stored — then ask whether `a.cache is b.cache`. Two questions fall out of what
> you see: *which values deserve to be stored at all*, and *whose dictionary is actually
> being written to when the caller passed none in*.

### Already correct — do not "fix" these

The failure behaviour itself is specified in README §"Availability lookups": an unreachable
or erroring depot **fails closed** and reports `0` free minutes, so the ticket falls through
to `needs_scheduling`. Green tests guard this. Keep them green — the defect is that the `0`
is remembered, not that it is returned.

| Scenario | Expected |
|---|---|
| depot fails once, then recovers | second lookup returns the depot's **real** number |
| client A caches `(BBB-01, certified)`; fresh client B looks it up | B returns **its own** depot's answer |
| `(AAA-01, certified)` = 240, then `(AAA-01, general)` = 30 | second lookup returns `30` |
| same pair looked up twice on one client | second call served from cache, no second HTTP call |
| depot unreachable / answers `503` | `0` free minutes |
| triage while the depot is down | `needs_scheduling`, `technician_id` empty |

**Relevant tests:** `tests/test_availability_client.py` — `test_a_failed_lookup_is_not_cached`,
`test_each_client_keeps_its_own_cache` (failing); `test_skill_is_part_of_the_cache_key`,
`test_repeated_lookup_is_served_from_cache`, `test_unreachable_depot_reports_no_capacity`,
`test_error_response_reports_no_capacity`, `test_ticket_is_queued_when_the_depot_is_down`
(green — keep them that way).

---

## Part 3 — The wire protocol is subtly off-spec (≈25 min)

**Layer:** `src/dispatch_agent/rpc/` and `src/dispatch_agent/api.py`

The parent orchestrator speaks strict JSON-RPC 2.0. Single calls, notifications and batches
all appear to work — the obvious tests are green. Two shapes of real traffic, both described
in README §"JSON-RPC contract", still come back wrong.

### Symptom A — a request is silently mistaken for a notification

The orchestrator sends low-priority tickets as **notifications**: a request object with
**no `id` member at all**. Per the spec, the server does the work and replies with nothing.
That much works.

But some of its clients serialise a real, answer-me request with an explicit `"id": null`
(a JSON encoder that emits every field). The spec is precise about the difference: a
**missing** `id` member is a notification; an `id` that is *present and null* is an ordinary
request, and gets an ordinary envelope back with `"id": null` echoed in it.

```
  ──→  {"jsonrpc":"2.0","id":null,"method":"dispatch.policy"}     ← "id" IS present

  EXPECTED                                OBSERVED
  ────────────────────────────────        ────────────────
  HTTP 200                                HTTP 204
  {"jsonrpc":"2.0","id":null,             (empty body)
   "result":{…}}                          the caller waits for a policy
                                          it will never be sent
```

The same confusion drops that member from a **batch** array, so the caller gets back fewer
responses than it sent calls and cannot line them up.

> Hint: by the time a JSON-RPC request has become a `JsonRpcRequest`, `id` is `None` in
> both cases — pydantic filled in the default and the distinction is gone. Whatever answers
> "does this caller want a reply?" has to be asked of something that still knows what the
> client actually sent.

### Symptom B — a batch comes back shuffled

The orchestrator groups calls into a **batch** and matches responses to requests **by
position**. The array it gets back is the right length and every envelope is individually
correct — but a batch containing a real `dispatch.triage` (which does downstream work and
takes tens of milliseconds) next to a cheap `dispatch.policy` comes back the other way
round.

```
  ──→  [ {id:"b-5", method:"dispatch.triage", …},   ← slow
         {id:"b-6", method:"dispatch.policy"} ]     ← fast

  EXPECTED                          OBSERVED
  ──────────────────────────        ─────────────────────────────
  [ {id:"b-5", result:{…}},         [ {id:"b-6", result:{…}},
    {id:"b-6", result:{…}} ]          {id:"b-5", result:{…}} ]

  a batch of equally cheap calls looks fine — which is why nobody noticed
```

The README requires responses **in request order, regardless of how long any individual
member took to run**. A parent that zips its request list against this array attributes a
triage decision to the wrong ticket.

> Hint: the batch path fans the calls out concurrently, which is correct and worth keeping.
> Look at how the results are collected back in, and ask what ordering that particular
> `asyncio` helper promises. Concurrency and ordering are separable: there is a one-line
> way to keep the first and fix the second.

### Do not change the happy path

`test_triage_over_rpc`, `test_policy_method`, `test_agent_describe`, the two envelope-shape
tests, the three `-32600` malformed-request tests, the two notification tests and the four
existing batch tests are green today and must stay green.

**Relevant tests:** `tests/test_rpc.py` — `test_explicit_null_id_is_an_ordinary_request`,
`test_batch_keeps_an_explicit_null_id_member`, `test_batch_keeps_request_order_when_a_call_is_slow`,
`test_batch_order_survives_notifications_and_slow_calls`.

---

## Part 4 — Write-up (≈10 min)

Create `FINDINGS.md` containing:

1. One short section per part: the root cause, your fix, and how you verified it.
2. Which defect you consider most severe in production, and why.
3. The single change you would make next if you had another day, and why.

---

## What we are looking for

- Can you read an unfamiliar graph-based codebase and reason about control flow from an
  execution trace?
- Do you fix root causes rather than patching over symptoms?
- Do you reason carefully about shared mutable state and about what is safe to cache?
- Do you take a written protocol contract seriously, including the parts nobody exercises
  until production?

## What we are not looking for

- Formatting, naming, or style rewrites.
- Rewriting the architecture. Keep changes surgical.
- Adding an LLM. This agent is deliberately deterministic.

## Deliverables

- A green `uv run pytest -q` (51 passed).
- `FINDINGS.md`.
- Clean, reviewable commits.
