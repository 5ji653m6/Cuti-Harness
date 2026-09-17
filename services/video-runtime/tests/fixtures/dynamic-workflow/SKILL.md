---
name: independent-story-workflow
description: Create a three-part story document without paid media generation.
metadata:
  kind: workflow
  workflow:
    mode: agentic
    planning:
      mode: agentic
      checkpoints:
        - id: story_ready
          after_phase: creative_intent
          next_phase: story_document
    parameters:
      completion_artifact_types: [script]
    pipeline: [atomic.text.generate]
    allowed_capabilities: [atomic.text.generate]
    requires_keyframe: false
    entrypoints: [text]
---

# Independent story workflow

Read the user's goal and submit a PlanPatch containing an atomic.text.generate task with a script output. Write an opening, turning point, and ending. Wait for the persisted artifact before completing the goal. For edits, append a revision task referencing the completed document. Do not generate video or invoke a different Workflow.
