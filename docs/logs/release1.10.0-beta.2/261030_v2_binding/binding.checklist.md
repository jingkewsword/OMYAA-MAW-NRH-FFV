---
task: v2-binding-diagnostics
pr: 9
date: 2026-10-30
status: pending
---

# v2 绑定索引诊断核验

> 基线 ce0fdc3b；开关默认开启，仅用于当前页面，不写入工程。

## 实现与验证
<!-- id: implementation -->

绑定同步使用按轨局部索引，关闭后按同一 CueRef 逐条查找。

相关自动化与已知基线失败见同目录 REVIEW_FINDINGS.md；自动化不替代真实长媒体验收。

## 人工验收
<!-- id: manual -->

- [ ] **开关前后结果一致**
  （操作）打开 v2 双语大工程，调整绑定字幕时间；在开发者控制台分别执行 AsrEditorUtils.setBindingIndexEnabled(false) 和 AsrEditorUtils.setBindingIndexEnabled(true)，重复相同操作。
  （预期）绑定偏移、主副轨字幕和分组保持一致，关闭优化不关闭功能。
  <!-- id: equivalence -->

- [ ] **历史与保存不受诊断开关影响**
  （操作）在两种开关状态下编辑、撤销、重做，另存后重新打开，再切换另一个工程；记录长媒体卡顿及内存表现。
  （预期）没有旧结果残留，保存内容一致；重载页面恢复默认开启。性能变化按同一工程、同一操作比较。
  <!-- id: lifecycle -->
