# 2.0 测试门禁

本页说明 PR 作者会遇到的检查。实际执行范围以该次 Actions 的选择计划、任务和测试报告为准。

| 改动 | 完整测试矩阵 | 现有检查 |
| --- | --- | --- |
| 普通用户文档或网站源码 | 轻量路径；不运行跨平台测试 | 文档、网站检查仍运行；Windows 预览按自身规则判断是否打包 |
| 经逐个审核的单一领域路径 | Windows 与 Ubuntu 各运行对应 Chromium 测试 | 编辑器与 Windows 预览保留各自检查 |
| 应用、共享配置、未知或混合路径；非 PR 事件 | Windows 与 Ubuntu 各运行 Python、Node 和四片 Chromium，共 12 个执行单元 | 原编辑器、调试工具和 Windows 预览继续运行 |

选择器见 `scripts/ci_impact.py`。只有登记过且消费者已审核的路径可缩小范围；差异无法确认时进入完整矩阵。2.0dev 的 push 也运行完整矩阵。发布工作流不使用 PR 选测。

完整矩阵见 `.github/workflows/test-matrix.yml`。每个 Python 单元运行全量发现，并单独用 `--pack media --required` 验证真实媒体能力。浏览器单元保存发现清单和实际结果；汇总检查提交、选中范围、所有分片和允许的精确跳过。测试未执行、报告缺失、额外跳过或失败均不能显示为通过。2.0 的统一轨道、旧工程迁移另存和数据安全浏览器用例仍由现有编辑器检查执行，也属于完整浏览器发现范围。

包含网站入口退役测试的浏览器分片先同步文档和发布数据，再构建真实网站；该测试读取构建后的 `website/dist`。其他分片不重复准备网站。

这套矩阵目前是**增加覆盖**。原编辑器和 Windows 预览中的固定检查仍保留；待在相同提交、平台和运行配置下逐项证明覆盖等效后，才会移除重复执行。不能把工作流绿色当作所有测试都运行；要同时看选择计划、执行任务、分片报告和结果。Windows 安装包以预览工作流实际构建、上传和启动证据为准。

本地可先运行相关组；`--required` 会拒绝依赖缺失导致的跳过：

```text
uv run --no-sync python scripts/run_tests.py --pack media --required --report .artifacts/media.json
pnpm run test:unit
pnpm exec playwright test --config=tests/config/playwright.config.mjs --project=chromium tests/e2e/unified-tracks.spec.mjs tests/e2e/v2-migration-save.spec.mjs tests/e2e/review-data-safety.spec.mjs
```

本地运行不验证 GitHub 的 PR 合并提交、跨任务报告和预览包上传；这些看目标 PR 的实际 Actions 回执。
