# @cuti-ai/tool-video

Checkpoint inspection renders the checkpoint JSON, including both revision counters, artifact summaries and planning instructions. Submit `base_plan_revision` as `base_revision` and retain `base_spec_revision`; these values must not be guessed from a phase label.

English | [中文](README.zh.md)

Stable, high-level tools that let a DeepSeek agent operate a versioned video project without exposing provider-specific calls.

Project creation and planning require a five-field video language contract. The Agent keeps UI locale, user-visible authored content, speech, subtitles, and provider prompt language independent and preserves those fields in every plan patch.

`video_checkpoint_inspect` accepts `checkpoint_id="live"` to open a planning snapshot for a user edit during execution. Use the returned id and revisions with `video_plan_patch_submit`. Task completion/failure notifications and live edits share the same append/cancel path; only pending tasks can be cancelled, and unrelated running tasks continue. See the [Runtime scheduling rules](../../../services/video-runtime/README.md).

For corrected-parameter retries, submit `replace_failed_task_ids` mapping failed IDs to new `add_tasks` client keys. The Runtime replaces pending descendants atomically; completed outputs remain reusable. A failed continuous Build can be inspected with `checkpoint_id="live"` and stays stopped until the repair patch commits.

An explicit edit request authorizes preview and apply without another confirmation. Build results distinguish queued work from completion and direct the Agent to finish dependent steps. Workflow-free PlanPatch capabilities include installed video generation and media operations; a generated clip can feed concatenation in the same plan.

## Model Experience

### Project video tools

#### What the model sees

The [23 `video_*` tools](../../../docs/tool-catalog.md#cuti-aitool-video) expose project creation, Cuti-compatible continuous `PlanPatch` planning, project inspection, structured edit and dependency impact previews, rebuild execution, durable build control, artifact selection, and export. `video_edit_preview` returns cost and affected steps but never executes paid work. Provider credentials, internal tasks, plugin hooks, and raw media operations are absent from the schemas.

#### Token effect

Fixed schema cost while the tool plugin is enabled; results are data-dependent and bounded summaries.

#### KV Cache effect

Prefix-stable while the enabled tool set is unchanged.

## Known Limitations and Deferred Work

- Project ids are explicit tool arguments in the first release; automatic active-project injection into tool arguments remains deferred.
