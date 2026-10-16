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
uv run --no-sync python scripts/test_workflow.py --stage merge --changed maw/quapeaks.py --plan-only
uv run --no-sync python scripts/test_workflow.py --stage merge --changed maw/quapeaks.py
```

`--changed` 可以重复；省略时读取当前 HEAD 相对的暂存/工作区改动及未跟踪文件。分支整体检查应使用 `--base-ref origin/main`，先确认本地 ref 是预期基线；CI 使用事件给出的 base SHA。Git diff 失败会终止，不能用空列表掩盖；没有可靠改动列表时扩大为全套 required 组。改名按删除与新增两条路径处理。

`--stage dev` 仅运行固定核心，不自动追加影响测试。先用目标方法/模块复现，一轮修改结束运行所属核心，再执行本次风险族。显式 `--base-ref` 只比较已提交的分支差异，未提交修改须另外纳入；默认工作区比较也不能代替整条已提交分支的检查。

## 分级依据

按影响面、错误后果与外部依赖分级，不按修改行数。少量共享状态或保存逻辑变化仍可能需要完整回归。

| 影响 | 开发反馈 | 合并准入 |
| --- | --- | --- |
| 文档正文、已知文档工具 | 相关文档/脚本回归 | docs；不准备应用依赖 |
| 独立测试 spec，无生产变化 | 该 spec 实际执行 | docs + 该 spec；多个修改取并集 |
| 局部生产算法或 UI | 目标行为测试 + 所属核心；前端重建受影响 bundle | common/browser/smoke + 消费者族 |
| 编解码、缩略图、媒体缓存 | 算法与短真实媒体 | media；长度/mip/长时声学偏移另加 long-media |
| 进程启动、取消、所有权 | 状态机 + 真实进程代表 | lifecycle/相关媒体或服务边界，按 OS 验证 |
| 共享 state/host/history/schema、测试 harness/锁/CI、未知边界 | 核心尽早反馈 + 定向故障复现 | 完整相关集合；共享基础设施和未知路径扩大全部 |

每个缩减必须说明保留何种独立故障检出能力。算法组合适合低层；跨模块接线至少保留一次真实往返；OS 回收、编解码、DOM/像素几何保留真实环境。依赖缺失不能转换为成功。

## 合并与发布

| 阶段/范围 | 必跑 | 按影响追加 |
| --- | --- | --- |
| 业务合并 | common Python/Node、构建与类型、browser 契约、两个真实文件/HTTP smoke specs、文档导航 | media、long-media、lifecycle、tools、完整浏览器回归 |
| 纯文档 | 文档导航、发布归档与对应回归 | Schema 文档视为共享契约，扩大所有业务组 |
| 网站 | 文档检查、网站构建 | 业务源码同批变化时合并相关组 |
| 文档工具 | check_docs/prepare_release_notes 及对应两个测试文件精确匹配时，仅 docs | 与生产或其他测试同批修改取并集 |
| 清单工具独立改动 | docs + 清单专属 tools 消费者；源目录带上自身真实 E2E | 无应用构建/类型检查/媒体依赖，混入其他消费者则恢复宽范围 |
| 其他工具 | 完整 tools；未知工具保守扩大 | 公共测试入口/依赖锁/工作流变更扩大全部组；目录名 tools 不能证明与业务无关 |
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

独立 `tests/e2e/**/*.spec.mjs` 修改选具体文件；文件缺失（包括改名旧路径）且未发现消费者时扩大完整浏览器；存在导出、其他测试 JS 引用或无法判断时扩大全组，防止遗漏读取该 spec 的 Node 消费者。helpers/fixtures/config 仍按共享基础设施处理。多路径只扩大集合，后加入 docs 或局部 spec 不得覆盖生产修改的要求。完整浏览器选择清空局部 spec 列表，禁止两种模式重复运行。该规则不自动批准测试删除，删掉独有保障仍需评审。

纯文档工具的精确白名单为 `scripts/check_docs.py`、`scripts/prepare_release_notes.py`、`tests/test_docs_check.py`、`tests/test_release_notes.py`。docs 已执行脚本及对应回归，因此复用现有门禁；相似未知文件名不命中。tools 组的打包、重构、类型与 Playwright 工具仍保留原依赖。缩略图新增真实 FFmpeg/HTTP/多进程场景归 media，纯 SQLite/线程/合成进程留 common；waveform 族包含 filmstrip 消费者。

文档检查的模式组合通过 `check_docs.main(argv)` 复用真实 parser 与完整命令体，保留 Git 读树/忽略检查；CLI 的 Unicode/JSON、默认/严格模式文本和进程退出码另有五次真实调用。这样减少解释器重复启动，不减少用例或替换业务检查。对模式增加断言时复用该入口；只有需要检验进程、编码或 CLI 边界时才追加真实子进程，避免每种组合都重新启动环境。

清单工具的 HTML 与 Markdown 构建回归均属于 tools，包括 `test_verification_checklist_build` 的 16 项用例；对应 Python 测试单独改动选择 docs/tools。工具源码、模板或示例目录还选择 `verification-checklist.spec.mjs`，保留真实 localStorage、下载/复制、布局与禁用状态消费者；只增加自身 spec，不准备应用预览。归属回归同时核对模块全部 ID，防止新增模块落入 common 后被工具选择漏过。

清单独立改动的计划另标 `tools_scope=checklist`：tools 精确执行两个 Python 模块（30 项）与一个 Node 文件（17 项），源目录带上 9 项真实 Chromium。它们不依赖应用 bundle、应用 tsc、Pillow 或媒体工具；CI 不同步应用 Python 环境、不安装 FFmpeg/媒体字体。docs 仍保留自身 37 项回归。新增应用消费者、未知路径、共享 harness/锁/工作流或混合应用 spec 会恢复宽范围；发布与显式 `--pack tools` 默认完整工具组。`--tools-scope checklist` 仅用于复现已确认的专属消费者或 CI 交接，不能拿局部结果代替整条分支的准入。

```sh
python scripts/test_workflow.py --stage merge --changed tools/verification-checklist/build.py --plan-only
python scripts/test_workflow.py --stage merge --changed tools/verification-checklist/build.py
```

清单设计需求、全部 56 项用例的用户后果、准备边界与实际隔离验收见[清单工具准备优化](../logs/release1.9.0-beta.2/261016_测试治理优化/清单工具准备优化.md)。低层表驱动失败组合与浏览器接线保障各自保留；页面不启动应用，仍必须实际启动 Chromium，不能用发现结果冒充执行。

导出菜单/时间线叶子修改除导出与混合波形消费者外，还选择 `editor-menu-focus.spec.mjs`，保留菜单实际间距及关闭后焦点/播放快捷键边界。新增测试文件进入全量集合不代表叶子选择已覆盖它；新功能引入消费者时需一并检查映射。共享输入仍扩大完整集合，多路径继续取并集。

每次运行的计划、聚合结果、Python IDs/skip 原因、Node JUnit 与 Playwright JSON 写入 `.artifacts/test-workflow/<id>/`，子命令的 bounded 日志与 PID/时限证据仍走 `scripts/run_check.py`。失败后停止当前批次，后续门禁尚未运行，不能宣称通过。NumPy/soundfile/Pillow/FFmpeg/内核缺失、编码器不支持、必需 fixture 缺失、Node/Playwright skip、超时均不能得到 required 成功。Windows 的特定 symlink 权限与 OS opener、不适用的 Unix checksum，以及非 Windows 的 LOCALAPPDATA/startfile 测试单独登记为 platform_not_applicable；Linux CI 必须运行符号链接边界。

CI 有独立选择、文档、业务、Windows 生命周期、完整浏览器分片与网站任务，最后由 `Required test gate` 汇总实际必需 job 的成功。选择器必须输出全部 13 个布尔 flag（含 application/real_media 准备需求）及 tools_scope；缺失、非法值、准备需求与消费者矛盾的输出直接失败，不能当作未选择。选中的 job 失败、取消或跳过也不能通过。`app` 继续表示需执行的业务/工具 job，不等于需要构建应用。

预览打包只在打包/资源/依赖/共享基础设施或未知路径触发，避免每个文案改动生成 Windows 包。正式发布先完成 Linux 质量组和完整浏览器汇总，再开始各平台打包；`publish` 的条件显式要求质量、完整浏览器和 Windows 打包成功。各平台发布验证包含 lifecycle，不依赖 PR 阶段曾跑过另一个 SHA。仓库外的 branch protection 要将汇总 `Required test gate` 设为 required，改源码不会自动修改 GitHub 的保护设置；既有 required job 名称需维护者迁移。

## 完整浏览器分片与结果

`.github/workflows/browser-gates.yml` 为合并与发布复用同一完整集合。四个独立 Linux runner 各运行一片，每片 2 workers、900s 执行期限；`fullyParallel=false` 保留文件隔离。增加 CI 机器可缩短墙钟关键路径，不意味着 CPU、总计 runner 时间或内存降低；四片案例数相近也不能证明耗时平衡，需以真实运行校准。

```sh
uv run --no-sync python scripts/test_workflow.py --stage merge --pack editor-e2e --browser-shard 1/4
uv run --no-sync python scripts/browser_results.py --reports .artifacts/browser-shards --total 4
```

分片命令会先发现完整集，再发现本片计划，最后执行本片；发现与运行都禁用 `.only`、retry 和 repeat。运行 JSON 必须包含计划中的每个用例，且每个用例实际成功一次，不能用 `--list` 的未执行状态或零退出码代替。Node required 报告同样拒绝空集和 skip；Python expected failure 也不能成为 required 成功。

每片写入 `browser-run.json`，记录 Git SHA、配置、选择范围、完整 ID 集、片号、计划 ID 与实际通过 ID。完整汇总只接受同 SHA、干净工作区、完整 `editor-e2e` 范围的全部分片，要求计划不重不漏、实际结果与计划一致。单片或叶子 `e2e` 成功只证明其自身范围；缺片、重复片、scope 不同、失败、skip、重试、空完整集均失败。非空完整集确实没有分配用例的片必须明示 `empty-shard`，不能伪造运行成功。

2026-10-14 已取得 794/794 真实四片与完整汇总通过证据；后续同步 main 新增用例，历史通过仅适用于当时受测 SHA。各阶段固定提交、实际结果与未验证边界见计划账本。

## 控制长期膨胀

每个新增测试先写清它能检出的具体错误与不可替代边界。优先给已有行为表补一个能区分错误的案例；只有风险或独立运行边界不同才新建测试/夹具。不要复制昂贵启动以检查多个字段，也不要用函数名、局部变量名或完整清单顺序代替行为；格式、安全、清单路径逃逸、依赖装配与离线发布契约仍可用静态检查。

重测试进入 media/long-media/lifecycle/browser 组时应说明真实依赖、代表数据、触发路径和成本证据。冻结参考文件只读；生成媒体在测试私有临时目录，按需生成一次。为确认解析格式不应先合成长媒体。保持每次 HTTP 服务器隔离，通过缩短测试专用 shutdown poll 消除空等；不要共享可变服务器来换取表面速度。

编辑器服务器 Python 回归只在测试类内复用首次真实读取的不可变脚本字符串；每页仍执行服务器 bundle 预检并重新渲染实际模板、项目与配置。HTTP 服务器、令牌、临时文件与设置不能随脚本缓存共享。类清理恢复真实入口，单独运行方法也必须实际读取产物；修改 bundle/构建机制时仍运行失效、哈希、重建与冻结分发回归。第六阶段保留原方法与断言，故障检出和成本见计划记录。

缩略图缓存测试以假媒体/JPEG验证真实 SQLite、ZIP、路径、取消与原子发布时，探测、目标解码、关键帧与拼图都在既定输入边界注入，媒体进程 guard 拒绝意外启动；不能反复解码假文件再吞掉错误。patch/目录以 addCleanup 保证 setUp 失败也恢复，不共享可变数据库。真实关键帧 PTS、预览登记/精确升级和跨进程取消仍由原媒体集成组运行。32 项原方法与故障对照见[缩略图缓存夹具降本](../logs/release1.9.0-beta.2/261016_测试治理优化/缩略图缓存夹具降本.md)；本机符号链接 skip 的 required 失败不改为成功。

PR 必须保留分组结果与耗时。新增重测试的评审要同时回答“删掉后漏掉什么”“能否在更低一层检出同一错误”。先做一次可复现的同集合 A/B，再决定移动、合并或退役；故障注入只用于证明替代保障，不把临时 probe 混进生产源码。成本显著增加时更新计划与实测，不制定脱离机器条件的通用秒数阈值。后续取得多次 CI 数据，再建立各组 p50/p95 和资源趋势；本轮不把一次采样当 p95。

本轮只退役两个纯实现形态测试：188 项完整清单快照、gap core 函数/缓存变量命名集合。装配顺序依赖仍由 Node 脚本顺序测试守住，清单重复/路径/冻结运行仍由 Python manifest 与离线包契约守住；gap 显示、恢复与清除仍由实际行为测试守住。其余混合静态文件保留，后续逐项拿故障检出证据讨论，不整文件删除。
