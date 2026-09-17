# Checkpoint tool feedback

The checkpoint inspection tool rendered only a phase summary while its next consumer required exact plan and specification revisions. A real task submitted zero for both revisions. The HTTP adapter then stringified the structured validation array as object placeholders, hiding the field errors from the Agent.

Inspection renders the returned checkpoint JSON and explicit revision-field mapping. HTTP errors include status and JSON validation details. The Loader-based composition test asserts the model-visible checkpoint snapshot and a structured 422 result through the real tool pipeline. No revision check is removed and no DeepSeek core code changes.
