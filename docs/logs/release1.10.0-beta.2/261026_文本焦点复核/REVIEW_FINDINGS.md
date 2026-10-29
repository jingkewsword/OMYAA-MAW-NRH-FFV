# 文本焦点修复独立复核

日期：2026-10-26。范围：[fork Draft PR 11](https://github.com/jingkewsword/OMYAA-MAW-NRH-FFV/pull/11)，原 head `0e052102`，基线 `350c3b02`。

## 结论与处置

独立审查未发现焦点实现的阻塞缺陷。`loadTimedTextEditTrack()` 同步完成行、视图和报告渲染；显示弹窗后立即聚焦有效。批量菜单关闭不恢复触发按钮焦点；自定义包裹入口先关闭右键菜单再打开弹窗，事件冒泡不会覆盖新焦点。整体视图光标定位、逐条视图选中字幕滚动以及 main 的报告复用、视图缓存和行查找优化保留。

| 问题 | 实际影响 | 处置 |
| --- | --- | --- |
| Windows Preview 契约仍要求显式 PR head ref | 基线已改用 merge ref，旧断言使打包契约失败并阻止后续验证 | 限定 checkout 步骤，要求默认 ref 与 workflow 一致，并在同一步骤验证不保存凭据；保留只读权限、lite 包、不含 FFmpeg 和不发布 Release 等保障 |
| 自定义包裹 Node mock 缺少 `contains` | 回退旧实现会先因 mock 不完整抛 TypeError，不能精确说明首次聚焦缺失 | 补齐 classList 状态和输入框包含关系，让旧实现由首次焦点断言失败 |

两项均已修正并经未参与实现的审查者复核。没有未处置的 blocker / major，也没有为假设性低概率问题增加产品逻辑。

## 定向验证

Windows、Node v24.22.1，所有测试从 `scripts/run_check.py` 运行：

- `node node_modules/playwright/cli.js test --config=tests/config/playwright.config.mjs --project=chromium --workers=1 tests/e2e/modal-initial-focus.spec.mjs tests/e2e/timed-text-edit.spec.mjs`：22/22，零 skip/retry。
- `node --test tests/test_inline_caret.mjs tests/test_timed_text_report.mjs`：14/14。
- `python scripts/run_tests.py tests/test_packaging_contract.py`：34/34。
- TypeScript、编辑器及 Launcher 构建、编辑器新鲜度、个人路径与 diff 检查通过。

回退三处焦点实现并重建后，六项相关 Chromium 用例全部在首次聚焦或输入归属断言处失败；自定义包裹 Node 用例因首次焦点为 null 失败。重新加入显式 PR head ref 时，新的打包契约也在禁止 ref 覆盖的断言处失败。随后恢复源码和 workflow 并重建产物。

新 head CI 结果见本 PR 验证说明。原始输出保留在本轮独立工作树的 `.artifacts/checks/`，未提交生成 bundle 或便携 HTML。

## 待人工确认

在实际桌面宿主分别以鼠标和键盘打开文本编辑弹窗，检查远处选中字幕定位、Tab / Shift+Tab 与搜索选区；切换整体和逐条视图后立即输入中文，确认输入法组合文本保留在目标输入框。自定义包裹弹窗检查左右输入框切换及输入法。此层仍待维护者验收。

现有远端 CI 未执行上述两个焦点 spec；其结果与本轮本地 Chromium 结果分别报告。内联副本待发布前统一重生成。
