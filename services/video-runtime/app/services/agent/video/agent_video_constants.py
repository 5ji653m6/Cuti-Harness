"""
Video Agent pipeline switch constants
"""
# Image wrapper: the cap on actual text-to-image/image-to-image API calls within a single tool call (including same-model retries and cross-model fallback).
IMAGE_WRAPPER_MAX_TOTAL_GENERATION_ATTEMPTS = 3

# Video wrapper: the cap on actual video-generation API calls within a single tool call (same semantics as the image wrapper).
VIDEO_WRAPPER_MAX_TOTAL_GENERATION_ATTEMPTS = 2

# whether normal video uses reference-to-video (T2V + reference_images) instead of the I2V first-frame hard constraint.
# Seedance2 forces reference-to-video when should_skip_keyframe_pipeline is true.
USE_REFERENCE_TO_VIDEO = False
