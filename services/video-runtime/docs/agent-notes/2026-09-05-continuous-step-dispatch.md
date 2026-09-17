# Agent Note: Continuous task dispatch

Status: implemented

## Problem

Waiting for a complete parallel batch delays creative decisions behind unrelated Provider latency. Iterating a captured plan also prevents a newly committed cancellation or addition from changing admission.

## Decision

The continuous Build scheduler owns running tasks, waits for the first terminal task or committed patch, and reads durable plan/Step state before admitting more work. A single outstanding checkpoint coalesces terminal updates without losing them across restarts. DeepSeek remains the only planner. Live edits open a checkpoint via POST and use the same revision-checked resolution path. Step admission is a repository compare-and-set competing with pending cancellation.

## Alternatives considered

**Keep the batch barrier:** rejected because a slow sibling prevents both failure repair and use of already available artifacts.

**Invoke an LLM inside Runtime callbacks:** rejected because it creates another creative loop and splits Session history. Callbacks persist facts; the existing coordinator queues the bound DeepSeek Session.

**Cancel captured coroutine objects for pending tasks:** rejected because they may already have submitted paid work. Only persisted pending Steps may be cancelled; running work retains its operation id.

## Consequences

Failed-task repair is an append-only PlanPatch: replacement tasks receive fresh operation identities and pending descendants are cloned, not mutated. The previous dependency graph remains auditable through cancelled Steps and superseded failed plan items. Inspecting a failed Build does not enqueue old parameters; only a valid repair transaction resumes it. Automatic rewriting of started descendants is rejected because external operations may already be billable. Mock tests cover changed parameters, downstream completion, duplicate patches, cycles, cancellation, and exclusion of superseded tasks from later retries.

One Runtime process owns execution; this is not a distributed-worker lease implementation. Cancellation, disposal, and restart preserve remote-job reconciliation. Terminal failures do not switch the active ProjectVersion. Concurrent updates during an outstanding planning turn are delivered as a subsequent snapshot, not parallel creative revisions. Provider-mock concurrency/restart tests, API-level live-edit tests, and a Loader-composed HTTP tool snapshot cover the changed path. Live Provider and real Postgres verification remain separate environment-dependent acceptance checks.
