BEGIN;

ALTER TABLE cuti_video_runtime.change_requests
  ADD COLUMN IF NOT EXISTS edits jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS proposed_video_spec jsonb;

COMMIT;
