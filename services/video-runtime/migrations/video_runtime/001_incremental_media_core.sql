BEGIN;

CREATE SCHEMA IF NOT EXISTS cuti_video_runtime;

CREATE TABLE IF NOT EXISTS cuti_video_runtime.projects (
  id text PRIMARY KEY,
  user_id text NOT NULL,
  title text NOT NULL,
  status text NOT NULL DEFAULT 'active',
  current_version_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.project_session_bindings (
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id),
  session_id text NOT NULL,
  user_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, session_id)
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.project_creation_idempotency (
  user_id text NOT NULL,
  idempotency_key text NOT NULL,
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.project_versions (
  id text PRIMARY KEY,
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id),
  parent_version_id text REFERENCES cuti_video_runtime.project_versions(id),
  timeline_version_id text,
  change_request_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.project_version_artifacts (
  project_version_id text NOT NULL REFERENCES cuti_video_runtime.project_versions(id),
  artifact_id text NOT NULL,
  artifact_version_id text NOT NULL,
  PRIMARY KEY (project_version_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.artifact_versions (
  id text PRIMARY KEY,
  artifact_id text NOT NULL,
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id),
  artifact_type text NOT NULL,
  version integer NOT NULL,
  status text NOT NULL,
  uri text,
  title text NOT NULL DEFAULT '',
  summary text NOT NULL DEFAULT '',
  content_digest text NOT NULL DEFAULT '',
  generation_spec_digest text NOT NULL DEFAULT '',
  provider_id text,
  provider_version text,
  plugin_id text,
  plugin_version text,
  provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (artifact_id, version)
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.artifact_edges (
  id text PRIMARY KEY,
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id),
  source_version_id text NOT NULL REFERENCES cuti_video_runtime.artifact_versions(id),
  target_version_id text NOT NULL REFERENCES cuti_video_runtime.artifact_versions(id),
  relation text NOT NULL DEFAULT 'derived_from',
  invalidation_policy text NOT NULL CHECK (invalidation_policy IN ('hard', 'validate', 'soft', 'none')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.change_requests (
  id text PRIMARY KEY,
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id),
  base_project_version_id text NOT NULL REFERENCES cuti_video_runtime.project_versions(id),
  description text NOT NULL,
  targets jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.rebuild_plans (
  id text PRIMARY KEY,
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id),
  change_request_id text NOT NULL REFERENCES cuti_video_runtime.change_requests(id),
  base_project_version_id text NOT NULL REFERENCES cuti_video_runtime.project_versions(id),
  items jsonb NOT NULL,
  estimated_cost numeric(16,6) NOT NULL DEFAULT 0,
  status text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.builds (
  id text PRIMARY KEY,
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id),
  plan_id text REFERENCES cuti_video_runtime.rebuild_plans(id),
  base_project_version_id text NOT NULL REFERENCES cuti_video_runtime.project_versions(id),
  idempotency_key text NOT NULL,
  session_id text,
  user_id text,
  status text NOT NULL,
  progress double precision NOT NULL DEFAULT 0,
  message text NOT NULL DEFAULT '',
  project_version_id text REFERENCES cuti_video_runtime.project_versions(id),
  error text,
  remote_operation_id text,
  remote_submission_state text NOT NULL DEFAULT 'not_submitted',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.validation_results (
  id text PRIMARY KEY,
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id),
  build_id text NOT NULL REFERENCES cuti_video_runtime.builds(id),
  artifact_version_id text,
  validator_id text NOT NULL,
  passed boolean NOT NULL,
  score double precision,
  issues jsonb NOT NULL DEFAULT '[]'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.project_events (
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id),
  sequence bigint NOT NULL,
  event_type text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, sequence)
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.exports (
  id text PRIMARY KEY,
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id),
  project_version_id text NOT NULL REFERENCES cuti_video_runtime.project_versions(id),
  idempotency_key text NOT NULL,
  format text NOT NULL,
  status text NOT NULL,
  uri text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.operation_idempotency (
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id),
  operation text NOT NULL,
  idempotency_key text NOT NULL,
  result_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, operation, idempotency_key)
);

CREATE TABLE IF NOT EXISTS cuti_video_runtime.compatibility_runs (
  user_id text NOT NULL,
  idempotency_key text NOT NULL,
  project_id text NOT NULL REFERENCES cuti_video_runtime.projects(id),
  session_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, idempotency_key)
);

-- Idempotent compatibility backfill. Dynamic SQL keeps a fresh installation valid when
-- the legacy schema was never installed.
DO $backfill$
BEGIN
  IF to_regclass('cuti_videochat_v2.agent_runs') IS NULL THEN
    RETURN;
  END IF;

  EXECUTE $sql$
    INSERT INTO cuti_video_runtime.projects
      (id, user_id, title, status, created_at, updated_at)
    SELECT DISTINCT ON (project_id)
      project_id, user_id, COALESCE(payload->>'title', payload->>'objective', 'Imported project'),
      'active', COALESCE(NULLIF(payload->>'created_at', '')::timestamptz, updated_at), updated_at
    FROM cuti_videochat_v2.agent_runs
    ORDER BY project_id, updated_at DESC
    ON CONFLICT (id) DO NOTHING
  $sql$;

  EXECUTE $sql$
    INSERT INTO cuti_video_runtime.project_versions (id, project_id, created_at)
    SELECT 'legacy-project-version-' || md5(id), id, created_at
    FROM cuti_video_runtime.projects
    ON CONFLICT (id) DO NOTHING
  $sql$;

  EXECUTE $sql$
    UPDATE cuti_video_runtime.projects
    SET current_version_id = 'legacy-project-version-' || md5(id)
    WHERE current_version_id IS NULL
  $sql$;

  EXECUTE $sql$
    INSERT INTO cuti_video_runtime.project_session_bindings
      (project_id, session_id, user_id, created_at)
    SELECT project_id, thread_id, user_id, COALESCE(NULLIF(payload->>'created_at', '')::timestamptz, updated_at)
    FROM cuti_videochat_v2.agent_runs
    ON CONFLICT (project_id, session_id) DO NOTHING
  $sql$;

  EXECUTE $sql$
    INSERT INTO cuti_video_runtime.artifact_versions
      (id, artifact_id, project_id, artifact_type, version, status, uri, title, summary,
       content_digest, generation_spec_digest, provider_id, provider_version,
       plugin_id, plugin_version, provenance, metadata, created_at)
    SELECT id, artifact_id, project_id, artifact_type, version,
      COALESCE(payload->>'status', 'ready'), payload->>'uri',
      COALESCE(payload->>'title', ''), COALESCE(payload->>'summary', ''),
      COALESCE(payload->>'content_digest', ''),
      COALESCE(payload->>'generation_spec_digest', ''),
      payload->>'provider_id', payload->>'provider_version',
      payload->>'plugin_id', payload->>'plugin_version',
      COALESCE(payload->'provenance', '{}'::jsonb),
      COALESCE(payload->'metadata', '{}'::jsonb), created_at
    FROM cuti_videochat_v2.artifact_versions
    ON CONFLICT (id) DO NOTHING
  $sql$;

  EXECUTE $sql$
    INSERT INTO cuti_video_runtime.artifact_edges
      (id, project_id, source_version_id, target_version_id, relation,
       invalidation_policy, created_at)
    SELECT id, project_id, payload->>'source_version_id', payload->>'target_version_id',
      COALESCE(payload->>'relation', 'derived_from'),
      CASE WHEN payload->>'invalidation_policy' IN ('hard','validate','soft','none')
        THEN payload->>'invalidation_policy' ELSE 'hard' END,
      COALESCE(NULLIF(payload->>'created_at', '')::timestamptz, now())
    FROM cuti_videochat_v2.artifact_edges
    ON CONFLICT (id) DO NOTHING
  $sql$;

  -- The old key was (project_id, artifact_type). Joining the selected version recovers
  -- artifact_id, so independent shots with the same type receive independent keys.
  EXECUTE $sql$
    INSERT INTO cuti_video_runtime.project_version_artifacts
      (project_version_id, artifact_id, artifact_version_id)
    SELECT 'legacy-project-version-' || md5(selection.project_id), artifact.artifact_id,
      selection.artifact_version_id
    FROM cuti_videochat_v2.artifact_selections selection
    JOIN cuti_videochat_v2.artifact_versions artifact
      ON artifact.id = selection.artifact_version_id
    ON CONFLICT (project_version_id, artifact_id)
      DO UPDATE SET artifact_version_id = EXCLUDED.artifact_version_id
  $sql$;

  EXECUTE $sql$
    INSERT INTO cuti_video_runtime.builds
      (id, project_id, base_project_version_id, idempotency_key, status, progress,
       session_id, user_id, message, project_version_id, error, created_at, updated_at)
    SELECT 'legacy-build-' || id, project_id, 'legacy-project-version-' || md5(project_id),
      'legacy-run-' || id,
      CASE status WHEN 'completed' THEN 'completed' WHEN 'failed' THEN 'failed'
        WHEN 'cancelled' THEN 'cancelled' WHEN 'waiting_external' THEN 'waiting_external'
        ELSE 'queued' END,
      CASE WHEN status = 'completed' THEN 1 ELSE 0 END,
      thread_id, user_id,
      'Imported from legacy AgentRun',
      CASE WHEN status = 'completed' THEN 'legacy-project-version-' || md5(project_id) END,
      CASE WHEN status = 'failed' THEN COALESCE(payload->>'last_response', 'Legacy run failed') END,
      COALESCE(NULLIF(payload->>'created_at', '')::timestamptz, updated_at), updated_at
    FROM cuti_videochat_v2.agent_runs
    ON CONFLICT (id) DO NOTHING
  $sql$;

  EXECUTE $sql$
    INSERT INTO cuti_video_runtime.compatibility_runs
      (user_id, idempotency_key, project_id, session_id, created_at)
    SELECT user_id, idempotency_key, project_id, thread_id,
      COALESCE(NULLIF(payload->>'created_at', '')::timestamptz, updated_at)
    FROM cuti_videochat_v2.agent_runs
    ON CONFLICT (user_id, idempotency_key) DO NOTHING
  $sql$;
END
$backfill$;

COMMIT;
