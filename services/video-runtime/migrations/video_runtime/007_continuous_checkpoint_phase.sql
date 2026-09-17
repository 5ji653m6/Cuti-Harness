BEGIN;

-- Continuous PlanPatch reuses phase name task_frontier_completed after every
-- frontier. UNIQUE(build_id, phase) silently dropped the second wait, leaving
-- the build running at the last-step progress with no Agent wake-up.
DO $constraint$
DECLARE
  old_name text;
BEGIN
  SELECT conname INTO old_name
  FROM pg_constraint
  WHERE conrelid = 'cuti_video_runtime.plan_checkpoints'::regclass
    AND contype = 'u'
    AND pg_get_constraintdef(oid) = 'UNIQUE (build_id, phase)';
  IF old_name IS NOT NULL THEN
    EXECUTE format(
      'ALTER TABLE cuti_video_runtime.plan_checkpoints DROP CONSTRAINT %I',
      old_name
    );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'plan_checkpoints_build_id_phase_revision_key'
      AND conrelid = 'cuti_video_runtime.plan_checkpoints'::regclass
  ) THEN
    ALTER TABLE cuti_video_runtime.plan_checkpoints
      ADD CONSTRAINT plan_checkpoints_build_id_phase_revision_key
      UNIQUE (build_id, phase, base_plan_revision);
  END IF;
END
$constraint$;

COMMIT;
