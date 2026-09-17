"""
Image-generation tool wrapper - unified entry point.

The chain is selected in get_image_generation_tools(user_option), passed via create_image_wrapper_tools(mode, user_option)
and bound to the tool instance; at runtime it no longer depends on context.image_generation_tool to select the chain.

The chain returns List[ToolInfo]:
  each chain entry contains a complete ToolInfo (tool object, tool_type, provider, etc.),
  see the get_xxx_tools() pattern in each tool module.

I2I flow:
  truncate reference images -> run generation -> retry once on the same model for retryable errors -> fall back to the next model.

T2I flow:
  run generation -> retry once on the same model for retryable errors -> fall back to the next model.

Metrics:
  per-wrapper-call stats (attempt count, per-model counts, success rate, consistency distribution, etc.)
  are written to LangSmith run metadata via ImageToolMetrics.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Annotated, Any, Dict, TYPE_CHECKING

from pydantic import BaseModel, Field, SkipValidation
from pydantic.json_schema import SkipJsonSchema
from app.tools.runtime import tool
from app.tools.runtime import ToolRuntime

from app.models.image_result import ImageGenerationResult
from app.models.tool_enums import ToolType, ToolMode, DefaultValues, ToolName
from app.tools.context_schemas import ImageGenerationContext
from app.services.agent.video.agent_video_constants import (
    IMAGE_WRAPPER_MAX_TOTAL_GENERATION_ATTEMPTS,
)

if TYPE_CHECKING:
    from app.services.tool_service import ToolInfo

logger = logging.getLogger(__name__)

# ==================== Dependency imports ====================

from app.models.user_options import ImageGenerationTool, DEFAULT_IMAGE_TOOL

from app.utils.i18n import get_i18n_message_async
from app.utils.error_classification import (
    classify_failure,
    user_facing_reason_async,
    FailureCategory,
)
from app.tools.image.ref_utils import truncate_reference_urls_for_model
from app.tools.image.seedream import (
    edit_image_with_wavespeed_seedream,
    generate_image_with_wavespeed_seedream_t2i,
)
from app.tools.image.gpt_image_2 import (
    edit_image_with_wavespeed_gpt_image_2,
    generate_image_with_wavespeed_gpt_image_2_t2i,
)
from app.tools.image.nano_banana import (
    generate_image_with_nano_banana_i2i,
    generate_image_with_nano_banana_t2i,
)


# ==================== Metrics（LangSmith metadata） ====================


@dataclass
class ImageToolMetrics:
    """Wrapper execution stats, written to LangSmith run metadata; can also to_dict into result for the persisted version."""

    total_attempts: int = 0
    per_model_attempts: Dict[str, int] = field(default_factory=dict)
    success: bool = False
    final_model: Optional[str] = None
    failure_reasons: List[str] = field(default_factory=list)
    best_effort_selected: bool = False

    def record_attempt(
        self,
        model: str,
        success: bool,
        failure_reason: Optional[str] = None,
    ):
        self.total_attempts += 1
        self.per_model_attempts[model] = self.per_model_attempts.get(model, 0) + 1
        if failure_reason:
            self.failure_reasons.append(f"{model}:{failure_reason}")
        if success:
            self.success = True
            self.final_model = model

    def to_metadata(self) -> dict:
        return {
            "image_wrapper_metrics": {
                "total_attempts": self.total_attempts,
                "per_model_attempts": dict(self.per_model_attempts),
                "success": self.success,
                "final_model": self.final_model,
                "failure_reasons": list(self.failure_reasons),
                "best_effort_selected": self.best_effort_selected,
            }
        }

    def to_dict(self) -> Dict[str, Any]:
        """For result.image_tool_metrics persisted-version use."""
        return {
            "total_attempts": self.total_attempts,
            "per_model_attempts": dict(self.per_model_attempts),
            "success": self.success,
            "final_model": self.final_model,
            "failure_reasons": list(self.failure_reasons),
            "best_effort_selected": self.best_effort_selected,
        }

    def flush_to_langsmith(self):
        """Write metrics into the current LangSmith run's metadata and patch to the API (works sync/async)."""
        try:
            from langsmith import get_current_run_tree

            run = get_current_run_tree()
            if run:
                run.add_metadata(self.to_metadata())
                run.patch()
        except Exception:
            pass


# ==================== Candidate records ====================


@dataclass
class _AttemptRecord:
    """Single-attempt record, for best-effort selection."""

    model: str
    attempt_num: int  # 1=first, 2=retry
    result: ImageGenerationResult
    failure_type: Optional[str] = None

    @property
    def has_image(self) -> bool:
        return bool(self.result.image_url)

# ==================== Tool helper functions ====================


def _is_retryable_error(result: ImageGenerationResult) -> bool:
    """Decide whether a transient API-level error is retryable (rate limit, timeout, etc.).

    Rate-limit or transient failures returned by the provider are allowed to retry.
    """
    if result.success:
        return False
    error_msg = (result.raw_error_msg or result.error_msg or "").lower()
    retryable_keywords = [
        "504",
        "deadline_exceeded",
        "rate limit",
        "too many requests",
        "quota",
        "capacity",
        "temporarily unavailable",
        "service unavailable",
        "timeout",
        "暂时不可用",
        "使用量",
        "限流",
    ]
    return any(kw in error_msg for kw in retryable_keywords)


def _pick_best_candidate(candidates: List[_AttemptRecord]) -> Optional[_AttemptRecord]:
    """Return the latest candidate that contains a generated image."""
    if not candidates:
        return None
    with_image = [c for c in candidates if c.has_image]
    if not with_image:
        return candidates[-1]  # all API attempts failed, return the last one
    return with_image[-1]


async def _maybe_add_switch_info(
    result: ImageGenerationResult,
    actual_tool_type: ToolType,
    requested_model: ToolType,
    lang: Optional[str] = None,
) -> ImageGenerationResult:
    """If a model downgrade/switch happened, add the switch info; text is localized by runtime.context.language."""
    if actual_tool_type != requested_model:
        msg = await get_i18n_message_async(
            "image_model_switched.fallback_default",
            default="The requested model was temporarily unavailable; another model was used to complete generation.",
            lang=lang,
        )
        data = result.model_dump()
        data.update(
            model_switched=True,
            requested_model=requested_model.value,
            actual_model=actual_tool_type.value,
            user_facing_message=msg,
        )
        return ImageGenerationResult(**data)
    return result


def _inject_metrics(
    result: ImageGenerationResult,
    metrics: ImageToolMetrics,
    duration_sec: float,
    accumulated_tool_cost: float,
) -> ImageGenerationResult:
    """Write metrics, elapsed time, and cost into result for the persisted version. accumulated_tool_cost is the cumulative cost across fallback attempts, consistent with the credits charged."""
    data = result.model_dump()
    metric_data = metrics.to_dict()
    if result.applied_skill_ids or result.constraint_coverage or result.final_prompt:
        metric_data["skill_constraint_audit"] = {
            "applied_skill_ids": result.applied_skill_ids,
            "constraint_coverage": result.constraint_coverage,
            "final_prompt": result.final_prompt,
        }
    data["image_tool_metrics"] = metric_data
    data["tool_duration_sec"] = round(duration_sec, 3)
    data["tool_cost"] = accumulated_tool_cost or None
    out = ImageGenerationResult(**data)
    logger.info(
        "[image_wrapper] _inject_metrics 写入: tool_duration_sec=%s, tool_cost=%s",
        out.tool_duration_sec,
        out.tool_cost,
    )
    return out


# ==================== Chain configuration ====================


def _get_i2i_chain(tool: Optional[ImageGenerationTool]) -> List["ToolInfo"]:
    """Return the I2I attempt order by user selection.

    Rule: a fallback must be a superset of the main model's capabilities (e.g. Flash lacks 1080p, so it cannot be a fallback for Flash2/Pro/Seedream).
    Returns List[ToolInfo], each entry containing complete tool info (tool object, tool_type, provider).
    """
    from app.services.tool_service import ToolInfo
    from app.models.tool_enums import ToolProvider, ToolCategory

    def _i2i(tool_fn, tt: ToolType, prov: ToolProvider) -> ToolInfo:
        # set tool.metadata so the callback can precisely obtain ToolType / Provider
        if hasattr(tool_fn, "metadata"):
            if tool_fn.metadata is None:
                tool_fn.metadata = {}
            tool_fn.metadata.update(
                tool_type=tt.value,
                provider=prov.value,
                category=ToolCategory.IMAGE_GENERATION.value,
            )
        return ToolInfo(
            tool=tool_fn,
            tool_name=tool_fn.name,
            tool_type=tt,
            provider=prov,
            category=ToolCategory.IMAGE_GENERATION,
            mode=ToolMode.I2I,
        )

    seedream = _i2i(edit_image_with_wavespeed_seedream, ToolType.SEEDREAM_V4_5, ToolProvider.WAVESPEED)
    gpt2     = _i2i(edit_image_with_wavespeed_gpt_image_2, ToolType.GPT_IMAGE_2, ToolProvider.WAVESPEED)
    flash    = _i2i(generate_image_with_nano_banana_i2i, ToolType.GEMINI_2_5_FLASH_IMAGE, ToolProvider.GOOGLE)
    flash2   = _i2i(generate_image_with_nano_banana_i2i, ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW, ToolProvider.GOOGLE)
    pro      = _i2i(generate_image_with_nano_banana_i2i, ToolType.GEMINI_3_PRO_IMAGE_PREVIEW, ToolProvider.GOOGLE)

    if tool == ImageGenerationTool.NANO_BANANA:
        return [flash, flash2, seedream]
    elif tool == ImageGenerationTool.NANO_BANANA_2:
        # user picked Banana 2: banana 2 -> pro -> seedream (flash lacks 1080p, cannot be a fallback)
        return [flash2, pro, seedream]
    elif tool == ImageGenerationTool.SEEDREAM:
        return [seedream, flash2, pro]   # prefer 2 over pro on fallback
    elif tool == ImageGenerationTool.GPT_IMAGE_2:
        return [gpt2, flash2, pro, seedream]
    elif tool == ImageGenerationTool.NANO_BANANA_PRO:
        # user picked Pro: pro -> banana 2 -> seedream (flash lacks 1080p, cannot be a fallback)
        return [pro, flash2, seedream]
    else:
        # None / unknown: prefer banana 2 -> pro -> flash -> seedream
        return [flash2, pro, seedream]


def _get_t2i_chain(tool: Optional[ImageGenerationTool]) -> List["ToolInfo"]:
    """Return the T2I attempt order by user selection.

    Rule: a fallback must be a superset of the main model's capabilities (Flash lacks 1080p, so it cannot be a fallback for Flash2/Pro/Seedream).
    Returns List[ToolInfo], each entry containing complete tool info (tool object, tool_type, provider).
    """
    from app.services.tool_service import ToolInfo
    from app.models.tool_enums import ToolProvider, ToolCategory

    def _t2i(tool_fn, tt: ToolType, prov: ToolProvider) -> ToolInfo:
        # set tool.metadata so the callback can precisely obtain ToolType / Provider
        if hasattr(tool_fn, "metadata"):
            if tool_fn.metadata is None:
                tool_fn.metadata = {}
            tool_fn.metadata.update(
                tool_type=tt.value,
                provider=prov.value,
                category=ToolCategory.IMAGE_GENERATION.value,
            )
        return ToolInfo(
            tool=tool_fn,
            tool_name=tool_fn.name,
            tool_type=tt,
            provider=prov,
            category=ToolCategory.IMAGE_GENERATION,
            mode=ToolMode.T2I,
        )

    seedream = _t2i(generate_image_with_wavespeed_seedream_t2i, ToolType.SEEDREAM_V4_5, ToolProvider.WAVESPEED)
    gpt2     = _t2i(generate_image_with_wavespeed_gpt_image_2_t2i, ToolType.GPT_IMAGE_2, ToolProvider.WAVESPEED)
    flash    = _t2i(generate_image_with_nano_banana_t2i, ToolType.GEMINI_2_5_FLASH_IMAGE, ToolProvider.GOOGLE)
    flash2   = _t2i(generate_image_with_nano_banana_t2i, ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW, ToolProvider.GOOGLE)
    pro      = _t2i(generate_image_with_nano_banana_t2i, ToolType.GEMINI_3_PRO_IMAGE_PREVIEW, ToolProvider.GOOGLE)

    if tool == ImageGenerationTool.NANO_BANANA:
        return [flash, flash2, seedream]
    elif tool == ImageGenerationTool.NANO_BANANA_2:
        # flash lacks 1080p, cannot be a fallback for Flash2
        return [flash2, pro, seedream]
    elif tool == ImageGenerationTool.SEEDREAM:
        return [seedream, flash2, pro]   # flash lacks 1080p, cannot be a fallback
    elif tool == ImageGenerationTool.GPT_IMAGE_2:
        return [gpt2, flash2, pro, seedream]
    elif tool == ImageGenerationTool.NANO_BANANA_PRO:
        return [pro, flash2, seedream]   # flash lacks 1080p, cannot be a fallback
    else:
        return [flash2, pro, seedream]   # default Banana 2; flash cannot be a fallback


# ==================== I2I core logic ====================


async def _invoke_i2i_tool(
    prompt: str,
    tool_info: "ToolInfo",
    urls: List[str],
    runtime: ToolRuntime[ImageGenerationContext],
) -> ImageGenerationResult:
    """Call the underlying I2I tool, pure execution without consistency checking.

    Seedream / GPT Image 2 and Nano Banana use different reference-image parameter names:
      - SEEDREAM_V4_5, GPT_IMAGE_2: images
      - GEMINI_*: reference_image_urls
    """
    from app.orchestration.skills.constraint_contract import (
        active_constraint_contract,
        merge_and_validate_prompt,
    )

    audit = merge_and_validate_prompt(prompt, active_constraint_contract())
    if tool_info.tool_type in (ToolType.SEEDREAM_V4_5, ToolType.GPT_IMAGE_2):
        result = await tool_info.tool.ainvoke(
            {"prompt": audit.final_prompt, "images": urls, "runtime": runtime}
        )
    else:
        result = await tool_info.tool.ainvoke(
            {"prompt": audit.final_prompt, "reference_image_urls": urls, "runtime": runtime}
        )
    result.applied_skill_ids = audit.applied_skill_ids
    result.constraint_coverage = audit.constraint_coverage
    result.final_prompt = audit.final_prompt
    result.generated_prompt = audit.final_prompt
    return result


async def _run_i2i_attempt(
    prompt: str,
    tool_info: "ToolInfo",
    urls: List[str],
    runtime: ToolRuntime[ImageGenerationContext],
) -> ImageGenerationResult:
    """Run one I2I provider attempt."""
    return await _invoke_i2i_tool(prompt, tool_info, urls, runtime)


async def _run_i2i_loop(
    prompt: str,
    reference_image_urls: List[str],
    runtime: ToolRuntime[ImageGenerationContext],
    chain: List["ToolInfo"],
) -> ImageGenerationResult:
    """I2I fallback chain with provider retries.

    Each model gets at most 2 attempts (first + retry), but the total number of image-to-image API calls within one wrapper call does not exceed
    IMAGE_WRAPPER_MAX_TOTAL_GENERATION_ATTEMPTS (same semantics as the video wrapper's total-attempt cap).
    When all fail, return the last candidate that still contains an image.
    """
    requested_model = runtime.context.model or DefaultValues.IMAGE_MODEL
    _lang = getattr(runtime.context, "language", None) if runtime and runtime.context else None
    if not runtime.context.reference_image_urls:
        runtime.context.reference_image_urls = reference_image_urls

    start_time = time.perf_counter()
    metrics = ImageToolMetrics()
    candidates: List[_AttemptRecord] = []
    accumulated_tool_cost = 0.0
    total_generation_attempts = 0

    for info in chain:
        # prepare reference images (truncate + write back to runtime)
        base_refs = runtime.context.reference_image_urls or []
        urls = truncate_reference_urls_for_model(base_refs, info.tool_type) or []
        runtime.context.reference_image_urls = urls
        runtime.context.model = info.tool_type

        for attempt_num in (1, 2):
            if total_generation_attempts >= IMAGE_WRAPPER_MAX_TOTAL_GENERATION_ATTEMPTS:
                logger.info(
                    "🛑 [I2I] 已达最大生成尝试次数 (%d)，停止",
                    IMAGE_WRAPPER_MAX_TOTAL_GENERATION_ATTEMPTS,
                )
                break
            total_generation_attempts += 1
            if attempt_num == 1:
                logger.info("🔄 [I2I] 尝试模型: %s", info.tool_type.value)
            else:
                logger.info("🔄 [I2I] 同模型重试: %s", info.tool_type.value)

            result = await _run_i2i_attempt(
                prompt, info, urls, runtime
            )
            accumulated_tool_cost += float(getattr(result, "billing_cost", None) or 0.0)

            # ---- API failure ----
            if not result.success:
                metrics.record_attempt(
                    info.tool_type.value, False, failure_reason="api_error"
                )
                candidates.append(
                    _AttemptRecord(
                        model=info.tool_type.value,
                        attempt_num=attempt_num,
                        result=result,
                        failure_type="api_error",
                    )
                )
                if _is_retryable_error(result) and attempt_num == 1:
                    continue  # retryable -> try again
                break  # not retryable / already retried -> switch model

            metrics.record_attempt(info.tool_type.value, True)
            metrics.flush_to_langsmith()
            out = _inject_metrics(
                result, metrics, time.perf_counter() - start_time,
                accumulated_tool_cost,
            )
            return await _maybe_add_switch_info(
                out, info.tool_type, requested_model, lang=_lang,
            )

        if total_generation_attempts >= IMAGE_WRAPPER_MAX_TOTAL_GENERATION_ATTEMPTS:
            break

    # ---- all models failed to pass -> best-effort selection ----
    best = _pick_best_candidate(candidates)
    if best and best.has_image:
        metrics.best_effort_selected = True
        metrics.success = True
        metrics.final_model = best.model
        metrics.flush_to_langsmith()
        logger.warning("⚠️ [I2I] provider fallback selected candidate model=%s", best.model)
        data = best.result.model_dump()
        data.update(
            requested_model=requested_model.value,
            user_facing_message=await get_i18n_message_async(
                "image_model_switched.best_effort",
                default="The last usable provider result was selected.",
                lang=_lang,
            ),
        )
        result = ImageGenerationResult(**data)
        result = _inject_metrics(result, metrics, time.perf_counter() - start_time, accumulated_tool_cost)
        logger.info("[image_wrapper] I2I 返回(best_effort): tool_duration_sec=%s, tool_cost=%s", result.tool_duration_sec, result.tool_cost)
        try:
            actual = ToolType(best.model)
        except ValueError:
            actual = requested_model
        return await _maybe_add_switch_info(result, actual, requested_model, lang=_lang)

    # ---- truly all API failures, no usable image ----
    metrics.flush_to_langsmith()
    logger.error("❌ [I2I] 所有模型均失败，无可用候选")
    last_result = (
        candidates[-1].result
        if candidates
        else ImageGenerationResult(success=False, error_msg="所有模型均失败")
    )
    data = last_result.model_dump()
    _category = classify_failure(last_result.raw_error_msg or last_result.error_msg)
    if _category in (FailureCategory.SERVICE_UNAVAILABLE, FailureCategory.UNKNOWN):
        all_unavailable_msg = await get_i18n_message_async(
            "image_model_switched.all_unavailable",
            default="All image generation models are temporarily unavailable. Please try again later.",
            lang=_lang,
        )
    else:
        all_unavailable_msg = await user_facing_reason_async(category=_category, lang=_lang)
    data.update(
        requested_model=requested_model.value,
        user_facing_message=all_unavailable_msg,
        failure_category=_category.value,
    )
    result = ImageGenerationResult(**data)
    return _inject_metrics(result, metrics, time.perf_counter() - start_time, accumulated_tool_cost)


# ==================== T2I core logic ====================


async def _run_t2i_one(
    prompt: str,
    tool_info: "ToolInfo",
    runtime: ToolRuntime[ImageGenerationContext],
) -> ImageGenerationResult:
    """Run a single-model T2I once.

    All T2I tools share the same parameters (prompt / runtime), called directly via tool_info.tool.
    """
    from app.orchestration.skills.constraint_contract import (
        active_constraint_contract,
        merge_and_validate_prompt,
    )

    audit = merge_and_validate_prompt(prompt, active_constraint_contract())
    runtime.context.model = tool_info.tool_type
    result = await tool_info.tool.ainvoke(
        {"prompt": audit.final_prompt, "runtime": runtime}
    )
    result.applied_skill_ids = audit.applied_skill_ids
    result.constraint_coverage = audit.constraint_coverage
    result.final_prompt = audit.final_prompt
    result.generated_prompt = audit.final_prompt
    return result


async def _run_t2i_loop(
    prompt: str,
    runtime: ToolRuntime[ImageGenerationContext],
    chain: List["ToolInfo"],
) -> ImageGenerationResult:
    """T2I fallback chain - no consistency check, only API-level retry + fallback; see IMAGE_WRAPPER_MAX_TOTAL_GENERATION_ATTEMPTS for the total text-to-image cap."""
    requested_model = runtime.context.model or DefaultValues.IMAGE_MODEL
    _lang = getattr(runtime.context, "language", None) if runtime and runtime.context else None
    start_time = time.perf_counter()
    metrics = ImageToolMetrics()
    last_error_result: Optional[ImageGenerationResult] = None
    accumulated_tool_cost = 0.0
    total_generation_attempts = 0

    for info in chain:
        for attempt_num in (1, 2):
            if total_generation_attempts >= IMAGE_WRAPPER_MAX_TOTAL_GENERATION_ATTEMPTS:
                logger.info(
                    "🛑 [T2I] 已达最大生成尝试次数 (%d)，停止",
                    IMAGE_WRAPPER_MAX_TOTAL_GENERATION_ATTEMPTS,
                )
                break
            total_generation_attempts += 1
            if attempt_num == 1:
                logger.info("🔄 [T2I] 尝试模型: %s", info.tool_type.value)
            else:
                logger.info("🔄 [T2I] 重试: %s", info.tool_type.value)

            result = await _run_t2i_one(prompt, info, runtime)
            accumulated_tool_cost += float(getattr(result, "billing_cost", None) or 0.0)
            if result.success:
                metrics.record_attempt(info.tool_type.value, True)
                metrics.flush_to_langsmith()
                logger.info("✅ [T2I] 成功: %s", info.tool_type.value)
                out = _inject_metrics(result, metrics, time.perf_counter() - start_time, accumulated_tool_cost)
                logger.info("[image_wrapper] T2I 返回(成功): tool_duration_sec=%s, tool_cost=%s", out.tool_duration_sec, out.tool_cost)
                return await _maybe_add_switch_info(out, info.tool_type, requested_model, lang=_lang)

            metrics.record_attempt(
                info.tool_type.value, False, failure_reason="api_error"
            )
            last_error_result = result

            if _is_retryable_error(result) and attempt_num == 1:
                continue  # retryable -> try again
            break  # not retryable / already retried -> switch model

        if total_generation_attempts >= IMAGE_WRAPPER_MAX_TOTAL_GENERATION_ATTEMPTS:
            break

    metrics.flush_to_langsmith()
    logger.error("❌ [T2I] 所有模型均失败")
    last = last_error_result or ImageGenerationResult(success=False, error_msg="所有模型均失败")
    data = last.model_dump()
    _category = classify_failure(last.raw_error_msg or last.error_msg)
    if _category in (FailureCategory.SERVICE_UNAVAILABLE, FailureCategory.UNKNOWN):
        t2i_unavailable_msg = await get_i18n_message_async(
            "image_model_switched.all_unavailable",
            default="All image generation models are temporarily unavailable. Please try again later.",
            lang=_lang,
        )
    else:
        t2i_unavailable_msg = await user_facing_reason_async(category=_category, lang=_lang)
    data.update(
        requested_model=requested_model.value,
        user_facing_message=t2i_unavailable_msg,
        failure_category=_category.value,
    )
    result = ImageGenerationResult(**data)
    return _inject_metrics(result, metrics, time.perf_counter() - start_time, accumulated_tool_cost)


# ==================== Wrapper Tool (T2I) ====================


class ImageWrapperT2IInput(BaseModel):
    """Input schema for image generation wrapper T2I."""

    prompt: str = Field(
        description="Detailed image description prompt. Describe the image content, style, composition, character appearance, scene environment, artistic style, etc. Be specific and detailed for better results."
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)",
    )


def _make_t2i_tool(chain_t2i: List["ToolInfo"]):
    """Create the T2I tool from the selected chain."""
    assert chain_t2i, "chain_t2i must be non-empty"

    @tool(ToolName.IMAGE_WRAPPER_T2I, args_schema=ImageWrapperT2IInput, response_format="content_and_artifact")
    async def generate_image_with_fallback_t2i(
        prompt: str,
        runtime: ToolRuntime[ImageGenerationContext],
    ) -> tuple[str, ImageGenerationResult]:
        """Professional image generation tool with automatic fallback - T2I text-to-image.
        Chain (Pro/Flash/Seedream) is chosen at tool creation from user_option; retries once per model on retryable errors.
        """
        result = await _run_t2i_loop(prompt, runtime, chain_t2i)
        return (result.model_dump_json(), result)

    return generate_image_with_fallback_t2i


# ==================== Wrapper Tool (I2I) ====================


class ImageWrapperI2IInput(BaseModel):
    """Input schema for image generation wrapper I2I."""

    prompt: str = Field(
        description="Image generation prompt based on reference images.",
    )
    reference_image_urls: List[str] = Field(
        description="List of reference image URLs for image editing or style reference.",
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)",
    )


def _make_i2i_tool(chain_i2i: List["ToolInfo"]):
    """Create the I2I tool from the selected chain."""
    assert chain_i2i, "chain_i2i must be non-empty"

    @tool(ToolName.IMAGE_WRAPPER_I2I, args_schema=ImageWrapperI2IInput, response_format="content_and_artifact")
    async def generate_image_with_fallback_i2i(
        prompt: str,
        reference_image_urls: List[str],
        runtime: ToolRuntime[ImageGenerationContext],
    ) -> tuple[str, ImageGenerationResult]:
        """Professional image generation tool with automatic fallback - I2I image-to-image.
        Chain is chosen at tool creation from user_option; each step truncates references, executes the provider, and retries transient failures once.
        When all models fail, the last usable provider candidate is returned.
        """
        result = await _run_i2i_loop(prompt, reference_image_urls, runtime, chain_i2i)
        return (result.model_dump_json(), result)

    return generate_image_with_fallback_i2i


# ==================== Tool creation functions ====================


def create_image_wrapper_tools(
    mode: Optional[ToolMode] = None,
    user_option: Optional[Any] = None,
) -> List["ToolInfo"]:
    """Create the image-generation tool wrapper with fallback.

    The chain (Pro/Flash/Seedream attempt order) is selected here based on user_option and bound to the tool instance,
    passed in when get_image_generation_tools(user_option, mode) is called.

    The chain returns List[ToolInfo]; provider/tool_type, etc. come directly from chain[0], no longer hardcoded.

    Args:
        mode: tool mode, ToolMode.T2I or ToolMode.I2I; None returns both T2I + I2I tools
        user_option: user option, used to decide the attempt chain; uses the default chain (nano_banana_2) when None

    Returns:
        List[ToolInfo]: list of wrapper tool info
    """
    from app.models.tool_enums import ToolCategory
    from app.services.tool_service import ToolInfo

    image_tool = user_option.image_generation_tool if user_option else None
    if image_tool == ImageGenerationTool.AUTO:
        image_tool = DEFAULT_IMAGE_TOOL
    chain_t2i = _get_t2i_chain(image_tool)
    chain_i2i = _get_i2i_chain(image_tool)

    tools: List[ToolInfo] = []

    if mode != ToolMode.I2I:
        t2i_tool = _make_t2i_tool(chain_t2i)
        primary_t2i = chain_t2i[0]
        t2i_tool_info = ToolInfo(
            tool=t2i_tool,
            tool_name=t2i_tool.name,
            tool_type=primary_t2i.tool_type,
            provider=primary_t2i.provider,
            category=ToolCategory.IMAGE_GENERATION,
            mode=ToolMode.T2I,
        )
        tools.append(t2i_tool_info)

    if mode != ToolMode.T2I:
        i2i_tool = _make_i2i_tool(chain_i2i)
        primary_i2i = chain_i2i[0]
        i2i_tool_info = ToolInfo(
            tool=i2i_tool,
            tool_name=i2i_tool.name,
            tool_type=primary_i2i.tool_type,
            provider=primary_i2i.provider,
            category=ToolCategory.IMAGE_GENERATION,
            mode=ToolMode.I2I,
        )
        tools.append(i2i_tool_info)

    # add metadata for the callback
    for info in tools:
        if hasattr(info.tool, "metadata"):
            if info.tool.metadata is None:
                info.tool.metadata = {}
            info.tool.metadata.update(
                tool_type=info.tool_type.value,
                provider=info.provider.value,
                category=ToolCategory.IMAGE_GENERATION.value,
            )

    return tools


# module-level default tools (for direct import or testing, using the default chain)
generate_image_with_fallback_t2i = _make_t2i_tool(_get_t2i_chain(None))
generate_image_with_fallback_i2i = _make_i2i_tool(_get_i2i_chain(None))
