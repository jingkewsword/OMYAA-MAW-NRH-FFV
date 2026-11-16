# 2.0 测试门禁

本页说明 PR 作者会遇到的检查。实际执行范围以该次 Actions 的选择计划、任务和测试报告为准。

| 改动 | 完整测试矩阵 | 现有检查 |
| --- | --- | --- |
| 普通用户文档或网站源码 | 轻量路径；不运行跨平台测试 | 文档、网站检查仍运行；Windows 预览按自身规则判断是否打包 |
| 经逐个审核的单一领域路径 | Windows 与 Ubuntu 各运行对应 Chromium 测试 | 编辑器与 Windows 预览保留各自检查 |
| 应用、共享配置、未知或混合路径；非 PR 事件 | Windows 与 Ubuntu 各运行 Python、Node 和四片 Chromium，共 12 个执行单元 | 原编辑器、调试工具和 Windows 预览继续运行 |

选择器见 `scripts/ci_impact.py`。只有登记过且消费者已审核的路径可缩小范围；差异无法确认时进入完整矩阵。2.0dev 的 push 也运行完整矩阵。发布工作流不使用 PR 选测。

完整矩阵见 `.github/workflows/test-matrix.yml`。每个 Python 单元运行全量发现，并单独用 `--pack media --required` 验证真实媒体能力。每个平台的第 1 个浏览器单元另存未分片发现清单；汇总重新校验各片的发现与实际结果，检查提交、平台、配置、Playwright 版本，以及分片无重叠且并集等于完整发现。仅允许精确登记的跳过。测试未执行、报告缺失、额外跳过或失败均不能显示为通过。2.0 的统一轨道、旧工程迁移另存和数据安全浏览器用例仍由现有编辑器检查执行，也属于完整浏览器发现范围。

30 分钟 tone30 真实生成属于 `long-media`；双声道和 48 kHz 短媒体生成属于 `media`，冻结缓存解析仍属于 `common`。完整矩阵的两平台 Python 全量报告必须证明 tone30 的精确用例已执行且其用例或夹具没有跳过。由于全量报告只记录预期失败的总数，出现任何预期失败时也不能据此证明 tone30 通过；矩阵会拒绝该报告。Windows 预览继续在同一次全量报告中检查三项生成用例均被选择且缓存测试无跳过。

checksum 工具的 Bash 能力在执行其测试类时检查，普通测试发现不再启动 Bash。依赖或夹具缺失时，`--required` 仍会使对应组失败。

包含网站入口退役测试的浏览器分片先同步文档和发布数据，再构建真实网站；该测试读取构建后的 `website/dist`。其他分片不重复准备网站。

这套矩阵目前是**增加覆盖**。原编辑器和 Windows 预览中的固定检查仍保留；待在相同提交、平台和运行配置下逐项证明覆盖等效后，才会移除重复执行。不能把工作流绿色当作所有测试都运行；要同时看选择计划、执行任务、分片报告和结果。Windows 安装包以预览工作流实际构建、上传和启动证据为准。

本地可先运行相关组；`--required` 会拒绝依赖缺失导致的跳过：

```text
uv run --no-sync python scripts/run_tests.py --pack media --required --report .artifacts/media.json
uv run --no-sync python scripts/run_tests.py --pack long-media --required --report .artifacts/long-media.json
pnpm run test:unit
pnpm exec playwright test --config=tests/config/playwright.config.mjs --project=chromium tests/e2e/unified-tracks.spec.mjs tests/e2e/v2-migration-save.spec.mjs tests/e2e/review-data-safety.spec.mjs
```

本地运行不验证 GitHub 的 PR 合并提交、跨任务报告和预览包上传；这些看目标 PR 的实际 Actions 回执。

## 本地按改动运行

安装锁定依赖后，可用 `uv run --no-sync python scripts/test_workflow.py --stage dev --component editor` 运行固定开发核心，或用 `--stage merge` 执行影响范围。`pnpm run test:dev`、`test:merge` 和 `test:release` 是快捷入口。

`merge` 默认读取未暂存、已暂存和未跟踪文件；`--base-ref origin/2.0dev` 只比较该引用与 HEAD 的已提交差异，使用前须更新引用。也可重复传入 `--changed` 指定路径。读取 Git 差异失败时命令失败；空差异、删除、未知或混合路径扩大到完整集合。文档及网站运行其消费者，独立浏览器 spec 运行自身，清单工具运行自身测试及三个实际浏览器消费者。共享源码和 2.0 轨道、说话人、工程迁移路径扩大到完整集合；Python 测试来源可能包含动态 `load_tests`，因此也扩大。

`--plan-only` 只输出计划；`--stage merge --pack media` 可复现单组，不能代表完整门禁。`--stage release` 禁止指定局部组并运行完整本地 required 集合；本地结果不代表跨平台 CI。计划及结果位于 `.artifacts/test-workflow/`。浏览器用例先发现再运行，使用现有 CI 报告校验与 2.0 退役便携 HTML 的精确例外。缺依赖、失败、超时或报告无效时停止并返回失败。

## 编写 2.0 浏览器测试

- 直接保存的测试工程用 `AsrEditorUtils.makeProject` 或 `importProject` 生成完整 v2 数据；从 `tracks[]` 读取字幕，按角色或轨道 ID 定位。不要在运行态继续读写旧的顶层 `segments`。
- 有意测试 v1/v1.5 或缺字段的旧工程时，核对首次保存需要另存为 v2、原文件不被覆盖；静默保存返回失败是迁移保护的一部分。
- 新增字幕、波形双击和 Enter 的默认输入入口是波形快速编辑框。测试应检查当前可见输入框、实际输入和提交结果；下方字幕面板只在快速编辑无法打开时接手焦点。
- 对撤销和保存分别检查用户数据与持久化结果；`_dirty` 是编辑会话标记。颜色、贴纸组范围和副轨关系按当前 2.0 轨道与组契约核对，不沿用旧数组索引断言。
