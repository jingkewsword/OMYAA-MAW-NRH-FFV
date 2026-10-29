---
task: v2-cleanup-diagnostics
pr: 10
date: 2026-10-30
status: pending
---

# v2 清理投影缓存诊断核验

> 基线 ce0fdc3b；开关默认开启，仅用于当前页面，不写入工程。

## 实现与验证
<!-- id: implementation -->

播放及公共多轨导出共用投影缓存；关闭只绕过缓存，切换会清空结果。

相关自动化与已知基线失败见同目录 REVIEW_FINDINGS.md；自动化不替代真实长媒体验收。

## 人工验收
<!-- id: manual -->

- [ ] **开关前后结果一致**
  （操作）打开 v2 带局部 AI 清理范围的工程，播放、Seek 并导出主副字幕；在开发者控制台分别执行 MaweExportSrt.setCleanupProjectionCacheEnabled(false) 和 MaweExportSrt.setCleanupProjectionCacheEnabled(true)，重复相同操作。
  （预期）清理文字、预览和导出内容一致，关闭优化不关闭功能。
  <!-- id: equivalence -->

- [ ] **历史与保存不受诊断开关影响**
  （操作）在两种开关状态下编辑、撤销、重做，另存后重新打开，再切换另一个工程；记录长媒体卡顿及内存表现。
  （预期）没有旧结果残留，保存内容一致；重载页面恢复默认开启。性能变化按同一工程、同一操作比较。
  <!-- id: lifecycle -->
