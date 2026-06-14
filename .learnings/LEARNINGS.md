# Learnings

Corrections, insights, and knowledge gaps captured during development.

**Categories**: correction | insight | knowledge_gap | best_practice

---

## [2026-06-07] 纯文字模式与语音输出分离

- **Category**: best_practice
- **Summary**: `text_only_mode` 仅跳过对话 TTS 合成/播放；TTS 服务与 `build_time_greetings.py` 预生成不受影响，便于省 GPU 且保留预热能力。
- **Pattern-Key**: pet-tts-text-only-mode

## [2026-06-07] 快捷启动失败需用户可见反馈

- **Category**: insight
- **Summary**: `LaunchAppsService.register_fail_notifier` 回调到桌宠托盘 `showMessage` 与气泡，避免「说了打开但没反应」。
- **Pattern-Key**: launch-apps-fail-notify
