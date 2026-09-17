BEGIN;

ALTER TABLE cuti_video_runtime.build_steps
  ADD COLUMN IF NOT EXISTS resolved_skills jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS skill_context jsonb;

COMMIT;
