BEGIN;

-- Conversation list: one user's recent projects without a sequential scan.
CREATE INDEX IF NOT EXISTS projects_user_updated_idx
  ON cuti_video_runtime.projects (user_id, updated_at DESC);

-- Latest DeepSeek Session binding per project/user.
CREATE INDEX IF NOT EXISTS project_session_bindings_latest_idx
  ON cuti_video_runtime.project_session_bindings (project_id, user_id, created_at DESC);

-- Workspace / sidebar: latest build and per-build collections.
CREATE INDEX IF NOT EXISTS builds_project_created_idx
  ON cuti_video_runtime.builds (project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS artifact_versions_project_created_idx
  ON cuti_video_runtime.artifact_versions (project_id, created_at, version);

CREATE INDEX IF NOT EXISTS project_versions_project_created_idx
  ON cuti_video_runtime.project_versions (project_id, created_at);

CREATE INDEX IF NOT EXISTS build_steps_build_created_idx
  ON cuti_video_runtime.build_steps (project_id, build_id, created_at, id);

CREATE INDEX IF NOT EXISTS validation_results_build_idx
  ON cuti_video_runtime.validation_results (project_id, build_id, created_at);

CREATE INDEX IF NOT EXISTS plan_checkpoints_build_idx
  ON cuti_video_runtime.plan_checkpoints (project_id, build_id, created_at);

CREATE INDEX IF NOT EXISTS artifact_edges_project_idx
  ON cuti_video_runtime.artifact_edges (project_id, created_at);

COMMIT;
