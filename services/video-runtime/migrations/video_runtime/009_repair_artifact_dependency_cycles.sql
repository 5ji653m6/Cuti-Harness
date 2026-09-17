-- Repair invalid dependency rows created by the former replacement-alias logic.
-- Immutable build provenance must never contain self edges or point backwards
-- from a newer build output to an older dependency target.
DELETE FROM cuti_video_runtime.artifact_edges edge
USING cuti_video_runtime.artifact_versions source,
      cuti_video_runtime.artifact_versions target
WHERE source.id = edge.source_version_id
  AND target.id = edge.target_version_id
  AND (
    edge.source_version_id = edge.target_version_id
    OR (
      edge.relation = 'build_step_dependency'
      AND source.created_at > target.created_at
    )
  );

ALTER TABLE cuti_video_runtime.artifact_edges
  DROP CONSTRAINT IF EXISTS artifact_edges_no_self_dependency;

ALTER TABLE cuti_video_runtime.artifact_edges
  ADD CONSTRAINT artifact_edges_no_self_dependency
  CHECK (source_version_id <> target_version_id);
