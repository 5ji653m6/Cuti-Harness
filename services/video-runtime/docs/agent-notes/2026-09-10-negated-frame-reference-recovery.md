# Negated frame references and Agent recovery

The provider bridge recognizes affirmative prompt frame assignments while excluding negated assignments. A prompt such as `而非首帧：@图片1` keeps its images as ordinary identity references; interpreting the substring as an explicit opening frame creates an unsupported mixed-input request before Provider submission.

Unsupported mixed-input errors describe how the Agent can restore an ordinary-reference request when that matches the original intent. Explicit strict-frame requirements remain intact. Checkpoint instructions require corrected replacement tasks for recoverable parameter errors and preserve completed outputs, model selection and reference requirements. Unchanged invalid submissions and empty acknowledgments do not repair failed work.

Regression coverage includes the incident wording, Chinese and English negation, affirmative frame assignments, and continuous scheduling recovery. Live recovery reuses the existing successful segment and continues the same project and Session.

The Video Agent bundle explicitly enables the upstream conversation compactor, manual compact command and tool-result pruner. The Web profile disables these services at host level; video sessions need them for repeated Skill loads and task snapshots. This restores bounded context-overflow recovery through existing Harness plugins without changing the Agent loop.
