# Dynamic edit recipes

Agent Note: selected ArtifactVersion records and their producing plan retain executable parameters independently of whether a complete VideoSpec exists. Requiring a video_spec Artifact excludes valid continuous PlanPatch projects, including projects whose ProjectVersion already references a partial VideoSpecRevision.

Regeneration reconstructs saved recipes, applies explicit parameter patches, and follows selected dependency edges. Recorded input IDs and step references restore edges omitted by output-only version changes such as watermarking. This recovery does not infer creative prompts or fabricate missing capabilities. Structural edits that lack authored specification fields still require Agent planning; direct artifact regeneration does not.

Continuous checkpoint revisions save execution_tasks alongside the authored spec. Workspace reads use the committed spec revision rather than accidentally promoting a draft. Follow-up goals seed selected generated artifacts as reuse steps. Existing live checkpoint validation controls pending cancellation, replacement of failed tasks, revision conflicts, and session ownership. Completed tasks remain immutable; new goals and output replacements use new builds.

Verification includes spec-free regeneration with missing stored graph edges, preservation of untouched reference media and prompts, stale-version rejection, selected-artifact reuse by follow-up goals, and the continuous scheduler regression suite. Real-project replay uses an isolated repository and does not submit Provider work.
