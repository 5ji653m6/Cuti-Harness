BEGIN;

ALTER TABLE cuti_video_runtime.rebuild_plans
  ALTER COLUMN change_request_id DROP NOT NULL;
ALTER TABLE cuti_video_runtime.rebuild_plans
  ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'incremental',
  ADD COLUMN IF NOT EXISTS workflow_id text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS video_spec jsonb;

ALTER TABLE cuti_video_runtime.builds
  ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'incremental',
  ADD COLUMN IF NOT EXISTS estimated_cost numeric(16,6) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS actual_cost numeric(16,6) NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS cuti_video_runtime.build_steps (
  id text PRIMARY KEY,
  build_id text NOT NULL REFERENCES cuti_video_runtime.builds(id) ON DELETE CASCADE,
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id),
  plan_step_id text NOT NULL,
  action text NOT NULL CHECK (action IN ('create','rebuild','validate','reuse')),
  capability text NOT NULL DEFAULT '',
  status text NOT NULL CHECK (status IN (
    'pending','running','waiting_external','completed','failed','cancelled'
  )),
  attempt integer NOT NULL DEFAULT 0,
  remote_operation_id text,
  remote_provider text,
  result_artifact_version_id text REFERENCES cuti_video_runtime.artifact_versions(id),
  error text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(build_id, plan_step_id)
);

CREATE INDEX IF NOT EXISTS build_steps_recovery_idx
  ON cuti_video_runtime.build_steps(project_id, status, updated_at);

ALTER TABLE cuti_video_runtime.build_steps
  ADD COLUMN IF NOT EXISTS remote_provider text;

COMMIT;
