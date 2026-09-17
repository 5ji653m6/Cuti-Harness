"""
Redis Stream service - handles message streams, task queues, and task status
"""
import logging
import time
from typing import Optional, List, Dict, Any, Tuple
import redis.asyncio as aioredis
from datetime import datetime

from ...utils.asyncpg_utils import utc_isoformat

logger = logging.getLogger(__name__)

from ...models.task_status import TaskStatus

# Milestone events persisted on Redis Stream for refresh recovery.
GENERATED_EVENTS = {
    "story_outline_generated",
    "storyboard_detail_generated",
    "keyframes_generated",
    "keyframes_reflection_completed",
    "narrations_generated",
    "audio_effects_generated",
    "video_segments_generated",
    "video_segments_assembled",
    "video_completed",
    "characters_designed",
    "music_generated",
    "scenes_generated",
    "video_lipsync_completed",
    "video_analysis",
    "workflow_state",
    "story_agent_generated",
    "music_agent_generated",
    "image_agent_generated",
    "video_agent_generated",
}

PROGRESS_EVENTS = {
    "keyframe_generation_progress",
    "keyframe_reflection_progress",
    "video_generation_progress",
    "video_segments_progress",
    "music_generation_progress",
    "video_lipsync_progress",
    "video_gen_progress",
}


class RedisStreamService:
    """Redis Stream service."""

    def __init__(self, redis_client: aioredis.Redis, environment: Optional[str] = None):
        self.redis = redis_client

        # get the environment prefix (from environment variable or parameter)
        if environment is None:
            from ...config import get_settings
            settings = get_settings()
            env = settings.ENVIRONMENT.value  # "local", "development", "production"
        else:
            env = environment

        # environment-prefix mapping (simplified key)
        env_prefix_map = {
            "local": "local",
            "development": "dev",
            "production": "prod"
        }
        env_prefix = env_prefix_map.get(env, "dev")

        # all keys get the environment prefix
        self.message_prefix = f"cuti-videoagent:{env_prefix}:message:"
        self.task_queue_key = f"cuti-videoagent:{env_prefix}:task:queue"
        self.task_status_prefix = f"cuti-videoagent:{env_prefix}:task:status:"
        self.task_index_prefix = f"cuti-videoagent:{env_prefix}:task:index:"
        self.cancel_channel_prefix = f"cuti-videoagent:{env_prefix}:cancel:"
        self.auto_resume_dismissed_prefix = f"cuti-videoagent:{env_prefix}:auto_resume_dismissed:"
        # single-flight lock: only one pipeline run (main/resume) may actually execute per thread at a time, to avoid concurrent duplicate generation
        self.pipeline_lock_prefix = f"cuti-videoagent:{env_prefix}:pipeline_lock:"

        logger.info(f"🔧 Redis Stream Service初始化: 环境={env} (前缀={env_prefix}), 队列key={self.task_queue_key}")

    @staticmethod
    def _decode_id(redis_id) -> str:
        """Decode a Redis ID (handles bytes and str)."""
        return redis_id.decode() if isinstance(redis_id, bytes) else redis_id

    async def add_message(self, run_id: str, event_data: dict) -> str:
        """Add a message to the stream.

        Serialize the whole event_data into a JSON string stored in one field, to simplify handling.
        """
        import json
        stream_key = f"{self.message_prefix}{run_id}"

        # mark whether it is a generated event
        event_type = event_data.get("type", "")
        event_data["is_generated"] = event_type in GENERATED_EVENTS

        # serialize the whole data into a JSON string (Redis Stream requires string values)
        payload = json.dumps(event_data, ensure_ascii=False, default=str)

        message_id = await self.redis.xadd(stream_key, {"data": payload})
        return self._decode_id(message_id)

    async def read_messages(
        self,
        run_id: str,
        from_id: str = "0",
        count: int = 100,
        block: Optional[int] = None
    ) -> List[Tuple[str, dict]]:
        """Read messages."""
        stream_key = f"{self.message_prefix}{run_id}"
        kwargs = {"count": count}
        if block is not None:
            kwargs["block"] = block

        messages = await self.redis.xread({stream_key: from_id}, **kwargs)

        if messages:
            import json
            stream, message_list = messages[0]
            result = []
            for msg_id, data in message_list:
                msg_id_str = self._decode_id(msg_id)

                # read data from Redis (str mode, used directly)
                payload_str = data.get("data")
                if payload_str is None:
                    continue

                # deserialize JSON
                try:
                    decoded_data = json.loads(payload_str)
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"解析消息JSON失败: {e}, payload: {payload_str[:100]}")
                    continue

                result.append((msg_id_str, decoded_data))
            return result

        return []

    async def get_all_messages(self, run_id: str) -> List[Tuple[str, dict]]:
        """Get all messages."""
        import json
        stream_key = f"{self.message_prefix}{run_id}"
        messages = await self.redis.xrange(stream_key, "-", "+")

        result = []
        for msg_id, data in messages:
            msg_id_str = self._decode_id(msg_id)

            # read data from Redis (str mode, used directly)
            payload_str = data.get("data")
            if payload_str is None:
                continue

            # deserialize JSON
            try:
                decoded_data = json.loads(payload_str)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"解析消息JSON失败: {e}, payload: {payload_str[:100]}")
                continue

            result.append((msg_id_str, decoded_data))

        return result

    async def check_stream_exists(self, run_id: str) -> bool:
        """Check whether the message stream exists."""
        stream_key = f"{self.message_prefix}{run_id}"
        exists = await self.redis.exists(stream_key)
        return bool(exists)

    async def get_stream_length(self, run_id: str) -> int:
        """Get the message-stream length."""
        stream_key = f"{self.message_prefix}{run_id}"
        length = await self.redis.xlen(stream_key)
        return length

    async def add_task_to_queue(self, task_data: dict) -> str:
        """Add a task to the queue.

        Serialize the whole task_data into a JSON string stored in one field, to simplify handling.
        """
        import json
        # serialize the whole data into a JSON string (Redis Stream requires string values)
        payload = json.dumps(task_data, ensure_ascii=False, default=str)

        message_id = await self.redis.xadd(self.task_queue_key, {"data": payload})
        return self._decode_id(message_id)

    async def consume_task(self, group_name: str, consumer_name: str) -> Optional[dict]:
        """Consume a task."""
        messages = await self.redis.xreadgroup(
            group_name,
            consumer_name,
            {self.task_queue_key: ">"},
            count=1,
            block=1000
        )

        if messages:
            import json
            stream, message_list = messages[0]
            message_id, data = message_list[0]

            msg_id_str = self._decode_id(message_id)

            # read data from Redis (str mode, used directly)
            payload_str = data.get("data")
            if payload_str is None:
                return None

            # deserialize JSON
            try:
                decoded_data = json.loads(payload_str)
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"解析任务JSON失败: {e}, payload: {payload_str[:100]}")
                return None

            return {"message_id": msg_id_str, "data": decoded_data}

        return None

    async def ack_task(self, group_name: str, message_id: str):
        """Acknowledge task completion."""
        await self.redis.xack(self.task_queue_key, group_name, message_id)

    async def update_task_status(
        self,
        run_id: str,
        status: str,
        last_generated_event: Optional[str] = None,
        last_generated_id: Optional[str] = None,
        **kwargs
    ):
        """Update task status."""
        status_key = f"{self.task_status_prefix}{run_id}"
        data = {
            "run_id": run_id,  # keep run_id for querying
            "status": status,
            "updated_at": utc_isoformat(datetime.utcnow()),
            **kwargs
        }
        if last_generated_event:
            data["last_generated_event"] = last_generated_event
        if last_generated_id:
            data["last_generated_id"] = last_generated_id

        # a Hash can store string values, format directly
        formatted_data = {}
        for k, v in data.items():
            if v is None:
                formatted_data[k] = ""
            elif isinstance(v, bool):
                formatted_data[k] = "1" if v else "0"
            else:
                formatted_data[k] = str(v)

        await self.redis.hset(status_key, mapping=formatted_data)
        # set the expiration (5 minutes, cache-aside best practice: short TTL + DB write-back)
        await self.redis.expire(status_key, 300)

    async def get_task_status(self, run_id: str) -> Optional[dict]:
        """Get task status from Redis only."""
        status_key = f"{self.task_status_prefix}{run_id}"
        data = await self.redis.hgetall(status_key)

        if data:
            # str mode, used directly (compatible with bytes mode)
            result = {}
            for k, v in data.items():
                key = k.decode() if isinstance(k, bytes) else k
                value = v.decode() if isinstance(v, bytes) else v
                result[key] = value
            return result

        return None

    async def get_user_running_tasks(self, user_id: str) -> List[dict]:
        """Get all running tasks for a user."""
        tasks = []
        pattern = f"{self.task_status_prefix}*"

        async for key in self.redis.scan_iter(match=pattern):
            key_str = self._decode_id(key)
            run_id = key_str.replace(self.task_status_prefix, "")

            status = await self.get_task_status(run_id)
            if status and status.get('status') in [TaskStatus.RUNNING.value, TaskStatus.QUEUED.value, TaskStatus.RESUME_QUEUED.value]:
                # check whether user_id matches (from the task status)
                task_user_id = status.get('user_id')
                if task_user_id == user_id:
                    status['run_id'] = run_id
                    tasks.append(status)

        return tasks

    async def get_running_tasks_by_thread_id(self, thread_id: str) -> List[dict]:
        """Get all running tasks for this thread_id."""
        # get all run_ids from the task index
        index_key = f"{self.task_index_prefix}{thread_id}"
        run_ids = await self.redis.zrevrange(index_key, 0, -1)

        tasks = []
        for run_id in run_ids:
            run_id_str = self._decode_id(run_id)
            status = await self.get_task_status(run_id_str)
            if status and status.get('status') in [TaskStatus.RUNNING.value, TaskStatus.QUEUED.value, TaskStatus.RESUME_QUEUED.value]:
                status['run_id'] = run_id_str
                status['thread_id'] = thread_id
                tasks.append(status)

        return tasks

    async def add_task_index(self, thread_id: str, run_id: str):
        """Add a task index."""
        index_key = f"{self.task_index_prefix}{thread_id}"
        await self.redis.zadd(index_key, {run_id: time.time()})
        # set the expiration (6 hours)
        await self.redis.expire(index_key, 21600)

    async def get_task_index(self, thread_id: str) -> List[str]:
        """Get the task index (in reverse chronological order)."""
        index_key = f"{self.task_index_prefix}{thread_id}"
        run_ids = await self.redis.zrevrange(index_key, 0, -1)
        return [self._decode_id(run_id) for run_id in run_ids]

    async def publish_cancel(self, run_id: str):
        """Publish a cancellation message to the Pub/Sub channel (for cross-machine/cross-process notification)."""
        import json
        channel = f"{self.cancel_channel_prefix}{run_id}"
        message = json.dumps({"run_id": run_id, "timestamp": time.time()})
        subscribers = await self.redis.publish(channel, message)
        logger.info(f"📢 发布取消消息: run_id={run_id}, channel={channel}, 订阅者数={subscribers}")
        return subscribers

    def get_pubsub(self):
        """Get the Pub/Sub object (for subscribing)."""
        return self.redis.pubsub()

    # ===== Pipeline single-flight lock (per-thread) =====
    # only one run per thread may actually run the video pipeline at a time, to avoid multiple resume/main running the same checkpoint concurrently
    # and duplicating outline/storyboard/keyframe/video generation. The lock has a TTL; the holder renews periodically during execution; after a process crash the TTL expires and auto-releases.
    def _pipeline_lock_key(self, thread_id: str) -> str:
        return f"{self.pipeline_lock_prefix}{thread_id}"

    async def acquire_pipeline_lock(self, thread_id: str, run_id: str, ttl_seconds: int = 180) -> bool:
        """Try to acquire the pipeline lock for this thread; returns True on success (owner=run_id), False if already held by someone else."""
        if not thread_id or not run_id:
            return True
        key = self._pipeline_lock_key(thread_id)
        ok = await self.redis.set(key, run_id, nx=True, ex=ttl_seconds)
        return bool(ok)

    async def refresh_pipeline_lock(self, thread_id: str, run_id: str, ttl_seconds: int = 180) -> bool:
        """Renew only while the lock still belongs to this run, to avoid renewing someone else's lock."""
        if not thread_id or not run_id:
            return False
        key = self._pipeline_lock_key(thread_id)
        lua = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
        )
        res = await self.redis.eval(lua, 1, key, run_id, ttl_seconds)
        return bool(res)

    async def release_pipeline_lock(self, thread_id: str, run_id: str) -> bool:
        """Release only while the lock still belongs to this run, to avoid deleting someone else's lock."""
        if not thread_id or not run_id:
            return False
        key = self._pipeline_lock_key(thread_id)
        lua = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end"
        )
        res = await self.redis.eval(lua, 1, key, run_id)
        return bool(res)

    async def get_pipeline_lock_owner(self, thread_id: str) -> Optional[str]:
        """Return the run_id currently holding the lock (None if none), for log diagnostics."""
        if not thread_id:
            return None
        v = await self.redis.get(self._pipeline_lock_key(thread_id))
        if v is None:
            return None
        return v.decode() if isinstance(v, bytes) else v

    def _auto_resume_dismissed_key(self, interrupted_run_id: str, interrupt_msgid: str) -> str:
        return f"{self.auto_resume_dismissed_prefix}{interrupted_run_id}:{interrupt_msgid}"

    async def set_auto_resume_dismissed(
        self, interrupted_run_id: str, interrupt_msgid: str, ttl_seconds: int = 120
    ) -> None:
        """Written when the user cancels "this interrupt's 15s auto-continue"; the worker checks it before handling auto_resume."""
        key = self._auto_resume_dismissed_key(interrupted_run_id, interrupt_msgid)
        await self.redis.set(key, "1", ex=ttl_seconds)

    async def is_auto_resume_dismissed(self, interrupted_run_id: str, interrupt_msgid: str) -> bool:
        key = self._auto_resume_dismissed_key(interrupted_run_id, interrupt_msgid)
        v = await self.redis.get(key)
        return bool(v and (v.decode() if isinstance(v, bytes) else v) == "1")
