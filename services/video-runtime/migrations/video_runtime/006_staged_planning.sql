BEGIN;

ALTER TABLE cuti_video_runtime.rebuild_plans
  ADD COLUMN IF NOT EXISTS schema_version integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS current_revision integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS project_intent jsonb,
  ADD COLUMN IF NOT EXISTS video_spec_revision_id text,
  ADD COLUMN IF NOT EXISTS current_phase text NOT NULL DEFAULT 'full',
  ADD COLUMN IF NOT EXISTS next_checkpoint jsonb;

ALTER TABLE cuti_video_runtime.project_versions
  ADD COLUMN IF NOT EXISTS video_spec_revision_id text;

CREATE TABLE IF NOT EXISTS cuti_video_runtime.video_spec_revisions (
  id text PRIMARY KEY,
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id) ON DELETE CASCADE,
  revision integer NOT NULL,
  parent_revision_id text REFERENCES cuti_video_runtime.video_spec_revisions(id),
  content jsonb NOT NULL DEFAULT '{}'::jsonb,
  resolved_sections jsonb NOT NULL DEFAULT '[]'::jsonb,
  unresolved_sections jsonb NOT NULL DEFAULT '[]'::jsonb,
  source_artifact_version_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  checkpoint_id text,
  created_by text NOT NULL CHECK (created_by IN ('user','agent','migration')),
  complete boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, revision)
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.build_plan_revisions (
  id text PRIMARY KEY,
  plan_id text NOT NULL REFERENCES cuti_video_runtime.rebuild_plans(id) ON DELETE CASCADE,
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id) ON DELETE CASCADE,
  revision integer NOT NULL,
  base_revision integer NOT NULL,
  checkpoint_id text,
  video_spec_revision_id text REFERENCES cuti_video_runtime.video_spec_revisions(id),
  added_step_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  cancelled_step_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  reason text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(plan_id, revision)
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.plan_checkpoints (
  id text PRIMARY KEY,
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id) ON DELETE CASCADE,
  build_id text NOT NULL REFERENCES cuti_video_runtime.builds(id) ON DELETE CASCADE,
  plan_id text NOT NULL REFERENCES cuti_video_runtime.rebuild_plans(id) ON DELETE CASCADE,
  workflow_id text NOT NULL,
  session_id text NOT NULL,
  user_id text NOT NULL,
  phase text NOT NULL,
  next_phase text NOT NULL,
  status text NOT NULL CHECK (status IN ('pending','planning','resolved','failed')),
  required_artifact_types jsonb NOT NULL DEFAULT '[]'::jsonb,
  artifact_version_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  artifact_summaries jsonb NOT NULL DEFAULT '[]'::jsonb,
  resolved_sections jsonb NOT NULL DEFAULT '[]'::jsonb,
  unresolved_sections jsonb NOT NULL DEFAULT '[]'::jsonb,
  planner_instruction text NOT NULL DEFAULT '',
  planning_mode text NOT NULL CHECK (planning_mode IN ('staged','agentic')),
  base_plan_revision integer NOT NULL,
  base_spec_revision integer NOT NULL,
  delivery_attempts integer NOT NULL DEFAULT 0,
  max_delivery_attempts integer NOT NULL DEFAULT 3,
  semantic_repair_attempts integer NOT NULL DEFAULT 0,
  delivery_id text,
  lease_expires_at timestamptz,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(build_id, phase)
);

CREATE UNIQUE INDEX IF NOT EXISTS plan_checkpoint_delivery_id_idx
  ON cuti_video_runtime.plan_checkpoints(delivery_id)
  WHERE delivery_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS plan_checkpoint_dispatch_idx
  ON cuti_video_runtime.plan_checkpoints(status, lease_expires_at, created_at);

DO $constraint$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'rebuild_plans_video_spec_revision_fk'
      AND conrelid = 'cuti_video_runtime.rebuild_plans'::regclass
  ) THEN
    ALTER TABLE cuti_video_runtime.rebuild_plans
      ADD CONSTRAINT rebuild_plans_video_spec_revision_fk
      FOREIGN KEY (video_spec_revision_id)
      REFERENCES cuti_video_runtime.video_spec_revisions(id)
      NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'project_versions_video_spec_revision_fk'
      AND conrelid = 'cuti_video_runtime.project_versions'::regclass
  ) THEN
    ALTER TABLE cuti_video_runtime.project_versions
      ADD CONSTRAINT project_versions_video_spec_revision_fk
      FOREIGN KEY (video_spec_revision_id)
      REFERENCES cuti_video_runtime.video_spec_revisions(id)
      NOT VALID;
  END IF;
END
$constraint$;

-- Existing complete plans become immutable revision 1 records. In-flight v1 builds
-- keep their original execution semantics and never gain semantic checkpoints.
WITH ranked_plans AS (
  SELECT plan.*, row_number() OVER (
    PARTITION BY project_id ORDER BY created_at, id
  ) AS spec_revision
  FROM cuti_video_runtime.rebuild_plans plan
  WHERE video_spec IS NOT NULL
)
INSERT INTO cuti_video_runtime.video_spec_revisions
  (id,project_id,revision,content,resolved_sections,unresolved_sections,
   source_artifact_version_ids,created_by,complete,created_at)
SELECT 'migrated-spec-' || id, project_id, spec_revision, video_spec,
  '["title","characters","shots","audio","timeline"]'::jsonb,
  '[]'::jsonb, '[]'::jsonb, 'migration', true, created_at
FROM ranked_plans
ON CONFLICT (project_id, revision) DO NOTHING;

UPDATE cuti_video_runtime.rebuild_plans plan
SET video_spec_revision_id = revision.id
FROM cuti_video_runtime.video_spec_revisions revision
WHERE revision.id = 'migrated-spec-' || plan.id
  AND plan.video_spec_revision_id IS NULL;

INSERT INTO cuti_video_runtime.build_plan_revisions
  (id,plan_id,project_id,revision,base_revision,video_spec_revision_id,
   added_step_ids,reason,created_at)
SELECT 'migrated-plan-revision-' || plan.id, plan.id, plan.project_id, 1, 0,
  plan.video_spec_revision_id,
  COALESCE((SELECT jsonb_agg(item->>'step_id') FROM jsonb_array_elements(plan.items) item), '[]'::jsonb),
  'Migrated complete v1 plan', plan.created_at
FROM cuti_video_runtime.rebuild_plans plan
ON CONFLICT (plan_id, revision) DO NOTHING;

COMMIT;
