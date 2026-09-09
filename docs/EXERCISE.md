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

You should see **14 failed, 30 passed**. Each part below covers one defect area, with the
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

### Symptom A — a booked ticket is never actually decided

A clean, serviceable ticket, at a site with plenty of free depot capacity. A technician
*is* reserved and the SLA *is* stamped — and yet the caller gets this back:

```jsonc
// request
{ "issue_code": "NO_POWER", "estimated_minutes": 90,
  "site_code": "SFO-02",    "reported_hours_ago": 4 }     // depot has 480 free minutes

// response
{
  "decision":      "pending",              // ✗ README says "auto_dispatch"
  "technician_id": "SFO-02-CERTIFIED-01",  // ✓ somebody was booked
  "sla_minutes":   60,                     // ✓ the clock was set
  "rejection_reason": "",
  "audit": [ … ]                           // ← read this. it is shorter than it should be
}
```

`"pending"` is the *initial* value the service seeds state with before the graph runs. The
orchestrator downstream branches on `decision`, so a ticket in this shape holds a
technician that no system will ever recognise as booked.

> Hint: `audit` records every node that actually ran, in order. Compare the audit you get
> for this ticket against the audit for a ticket that gets **queued** instead of booked —
> the two paths are supposed to differ by exactly one node. Then compare both against the
> mermaid diagram in README §"Decision flow" and ask which node stamps `decision`.

### Symptom B — a junk ticket goes shopping for a technician

A ticket with an empty `asset_id` is invalid. `validate` notices it and records the error,
and the ticket does come back `rejected` with the right reason. So far so good.

The problem is what happens on the way there. The README's **short-circuit rule** says an
invalid ticket goes straight to `finalize`; it must never reach `capacity_check`, because a
malformed ticket must not burn a downstream depot lookup or momentarily hold a technician
slot that a real ticket could have used.

```
   ticket: asset_id = ""        ← we already know this is garbage

   📡  the depot receives an availability lookup for it anyway
   🔧  and the ticket carries on through nodes that only real work should reach

   the verdict is right; the road taken to reach it is not
   (the test asserts the depot is never called — and counts the calls)
```

> Hint: routing in this graph is done by plain functions that read state and return a
> branch name. `validate` runs before them and leaves something behind in state. Ask
> whether anything downstream ever looks at it before deciding where to go next — and note
> that `finalize` reading it at the very end is not the same as the graph acting on it.

### What must hold when you are done

| Ticket | `decision` | `audit` |
|---|---|---|
| `NO_POWER`, 90 min, depot 480 free | `auto_dispatch` | `validate, triage, capacity_check, assign_technician, finalize` |
| `NO_POWER`, 90 min, depot 100 free | `needs_scheduling` | `validate, triage, capacity_check, queue_for_scheduling, finalize` |
| `asset_id=""` | `rejected` | `validate, triage, finalize` |
| `WARRANTY_QUESTION` | `rejected` | `validate, triage, finalize` |

**Relevant tests:** `tests/test_graph_flow.py` — `test_dispatched_ticket_reaches_a_terminal_decision`,
`test_dispatched_ticket_runs_every_node_in_order`, `test_technician_comes_from_the_right_pool`,
`test_invalid_ticket_is_rejected_without_calling_the_depot`, `test_invalid_duration_is_rejected`.

---


## Part 2 — The depot gives out the wrong number (≈25 min)

**Layer:** `src/dispatch_agent/services/availability_client.py`

Every site runs **two independent technician pools** — `certified` (safety and urgent work)
and `general` (routine work). They have separate capacity. `capacity_check` asks the depot
for the free minutes of one specific *site + pool* pair, and answers are cached to spare
the downstream service.

Two things go wrong, and they share a home in this one file.

### Symptom A — one pool answers for the other

```
 site SFO-02 today
 ┌──────────────────────────┬──────────────────────────┐
 │  certified pool          │  general pool            │
 │  240 free minutes        │   30 free minutes        │
 └──────────────────────────┴──────────────────────────┘

   ask for (SFO-02, certified)  →  240   ✓
   ask for (SFO-02, general)    →  240   ✗   the depot's real answer is 30
```

A routine job at that site now looks like it has 240 minutes of general-pool capacity it
does not have, and gets auto-dispatched into a pool that is already full.

### Symptom B — a brand-new client is born already knowing things

```
   client A  ─ ask (BBB-01, certified) ─→  240      ✓ that is A's depot answer

   client B  ─ created fresh, never used before
   client B  ─ ask (BBB-01, certified) ─→  240      ✗ B's depot answers 15
```

Two `AvailabilityClient` instances are supposed to be independent — including the
long-lived one the graph itself holds. Today something written through one is visible
through the other.

> Hint: both symptoms are visible in `AvailabilityClient` alone — no graph, no network.
> Instantiate one in a REPL, hand it a stub, and print the client's own state after each
> lookup. Two questions will fall out of what you see: *what exactly identifies a stored
> answer*, and *who else can reach the thing that stores it*.

### Already correct — do not "fix" these

The failure behaviour is deliberate and specified in README §"Availability lookups": an
unreachable or erroring depot **fails closed** and reports `0` free minutes, so the ticket
falls through to `needs_scheduling`. Three green tests guard this. Keep them green.

| Scenario | Expected |
|---|---|
| `(AAA-01, certified)` = 240, then `(AAA-01, general)` = 30 | second lookup returns `30` |
| client A caches `(BBB-01, certified)`; fresh client B looks it up | B returns **its own** depot's answer |
| same pair looked up twice on one client | second call served from cache, no second HTTP call |
| depot unreachable / answers `503` | `0` free minutes |
| triage while the depot is down | `needs_scheduling`, `technician_id` empty |

**Relevant tests:** `tests/test_availability_client.py` — `test_skill_is_part_of_the_cache_key`,
`test_each_client_keeps_its_own_cache` (failing); `test_repeated_lookup_is_served_from_cache`,
`test_unreachable_depot_reports_no_capacity`, `test_error_response_reports_no_capacity`,
`test_ticket_is_queued_when_the_depot_is_down` (green — keep them that way).

---

## Part 3 — The wire protocol is only half-implemented (≈25 min)

**Layer:** `src/dispatch_agent/rpc/` and `src/dispatch_agent/api.py`

The parent orchestrator speaks strict JSON-RPC 2.0. Single calls work fine today. Two other
shapes of traffic, both described in README §"JSON-RPC contract", do not.

### Symptom A — fire-and-forget still gets an answer

The orchestrator sends low-priority tickets as **notifications**: a request object with
**no `id` member at all**. Per the spec, the server does the work and replies with
*nothing*.

```
  ──→  {"jsonrpc":"2.0","method":"dispatch.triage","params":{…}}      ← no "id"

  EXPECTED                          OBSERVED
  ────────────────────              ─────────────────────────────────────────
  HTTP 204                          HTTP 200
  (empty body)                      {"jsonrpc":"2.0","id":null,"result":{…}}
                                                        ▲
                                                        └── an id that was
                                                            never sent
```

Note the distinction the spec draws: a **missing** `id` member is a notification;
an `id` that is *present and null* is an ordinary request. The work itself must still
happen either way.

### Symptom B — a batch takes the whole endpoint down

The orchestrator also groups calls into a **batch**: a JSON array of request objects,
answered with an array of responses in the same order, with notifications left out.

```
  ──→  [ {id:"b-3", method:"dispatch.policy"},
         {        method:"agent.describe"},     ← notification
         {id:"b-4", method:"dispatch.nope"} ]

  EXPECTED                                   OBSERVED
  ─────────────────────────────────────      ────────────────────────
  HTTP 200                                   HTTP 500
  [ {id:"b-3", result:{…}},                  (unhandled exception,
    {id:"b-4", error:{code:-32601}} ]         no JSON-RPC envelope
                                              at all)
  └─ two entries: the notification
     contributes nothing
```

Three batch shapes have to behave:

| Body | Expected |
|---|---|
| array of 2 ordinary calls | HTTP 200, array of 2 responses, ids in request order |
| array mixing calls and notifications | HTTP 200, array with **only** the non-notification responses |
| array where every member is a notification | HTTP 204, empty body |
| `[]` (empty array) | HTTP 200, a **single** error object, `code = -32600` |

> Hint: start at `POST /rpc` in `api.py` and follow the body. It is handed to the
> dispatcher assuming exactly one shape. Ask what the endpoint does before it knows what it
> is holding, and what a handler's return value should be when the caller asked for no
> reply. FastAPI will happily return an empty `204` if you give it the right object.

### Do not change the happy path

`test_triage_over_rpc`, `test_policy_method`, `test_agent_describe`, the two
envelope-shape tests, and the three `-32600` malformed-request tests are green today and
must stay green.

**Relevant tests:** `tests/test_rpc.py` — `test_notification_gets_no_response_body`,
`test_batch_returns_one_response_per_call`, `test_batch_omits_notifications`,
`test_batch_of_only_notifications_gets_no_response_body`, `test_empty_batch_is_invalid_request`.

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

- A green `uv run pytest -q` (44 passed).
- `FINDINGS.md`.
- Clean, reviewable commits.
