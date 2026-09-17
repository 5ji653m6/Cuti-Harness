BEGIN;

CREATE TABLE IF NOT EXISTS cuti_video_runtime.project_skill_locks (
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id) ON DELETE CASCADE,
  skill_id text NOT NULL,
  version text NOT NULL,
  digest text NOT NULL,
  source text NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, skill_id)
);

COMMIT;
