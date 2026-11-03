# 测试分组与夹具边界

Python 使用现有 `scripts/run_tests.py --pack <组> --required --report <文件>`。标准 unittest 发现完成后按用例归属筛选；默认无参数入口仍运行完整集合。`--required` 拒绝依赖、工具或夹具缺失导致的跳过，精确的平台不适用例外保持原规则。

| 组 | 负责的验证 |
| --- | --- |
| common | 常规算法、格式、状态、真实文件与 HTTP 契约；新增测试默认进入此组 |
| media | 真实 FFmpeg/FFprobe、媒体缓存和短媒体内核生成 |
| long-media | 30 分钟 tone30 内核生成与粗 mip 兼容、11 分钟音频对齐 |
| tools | 文档、发布、打包、执行器及维护工具 |
| manual | 需要维护者自有工程样例的历史场景；不能代替公开仓库的自动门禁 |

示例（先准备当前锁定依赖和所需 FFmpeg/FFprobe）：

```sh
python scripts/run_tests.py --pack media --required --report .artifacts/media.json
python scripts/run_tests.py --pack long-media --required --report .artifacts/long-media.json
```

冻结 REAPER 缓存解析仍在 common；短真实生成 tone_dual/tone_48k 在 media；30 分钟 tone30 在 long-media。三项生成继续使用同一比较方法和原断言。Windows 完整测试仍执行全部三项，并在同一次报告中拒绝漏项或跳过；分组不会缩减现有 CI 覆盖。

checksum 工具只在实际执行其测试类时准备 Bash。其他组的标准发现会导入测试模块，但不再因此启动 Bash。运行 tools 或默认全量时仍执行真实 checksum 脚本；Bash 缺失在 required 下仍失败。

## 按改动选择本地测试

先安装锁定的测试与开发依赖：`uv sync --group test --group dev`、`pnpm install --frozen-lockfile`。网站组另需 `pnpm --dir website install --frozen-lockfile`；真实浏览器需 Chromium，媒体组需 FFmpeg/FFprobe。test 组包含 NumPy 与 soundfile，不安装本地 ASR 模型运行时。

```sh
uv run --no-sync python scripts/test_workflow.py --stage merge --changed web/shared/tooltip.js --plan-only
uv run --no-sync python scripts/test_workflow.py --stage merge --changed web/shared/tooltip.js
uv run --no-sync python scripts/test_workflow.py --stage merge --base-ref origin/main
```

`--changed` 可重复，多个路径取并集。省略时检查 HEAD 相对工作区、暂存区及未跟踪文件；`--base-ref` 只比较已提交的分支差异，使用前确认本地 ref 新鲜。Git 差异读取失败直接退出；没有可靠路径时扩大到完整集合。重命名按删除和新增处理。

| 改动 | 选择范围 |
| --- | --- |
| README、用户文档、网站同步的工程及历史文档、网站源码 | 文档检查与真实网站同步、发布预览及构建 |
| 其他工程 Markdown | 文档检查；schema 仍扩大完整集合 |
| 生产叶子 | common、Node 浏览器契约、真实 smoke 与对应 E2E 消费者 |
| 媒体、波形、工程状态 | 追加 media；长媒体内核和工程/历史等路径追加 long-media |
| 独立清单工具 | 文档、自身 Python/Node 用例与真实工具 E2E；不准备应用与媒体依赖 |
| 独立 E2E spec | 实际执行该文件；导出或被其他测试引用、删除、未知情况扩大 |
| 共享 helper、装配、锁文件、未知路径 | 完整相关集合；网站生成目录和非正文文档夹具也保守扩大 |

常规 Python 用例沿用本页归组。Node 顶层用例分 common、browser、lifecycle、tools；新文件默认 common。真实 E2E 选择现有消费者，不改其断言与 ESM helper。共享状态、host、history、boot 和未知叶子扩大完整浏览器，不能被随后追加的文档或局部 spec 缩小。

`--stage dev` 只运行固定开发核心（`--component python/editor/launcher/all`），不代替改动影响回归。`--stage release` 本地运行完整 required 集合。`pnpm run test:dev/test:merge/test:release` 是同一入口的快捷命令。原无参数 Python runner 和 `pnpm run test:unit` 行为不变。

显式复现可用 `--stage merge --pack media`；定向浏览器使用 `--pack e2e --e2e-specs '["tests/e2e/shared-tooltip.spec.mjs"]'`。完整浏览器用 `--pack editor-e2e`，不能与定向 e2e 同时指定。局部复现结果不代表整条分支准入。

入口在 `.artifacts/test-workflow/<id>/` 保存计划与 summary；子命令由有界 run_check 执行。Python required 拒绝缺依赖跳过；Node 要求非空、无 skip 的实际 JUnit；浏览器先发现计划，再要求实际 JSON 完整、每例仅成功执行一次，无 skip、retry 或 flaky。错误、超时或无效报告立即使入口失败，后续未运行项不算通过。

Windows/Linux 的真实 macOS MobileAsset 字体资产用例按精确 ID 与原因记为平台不适用，旁边的合成目录用例仍执行；macOS 缺资产、其他依赖缺失仍失败。

本批只提供本地选测与执行，不改变 GitHub 工作流、CI 分片、汇总或分支保护。正式 PR 仍运行现有完整 CI；动态 job 的线上验收随后续接线完成。
