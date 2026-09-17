# Checkpoint turn recovery

Continuous task notifications retain one unresolved checkpoint per Build. Its persisted revision identifies the planning transaction, while delivery and inspection project current BuildStep results so late media completions are visible without replacing the transaction.

The coordinator observes consumed checkpoint messages and subsequent Session turn completion. Missing PlanPatch acknowledgement releases the delivery for bounded retry. An attempt compare-and-set prevents stale observers from releasing a newer delivery, and terminal Builds and resolved checkpoints remain unchanged. Reconciliation reconstructs its state from the repository and Session history after restart. A lease covers delivery without a recorded completed turn.

Regression coverage exercises late completion during a text-only planning turn, coordinator recreation, refreshed inputs, stale observers, and successful continuation without regenerating completed steps.
