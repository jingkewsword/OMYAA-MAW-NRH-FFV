# 测试分层与准入

本指南对应 `scripts/test_workflow.py` 与 `scripts/test_policy.py`。测试成本分析见[原始审计](../logs/unversioned/2026-10-13/TEST_SUITE_COST_AUDIT.md)，实施账本见[测试治理计划](../plans/TEST_SUITE_GOVERNANCE.md)。这里定义当前入口；审计中的旧时间只作基线。

## 日常开发

准备环境一次：`uv sync --group test --group dev`、`pnpm install --frozen-lockfile`。真实媒体组需要 PATH 中的 FFmpeg/ffprobe，浏览器组需要 `pnpm exec playwright install chromium`。test 组只有 NumPy、Pillow、soundfile，不下载 ASR 模型或完整 local/OCR 运行时。

```sh
uv run --no-sync python scripts/test_workflow.py --stage dev
uv run --no-sync python scripts/test_workflow.py --stage dev --component python
uv run --no-sync python scripts/test_workflow.py --stage dev --component editor
uv run --no-sync python scripts/test_workflow.py --stage dev --component launcher
```

默认开发核心包含 Python 工程契约、读写、备份 65 用例，以及 Node 编辑器 runtime/state/commands/host/history_gestures 33 用例。这个集合适合一次修改阶段结束时运行；它不代替改动涉及的回归。Launcher 开发使用对应 component。修复失败时先运行具体测试文件或方法，然后扩大到相关组。

```sh
uv run --no-sync python scripts/run_check.py --timeout 90 -- uv run --no-sync python scripts/run_tests.py --required tests.test_project_io
uv run --no-sync python scripts/test_workflow.py --stage merge --changed maw/reapeaks.py --plan-only
uv run --no-sync python scripts/test_workflow.py --stage merge --changed maw/reapeaks.py
```

`--changed` 可以重复；省略时读取当前 HEAD 相对的暂存/工作区改动及未跟踪文件。分支整体检查应使用 `--base-ref origin/main`，先确认本地 ref 是预期基线；CI 使用事件给出的 base SHA。Git diff 失败会终止，不能用空列表掩盖；没有可靠改动列表时扩大为全套 required 组。改名按删除与新增两条路径处理。

## 合并与发布

| 阶段/范围 | 必跑 | 按影响追加 |
| --- | --- | --- |
| 业务合并 | common Python/Node、构建与类型、browser 契约、两个真实文件/HTTP smoke specs、文档导航 | media、long-media、lifecycle、tools、完整浏览器回归 |
| 纯文档 | 文档导航、发布归档与对应回归 | Schema 文档视为共享契约，扩大所有业务组 |
| 网站 | 文档检查、网站构建 | 业务源码同批变化时合并相关组 |
| 工具 | 文档检查、tools | 公共测试入口/依赖锁/工作流变更扩大全部组 |
| 发布 | 所有 required 组 | 打包平台分别验证 Python/媒体/长媒体/生命周期/工具与 Node 语义；完整 Chromium 在四个独立 Linux runner 执行并汇总 |

`--stage merge --plan-only` 输出选择与原因；`--pack` 可以显式选择组进行复现。`pnpm run test:dev`、`test:merge`、`test:release` 是同一入口的快捷方式。历史 `pnpm run test:unit` 仍运行全部顶层 `.mjs`，其中含真实浏览器与进程测试；无参数 `scripts/run_tests.py` 仍保留历史全量 unittest 行为，不能拿其允许 skip 的结果代替 required 门禁。

| 组 | 保障与成本 |
| --- | --- |
| common | 默认接收新增测试，保留全局算法/格式/状态/安全/真实文件与 HTTP 契约；不对每个便宜用例建立路径规则 |
| browser | 三个顶层真实 Chromium 契约文件，独立于纯 Node 语义 |
| smoke | editor-bundle、editor-transactions 两个真实服务器/浏览器 spec |
| media | 真 FFmpeg/ffprobe、容器与缓存生成；混合文件只按方法或类分流，其他方法仍在 common |
| long-media | 30 分钟 tone30 内核兼容与 11 分钟声学对齐；不能由短音频代替粗 mip/长时偏移保障 |
| lifecycle | 真实进程树、异常退出、信号、失活、端口再绑定、无关进程隔离；合成失活期限可缩短，真实应用默认期限保留 |
| tools | 文档/发布/打包/执行器/重构工具；Unix checksum 在 Linux required，Windows 明示不适用 |
| e2e | 叶子功能按现有消费者族选择具体 spec；Launcher、断句/词时间、Gap/AI/文稿、波形/播放、ASS/导出、多轨/markers/overlay、cue 列表、tooltip 与 onboarding 有明确族映射 |
| editor-e2e | 当前完整 Chromium spec 集，含 Launcher；共享 host/state/history/schema/boot/全局布局或未识别路径扩大到全量 |
| manual | 依赖个人 real .mosp 示例的历史方法。显式运行并准备自有数据，不是公开仓库 required 门禁 |
| website | 独立网站构建，需要网站目录自己的锁定依赖 |

未知生产路径扩大全部组。当前业务路径规则刻意保守：`maw/` 与服务器触发媒体和相关浏览器族；涉及 waveform/reapeaks/quapeaks/project/history/script_timestamp 时再触发长媒体。`web/` 按叶子消费者族选 E2E，共享状态/host/history/boot/全局布局或未知叶子扩大完整浏览器。共享测试基础设施、依赖锁与工作流触发所有 required 组和预览打包。修改测试文件按其实际源代码内用例所属组选择。新测试默认 common；禁止通过未登记的新重测试逃避成本讨论。

每次运行的计划、聚合结果、Python IDs/skip 原因、Node JUnit 与 Playwright JSON 写入 `.artifacts/test-workflow/<id>/`，子命令的 bounded 日志与 PID/时限证据仍走 `scripts/run_check.py`。失败后停止当前批次，后续门禁尚未运行，不能宣称通过。NumPy/soundfile/Pillow/FFmpeg/内核缺失、编码器不支持、必需 fixture 缺失、Node/Playwright skip、超时均不能得到 required 成功。Windows 的特定 symlink 权限与 OS opener、不适用的 Unix checksum，以及非 Windows 的 LOCALAPPDATA/startfile 测试单独登记为 platform_not_applicable；Linux CI 必须运行符号链接边界。

CI 有独立选择、文档、业务、Windows 生命周期、完整浏览器分片与网站任务，最后由 `Required test gate` 汇总实际必需 job 的成功。选择器必须输出全部 11 个准入 flag，缺失、非法值或互相矛盾的输出直接失败，不能当作未选择。选中的 job 失败、取消或跳过也不能通过。

预览打包只在打包/资源/依赖/共享基础设施或未知路径触发，避免每个文案改动生成 Windows 包。正式发布先完成 Linux 质量组和完整浏览器汇总，再开始各平台打包；`publish` 的条件显式要求质量、完整浏览器和 Windows 打包成功。各平台发布验证包含 lifecycle，不依赖 PR 阶段曾跑过另一个 SHA。仓库外的 branch protection 要将汇总 `Required test gate` 设为 required，改源码不会自动修改 GitHub 的保护设置；既有 required job 名称需维护者迁移。

## 完整浏览器分片与结果

`.github/workflows/browser-gates.yml` 为合并与发布复用同一完整集合。四个独立 Linux runner 各运行一片，每片 2 workers、900s 执行期限；`fullyParallel=false` 保留文件隔离。增加 CI 机器可缩短墙钟关键路径，不意味着 CPU、总计 runner 时间或内存降低；四片案例数相近也不能证明耗时平衡，需以真实运行校准。

```sh
uv run --no-sync python scripts/test_workflow.py --stage merge --pack editor-e2e --browser-shard 1/4
uv run --no-sync python scripts/browser_results.py --reports .artifacts/browser-shards --total 4
```

分片命令会先发现完整集，再发现本片计划，最后执行本片；发现与运行都禁用 `.only`、retry 和 repeat。运行 JSON 必须包含计划中的每个用例，且每个用例实际成功一次，不能用 `--list` 的未执行状态或零退出码代替。Node required 报告同样拒绝空集和 skip；Python expected failure 也不能成为 required 成功。

每片写入 `browser-run.json`，记录 Git SHA、配置、选择范围、完整 ID 集、片号、计划 ID 与实际通过 ID。完整汇总只接受同 SHA、干净工作区、完整 `editor-e2e` 范围的全部分片，要求计划不重不漏、实际结果与计划一致。单片或叶子 `e2e` 成功只证明其自身范围；缺片、重复片、scope 不同、失败、skip、重试、空完整集均失败。非空完整集确实没有分配用例的片必须明示 `empty-shard`，不能伪造运行成功。

2026-10-13 第二阶段已验证 794 例实际发现与四片分配，并通过针对性故障检出回归；真实四片运行与远端 CI 尚未完成。这是已实现的流程，完整验收仍见计划账本。

## 控制长期膨胀

每个新增测试先写清它能检出的具体错误与不可替代边界。优先给已有行为表补一个能区分错误的案例；只有风险或独立运行边界不同才新建测试/夹具。不要复制昂贵启动以检查多个字段，也不要用函数名、局部变量名或完整清单顺序代替行为；格式、安全、清单路径逃逸、依赖装配与离线发布契约仍可用静态检查。

重测试进入 media/long-media/lifecycle/browser 组时应说明真实依赖、代表数据、触发路径和成本证据。冻结参考文件只读；生成媒体在测试私有临时目录，按需生成一次。为确认解析格式不应先合成长媒体。保持每次 HTTP 服务器隔离，通过缩短测试专用 shutdown poll 消除空等；不要共享可变服务器来换取表面速度。

PR 必须保留分组结果与耗时。新增重测试的评审要同时回答“删掉后漏掉什么”“能否在更低一层检出同一错误”。先做一次可复现的同集合 A/B，再决定移动、合并或退役；故障注入只用于证明替代保障，不把临时 probe 混进生产源码。成本显著增加时更新计划与实测，不制定脱离机器条件的通用秒数阈值。后续取得多次 CI 数据，再建立各组 p50/p95 和资源趋势；本轮不把一次采样当 p95。

本轮只退役两个纯实现形态测试：188 项完整清单快照、gap core 函数/缓存变量命名集合。装配顺序依赖仍由 Node 脚本顺序测试守住，清单重复/路径/冻结运行仍由 Python manifest 与离线包契约守住；gap 显示、恢复与清除仍由实际行为测试守住。其余混合静态文件保留，后续逐项拿故障检出证据讨论，不整文件删除。
