# MAW 测试成本与长期治理方案

状态：**第一、二阶段已提交；第三阶段真实分片验收进行中**。2026-10-14 维护者授权继续本分支，先 Windows 代表性分片，再远端四片与汇总，失败修复；真实发布暂不执行。2026-10-13 的实施与阶段保存记录保留，未通过验收的部分不标记为完成。

## 第三阶段真实分片验收（2026-10-14）

| 项目 | 状态 | 实际结果与未完成边界 |
| --- | --- | --- |
| Windows 代表性分片 | 已通过 | 固定干净 27e1432 第 1/4 片 200/200，0 skip/失败/flaky、计划与实际 ID 一致，304.17s；Windows生命周期30/30。首轮和中间失败保留，原 3px/零越界及产品默认期限保持 |
| 远端四片与汇总 | 进行中 | 用户 fork Draft PR #2，首轮776/794、18失败，第二轮27e1432为793/794、1失败、0 skip/flaky，汇总正确拒绝。Linux业务组、Windows生命周期30/30和预览包成功。剩余主轨测试误选副轨中缝已确定检出并修正，待第三轮实际四片；不合并或真实发布 |
| GitHub required 设置 | 待处理 | 用户 fork main 当前无 branch protection、rulesets 为空；已核实但未修改仓库外设置 |
| 平台与产物验收 | 待处理 | Linux/macOS、实际预览打包以新 CI 结果为准；禁止用 Windows/契约结果外推 |
| 真实发布 | 仅说明 | 本轮用户明确排除；不创建 tag 或 Release |

本阶段证据与修复依据见[开发记录](../logs/unversioned/2026-10-13/TEST_SUITE_COST_AUDIT.md#第三阶段真实分片验收2026-10-14)。

2026-10-13 接续基线：`0735166`。代码已迁至维护者指定开发工作区，本地交付进入指定 codexdocs 的项目分支目录。第一阶段已通过且源码未变的媒体/HTTP 不重复验证。

## 第二阶段预期与验收

| 当前问题 | 预期结果 | 状态 | 实际与边界 |
| --- | --- | --- | --- |
| 完整浏览器时间预算 | CI 四片独立机器，每片仍 2 workers、900s；保留文件级隔离，不用本机增加并发换速度 | 进行中 | 可复用 CI 已实现；实际发现 794 例，四片 200/198/217/179，无遗漏与重复。仅发现验证，真实分片与 CI 耗时未验收；317/794 的旧进度不算通过 |
| 完整集合与结果汇总 | 同提交/配置/选择范围的完整发现集；各片计划不重不漏、实际与计划一致；缺片、重复、skip、失败、空完整集不能绿 | 进行中 | 实现与故障注入已通过；发现与执行统一禁止 `.only`、固定无 retry；零分配分片只在已知非空完整集下明示为空。尚待真实四片验证 |
| 发布与选择器假绿 | publish 显式要求质量和浏览器汇总成功；selector 缺失/非法 flag 失败；Windows 发布 SHA 验证 lifecycle | 已修复 | 消除 `!cancelled()` 绕过质量失败的条件；汇总校验 11 个 flag；各平台发布验证补 lifecycle。契约与拒绝错误结果回归通过，未执行真实发布 |
| 消费者与动态发现遗漏 | 导出/Gap 选择覆盖 waveform-history 混合消费者；无法静态判断的 unittest 模块保守加载与扩大 | 已修复 | export/gap 覆盖混合 waveform 消费者；动态 unittest 保守加载并扩大选择，全发现集合归属检查与代表性动态 fixture 通过 |
| 保存与接续 | 复验相应边界、正常提交推送、同步本地分支交付；未跑平台/打包保留真实状态 | 进行中 | 本轮 63 项回归通过、无 skip；按维护者要求保存阶段，不以发现成功代替完整运行。远端 required 设置及实际发布产物仍需独立验收 |

第二阶段证据：`.artifacts/phase2/discovery/summary.json` 明示 `runtime_complete=false`；63 项 required 回归为 `.artifacts/checks/20261013T091912Z-a77fcb2e/result.json`。最新 actionlint 与文档检查通过，文档无新增断链、无结构错误。详细发现、环境性失败和接续步骤见[开发记录](../logs/unversioned/2026-10-13/TEST_SUITE_COST_AUDIT.md#第二阶段开发发现与阶段保存2026-10-13)。

日期：2026-10-13。基线：上游 main `a34d502a33cfe9fcff0288c13b04f6bba3ca48fa`。

实施分支：`docs/test-suite-governance-20261013`。原审计提交 `21d2b7a` 保留测量与提案基线；本轮在同一分支正常提交实施阶段。

## 本轮实施与验收账本

| 阶段 | 预期结果 | 状态 | 实际结果与证据 |
| --- | --- | --- | --- |
| 稳定入口与影响选择 | dev 核心、merge 常驻/条件门禁、release 完整集合可执行；未知/公共变更扩大回归，集合没有无说明的遗漏 | 已修复 | 开发核心通过；Python 全发现集合与各 pack 一致且没有重复；未知/共享路径扩大，叶子浏览器功能按消费者族选择，required skip 故障检出通过 |
| 媒体与 HTTP 夹具 | 固定 cache 解析不生成 30 分钟 WAV；长生成显式选择；短生成/真实 HTTP 保留所有边界 | 已修复 | 6 冻结、2 短生成、1 长生成独立；154 夹具/HTTP 用例通过无 skip；102 同集合 A/B 减少 30.7% 墙钟时间，RSS 略升 |
| 生命周期与低价值断言 | 生产式默认期限保留、失活测试可注入短期限；只退役已证明冗余的实现形态断言 | 已修复 | Windows 生命周期组 30/30 无 skip，71.81s；真实应用 30s/45s 默认保留；只删除两个命名/完整清单快照测试 |
| 合并与发布流程 | required skip/超时/失败阻断、文档/网站不误触发全业务，构建一次，重测试命中改动时运行 | 已修复 | 已接入 CI 选择与汇总、发布质量依赖；准备环境打包前检查 bundle 新鲜度；actionlint、Python lint、锁一致性、工具和文档门禁通过。远端 CI 和实际打包尚未运行 |
| 验收与保存 | 选择覆盖检查、故障检出回归、对应真实进程/媒体/浏览器验证、成本对照和正常 commit/push | 仅说明 | 维护者要求先保存阶段提交；对应分组与 13 个真实 HTTP smoke 已通过。完整 794 Chromium 集按收束要求停止，不能计作全量成功。Linux/macOS、打包产物及 GitHub required 设置待续 |

授权范围为本计划的测试组织、夹具、测试入口/CI 与说明升级；用户明确要求留在本分支。主代理负责设计、集成与最终判断；一个 GPT-6.1-sol 子代理负责指定夹具文件，不并行修改入口/CI/计划。

## 讨论状态与流程升级条件

维护者已授权按本计划在当前分支实施。下列讨论项作为第一阶段采用规则的依据；成本预算和平台实际 CI 结果仍需持续校准。现行入口与准入规则见[测试分层](../INDEX.md#engineering-test-workflow)。

第一阶段采用以下决定，并保留进一步收束预算/平台证据的空间：

1. 开发小核心的模块归属与触发时机；是否采纳本文的 Python/编辑器/Launcher 分组。
2. 合并常驻集合与真实主流程 smoke；哪些公共改动需要扩大到完整相关 E2E。
3. 长媒体、编解码、生命周期与打包的 required 条件，缺依赖/skip 如何判定门禁未完成。
4. 混合测试文件的拆分与迁移顺序，退出低价值断言的风险映射和故障检出验收。
5. 测试成本预算、支持平台与发布验收范围；初始目标需以实际 CI 验证后定稿。

本轮实施路径：

1. 在本计划记录维护者通过的版本、范围及调整，状态改为“已通过，待实施”。
2. 从当时的目标分支建立实施分支，保留本次审计基线作为历史证据；不直接把审计 loader 或采集器当生产实现。
3. 先落地稳定 pack、影响选择与 required 结果汇总，再迁移长媒体/进程/编解码/打包任务；尚未拆开的有效保障继续保留。
4. 验证选择不会漏掉关键消费者，故障检出没有退化，required skip 不冒充通过，并对比同集合成本。
5. 验收后同步 `AGENTS.md`、贡献指南、开发/调试说明与 CI，消除旧命令和新入口的冲突，再将状态改为“已实施”。

上方讨论内容保留原提案依据；原审计提交 `21d2b7a` 当时仅含分析。后续实施已获授权，现行实现和未完成验收以上方阶段账本及测试指南为准。

## 目标与验收

找出当前测试反馈链的最大耗时与资源卡点，区分真实产品边界、架构契约、重复保障和实现细节断言。以同一基线的测量、源码和有限故障注入评估消融，不以“删后其余测试变绿”证明安全。

验收内容：测试规模清单；CI 与本机成本证据；值得保留的风险边界；可删除、合并、降层或按需运行的具体候选；防止持续膨胀的准入、成本预算和退役流程。原始输出保存在忽略的 `.artifacts/`；共享证据见[分析记录](../logs/unversioned/2026-10-13/TEST_SUITE_COST_AUDIT.md)。

## 第一性原理

测试价值来自它能否发现独立的用户损失或外部契约破坏。MAW 的核心任务是媒体转写、编辑、保存和导出；字幕 `segments` 是真源，波形是可重建缓存。毫秒时间、Unicode、撤销事务、保存原子性、本机文件访问范围、取消与进程回收，比函数名、源码片段和文件拆分形式更接近产品不变量。

每个新增测试必须能回答：什么错误会让它失败；错误会伤害哪条行为；为何现有测试不能发现；为何选择这层执行。允许增加真正独立的风险覆盖，不设机械数量上限。

## 原审计阶段进展（历史）

- 已完成：当前上游基线、92/38/70 个测试文件清单，CI 分步成本与本机进程树采样。
- 已完成：Python 2188 个 discovery ID 的分段记录核对；Node 624 例与两条 hang 的有效实验；E2E 794 例只收集，未做全量运行。
- 已完成：源码误报/漏报故障对照、短期限与 HTTP 轮询对照、同集合并发对照。
- 待讨论：确定测试入口、夹具与 CI 的升级范围及验收。方案通过后才逐风险族实施；当前基线的日志索引结构错误另行记录，本次未改变生产门禁。

## 初步治理方向（待证据修订）

1. 用风险族组织测试：真源与持久化、时间轴与编辑事务、导出与媒体、本机服务边界、运行环境与打包、真实交互。
2. 低层测试负责算法组合；集成测试负责跨模块协议；浏览器测试只承担真实 DOM、布局、媒体事件、用户操作与启动路径。
3. 在相同风险族内优先补充现有夹具与断言；新测试文件或新环境启动要解释额外检出能力。
4. 记录 suite 总时间与热点，区分安装 / 构建 / 测试 / 清理；慢测试先消除固定等待和重复启动。
5. 删除前建立风险到保留测试的映射，做代表性故障注入。不能被保留测试发现的关键故障必须补齐。
6. 将重构临时等价性工具与永久行为契约区分，阶段结束时明确保留理由或退出条件。

## 风险族与常驻保障

| 风险族 | 必须守住的损失 | 适合的最小执行层 | 代表性现有保障 |
| --- | --- | --- | --- |
| 工程真源与持久化 | 丢字幕、覆盖原工程、旧版读坏新格式、缓存进入真源 | Python / JS 算法与一次文件或 HTTP 往返 | project_contract、project_io、project_backups、project-load/save 的浏览器旅程 |
| 时间轴与编辑事务 | 非整数毫秒、Unicode 范围错位、多轨串改、取消破坏 redo、一次手势多个 undo | 算法组合 + 一次真实事件接线 | editor_utils、editor_history_gestures、editor-transactions、word-timing |
| Gap 与派生导出 | 原时间轴被不可逆重写、作用域删错字幕、被保护内容被误删、丢媒体流 | provenance 算法 + 后端导出契约 + 少量真实 FFmpeg | ai_cleanup_timeline、gap_removed_*、waveform 与导出行为 |
| 本机服务边界 | 任意路径读取或写入、跨站写入、无令牌变更、错误绑定 | 真实 loopback HTTP，合成目录 | local_editor_server 的 token、path escape、绑定、Range / 下载测试 |
| 作业与进程所有权 | 取消后落产物、孤儿进程占端口、误杀他人进程、提交中误报取消成功 | 状态机 + 合成真实进程树 | script_match_cancel、gap_removed_media_jobs、e2e_process_lifecycle |
| 装配与公开入口 | 旧 bundle 被运行、冻结包依赖 Node、classic 接线顺序错、公开 CLI 不可导入 | 构建器合成 fixture + 一次真实启动 | web_build、editor_manifest、editor_bundle、editor-bundle.spec |
| 布局与媒体交互 | 点击被遮挡、拖动丢事件、媒体播放/seek race、窄屏不可操作 | 真浏览器，行为与几何断言 | seek-race、cue-scroll、布局、ASS raster / frame |
| Provider 与 runtime | 参数传错、密钥泄露、响应不可解析、运行环境互相污染 | 录制/合成响应的 adapter 契约，离线配置 | provider tests、runtimes / freezer、local_log |

当前 root AGENTS 的“刻意收窄”应解释为工作流边界，而不是按早期只支持 Qwen 的快照删除当前已接受的功能。现行用户指南、schema、代码和设计契约共同界定范围；scope 收缩是产品决定。

## 测试分层与触发

推荐采用一套固定策略：**开发阶段 = 所属模块的小核心 + 本次影响回归；合并阶段 = 全局便宜回归 + 主流程烟测 + 按影响触发的重门禁；发布阶段 = 产物与完整平台验收。**

“开发必跑”指一项逻辑改动完成、准备提交或交付时，不是每次保存文件。相关源码、测试、依赖和运行环境未变时复用已通过结果；不因写了阶段说明再重跑同一层。只改文档、网站或独立开发工具不触发整个应用核心。

### 1. 开发中必跑：按入口选择最小稳定核心

| 改动范围 | 必跑底线 | 不在该底线里的内容 |
| --- | --- | --- |
| 所有改动 | diff / 文本基本检查；已有能证明本次行为的最小回归。存在独立检出缺口才新增测试 | 不要求每次改动新建测试文件，也不要求每次保存全量执行 |
| Python 应用代码：转写、后处理、服务或 CLI | 变更文件的现有 Ruff/语法规则；`test_project_contract.py`、`test_project_io.py`、`test_project_backups.py` | 不默认启动浏览器、解码媒体、安装模型、跑所有 runtime / provider |
| 编辑器 JS：`web/editor/`、所消费的 `web/shared/` | 已变更 JS 的语法/类型；重建并验证 editor bundle 一次；`test_editor_runtime.mjs`、`test_editor_state.mjs`、`test_editor_commands.mjs`、`test_editor_host.mjs`、`test_editor_history_gestures.mjs` | 不默认跑 794 个 E2E，也不默认跑生命周期失活矩阵 |
| Launcher JS / bridge | 变更脚本语法/类型；Launcher bundle 的构建/新鲜度；`test_launcher_bundle.mjs`、`test_launcher_contract.py`，再加相关 bridge 或 UI 回归 | 不强制执行无关编辑器状态核心；真实 ASR 和模型安装另按影响验证 |
| 纯 CSS / 模板 | 实际变更区域的浏览器几何/可点击回归；模板改变时补资产/装配验证 | CSS 单独变化不需要重新证明项目数据算法；CSS 由渲染读取，不无条件重建 JS |
| docs / website | 链接与导航/消费者检查；网站自身 check/build 按源文档同步或网站改动运行 | 普通文字修订不跑全业务、不重复检查器全部语义测试；修改检查器/消费者映射才跑它的回归 |

最小核心的本机验证（2026-10-13，同一审计基线）：Python 三文件 **65 例通过、0 跳过**，外层命令 1.31 秒；编辑器五文件 **33 例通过、0 跳过**，外层命令 1.58 秒。约 2.9 秒是两个调用合计，未包含构建、typecheck 或本次功能的相关测试，不承诺整项开发验证总在 3 秒内。它守住数据真源、格式与持久化、状态隔离、事务/undo/redo 和文件写入行为，不能证明叶子功能全部正确。

现有入口可执行，以下不假设已经存在 `test:fast` / `test:merge` 脚本；Agent 仍通过 run_check 包装：

```powershell
uv run --no-sync python scripts/run_check.py --timeout 60 -- uv run --no-sync python scripts/run_tests.py tests.test_project_contract tests.test_project_io tests.test_project_backups
uv run --no-sync python scripts/run_check.py --timeout 60 -- node --test tests/test_editor_runtime.mjs tests/test_editor_state.mjs tests/test_editor_commands.mjs tests/test_editor_host.mjs tests/test_editor_history_gestures.mjs
```

这两个 pack 按入口选择。一个同时改 Python 工程契约和编辑器事务的任务两者都跑；纯 CSS/网站/文档不套用这两个命令。

### 2. 开发按影响跑，并在合并前完成对应门禁

| 变更内容 | Python / Node 回归范围 | 浏览器或重测试范围 |
| --- | --- | --- |
| Provider 适配、请求选项、响应解析、错误分类 | 该 provider 的 `test_qwen*` / `test_openai_asr` / `test_doubao` 等；经过 GUI 时加相关 gui_workflow/gui_web，CLI 分派变化加 cli | 错误展示/输入校验变了，跑 launcher-api-errors/file-errors；mock/合成响应常驻，不在每次 CI 消费真实账号 |
| 断句、Unicode、items 文本映射、词时间、split/merge | segmentation、punctuation、editor_utils、word_timing、waveform_js 的相关算法族 | timed-text-edit、word-timing、split-desynced-items/split-word-gap、keyboard-timing 按实际操作路径选；公共时间单位变化扩大到多轨与导出 |
| 工程格式、load/save、检查点、备份、缓存剥离 | project_contract/io/backups、editor_state/commands/host、相关 project load/save 行为；影响后端时加 local_editor_server | editor-transactions、open-project-attach/drop、new-project、editor-i18n-save；格式变化还要迁移/旧工程/多轨往返 |
| 波形/频谱/缓存/音轨选择 | waveform、media_cache、reapeaks/quapeaks_container、quapeaks_generation/loudness 与 waveform_js | 拖动/选择/播放变化跑 waveform 与 seek/playback spec；缓存格式/内核/长媒体路径变化触发长媒体 gate |
| Gap / AI cleanup / 文稿匹配 / 去空隙媒体 | gap provenance、postprocess_ai_cleanup/timeline、script_match_cancel、gap_removed_audio/media_jobs/backend 等相关族 | AI scope、cancel/timeout、视频绑定/传输/提交场景；修改解码、stream copy、时间裁切时跑真实 FFmpeg 格式对照 |
| Export：SRT/ASS/FCP7/OTIO/Lottie/OGraf 等 | 对应 exporter/plan 与 project 元数据，涉及后端打包时加 local_editor_server 的对应接口 | 对应 export spec；ASS 像素布局/raster、真实 libass 只在预览/ASS/字体路径改动与发布验证 |
| 多轨/markers/speaker/overlay | 对应 editor_*、multi_subtitle_metadata、speaker_export、word_timing | multi-subtitle、overlay-track、markers、speaker-labels 与保存往返；公共状态/绑定变化扩大到事务主流程 |
| 本机 HTTP、host server API、路径/令牌/绑定/退出 | local_editor_server + server_align 的相关真实 HTTP 集合；媒体作业变化加 shutdown/jobs | 对应浏览器客户端、open/attach/下载；token/path/Range 不以 mock 替换 |
| 进程管理、readiness、helpers、Windows Job / POSIX group | e2e_server_process/lifecycle、e2e_process_lifecycle、run_check 或 media_job_shutdown 的相关族 | Windows 与 Linux 对应平台矩阵；保持退出、强杀、子孙回收、端口和旁观者。短期限优化实施前仍运行现有期限 |
| UI 布局、设置、主题、toolbar、popover、zoom | settings/geometry/tooltip 等相关低层行为 | 涉及区域的窄/宽视口、必要 zoom、实际间隔与 hit-test；共享 CSS token/layout 变化扩大到完整布局族 |
| runtime 安装/隔离、模型 inventory、freezer、下载/镜像 | runtimes、freezer、local/ocr/moss_runtime、local_models、hub_download 等对应族 | 相关 Launcher UI；安装/导入/取消烟测在干净环境。真实大模型转写不是每次 PR 默认项 |
| bundler / manifest / shared host / dependency / type 配置 | editor/launcher_bundle、script_order/syntax、manifest/assets、web_build、typecheck、跨语言契约；公共依赖变化跑全部便宜回归 | file/HTTP boot 必跑；装配变化涉及全部编辑器行为，合并前跑完整编辑器 E2E；Launcher 装配变化跑完整 Launcher 族 |
| docs checker / Release notes / runner / 重构工具 | 工具自己的测试 + 实际消费者。不要因普通应用改动总跑全部历史迁移工具 | runner/生命周期变化验证两个 OS；旧 mutation 工具存续时保留拒绝误写检查 |

路径只用于第一层定位。改 `shared`、schema、history、settings、host、项目格式、manifest、共享 CSS、测试 helper、依赖或 CI，必须按真实调用关系扩大到消费者。不是“源码 A 对应 test_A”就结束，也不只看新增/修改的测试文件。

### 3. 合并前常驻门禁：便宜的全局保障，不追求全套路径精准选择

对应用代码 PR，推荐合并资格由下列集合共同给出。门禁应验证拟合并结果与目标分支的组合；源分支 head 的 Preview 构建不能单独替代它。目标分支变化影响组合时更新门禁；这不意味着本地重复已有有效验证。

| 门禁 | 合并时执行内容 | 为什么常驻 |
| --- | --- | --- |
| 通用质量与装配 | Python lint；editor/Launcher 各构建一次与类型/必要加载顺序检查；公开入口/格式契约 | 便宜，发现跨文件/构建/依赖漂移；复用构建产物，不依赖 postinstall 后又重复 build |
| 全部便宜的离线算法与契约 | Python 业务算法、schema、持久化、各 provider 的合成响应、默认值、运行配置；Node 算法/状态/事务/装配，覆盖全模块 | 不把每条快单测做成路径选择规则；全局回归防跨模块漏选，维护成本比极细选择低 |
| 最小真实主流程 | 现有 `editor-bundle.spec.mjs` + `editor-transactions.spec.mjs`，覆盖 file/HTTP boot、项目/导出/undo 与真实编辑事务 | 构建/VM 单测不能证明浏览器接线、真实事件和 Server 页面正常 |
| 按影响门禁 | 执行上一表中的受影响 E2E/HTTP/媒体/平台风险族，作为本 PR 的合并资格的一部分 | “按修改跑”适用于合并前也是硬要求，不能把重边界一律推迟到发布 |

最小主流程不是全 794 例。对纯 Launcher 改动还须有 Launcher 的对应真实页面回归；当前共用两个 editor spec 不证明 Launcher 交互正确。可从现有相关 spec 选择少量启屏/配置/启动校验，形成稳定 Launcher 烟测入口；此入口尚未实现，不虚构现有脚本。

纯 docs/网站/独立工具 PR 的合并资格运行它自己的检查与消费者，不触发完整应用门禁；若文档/配置被程序消费，按消费链扩大。CI 的选择入口或映射被修改时验证选择逻辑，并做一次不依赖映射的全回归确认。

### 4. 合并条件性重门禁与发布验收

| 集合 | 必须在合并前跑的触发 | 未触及时的位置 |
| --- | --- | --- |
| 30 分钟 tone30、粗 mip 层级、长媒体内核生成 | quapeaks/reapeaks 内核/容器/生成参数/媒体解码/长媒体分块相关改动，或相关依赖升级 | 明确的发布验收；可重复的性能基线，不在每次小 UI 改动执行 |
| 真实 FFmpeg、AAC/MP3/多轨/时间裁切/libass | 对应媒体处理、export、音轨、ASS/字体或 FFmpeg 依赖/分发改变 | 发布对应平台产物验收；算法层组合仍进通用回归 |
| Windows Job 与 POSIX 进程矩阵 | 生命周期代码、测试 server helpers、readiness、取消/作业 shutdown、runner 变化 | 相关平台发布验收；普通离线函数改动不用支付完整启动失活期限 |
| Windows PyInstaller / macOS / Linux AppImage | spec/build script/bootstrap/resource 路径/依赖/runtime 清单/公开入口/产物内容改变 | Windows Preview 可按维护者需要提供，但不把每个 docs/UI 小 PR 的完整打包当通用必需测试；发布跑正式支持平台产物 |
| 全编辑器或 Launcher E2E | 对应装配、公共 schema/host/history/全局布局、依赖或共用测试 fixture 有广泛影响；跨多风险族重构 | 每次发布前完整验收；小叶子功能 PR 仅所影响的族与常驻 smoke |
| 真 API / 真实大模型 | 支持承诺改变、SDK/模型/实际协议改动需要外部证据，离线 fixture 不足以证明时，维护者有对应环境 | 明确的发布/人工集成验收；不用 live API 替代离线契约，也不因环境缺失虚报已验证 |

一旦当前 PR 命中 required 重门禁，依赖缺失/skip 必须被报告为未验证或阻塞该门禁，不能计作通过。未被选择与被选择后跳过要分开。完整 E2E 未执行时不拿几个 smoke 的绿灯冒充。

### 5. 当前能做什么，哪些要先改测试组织

上述是推荐执行策略，不是已上线的 CI。

现在可直接采用最小开发核心、按风险族开发与 PR 验证、现有两个主流程 spec、按影响运行重测试。Node 常规 37 文件/624 例的已测集合排除了整个生命周期矩阵文件，但仍包含浏览器、进程烟测与开发工具，**不等同于纯算法集合**；短期限改造与工具分类后再形成常驻 merge pack。

Python 的 `run_tests.py` 默认 discovery 会包含长媒体和混合 HTTP/资产测试，不能把它重命名成 fast 就当分层完成。过渡期：**尚未安全拆开的文件保留当前回归，接受成本**；只迁移已审阅的具体重用例/族到显式 required 条件门禁，保留固定 cache/格式/安全保障。不要整文件跳过，也不要靠不安装 NumPy/FFmpeg 制造“快全量”。

实施顺序：先建立少量稳定 pack 与 required 结果汇总（始终有合并资格结果）；再抽出 long-media/process/codec/build jobs；再整理混合文件。选择未识别文件或依赖不确定时，回退到完整相关回归。完整回归可作为发布检查校验选择遗漏，本文不创建定时任务。

## 新增测试的准入

PR 对测试只补充以下短说明，不引入逐用例庞大登记表：

1. 风险：用户或外部契约会失去什么？
2. 检出：能让它变红的具体错误是什么？
3. 独立性：现有风险族为什么不会发现？优先在原 fixture 加一个有效案例。
4. 层级：为何需要真实浏览器、FFmpeg 或子进程，低层不足在哪里？
5. 成本：新增环境启动、固定等待或大型 fixture 的代价；临时重构保障的退出条件。

拒绝仅验证“函数存在、实现写法相同、spy 被调用”的新增用例，除非该调用本身就是外部边界。spy 比如“不会向任意路径写入”“只在成功检查后保存 Key”“冻结包不执行 Node 构建”有明确边界价值。

## 成本预算（实施前的初始目标）

目标约束反馈链，而不是强制按秒删除保障：

- Node 离线算法与契约初始目标 30 秒；生命周期独立报告，先消除 45/30 秒真实等待。按硬件固定的基线比较，未测到的 p95 不宣称已有。
- 单个纯算法测试超过 1 秒进入热点解释；有真实环境启动的文件超过 10 秒必须说明启动次数与独立边界。达到阈值先合并 fixture、消除重复启动和控制并发，再决定降层。
- Python 完整离线套件目标先按当前 CI 75–83 秒建立基线，再用实测决定可达预算；真实编解码与 HTTP 可单独报告。资源预算按本机采样与 CI 能力确认，不拍一个脱离环境的内存硬上限。
- 保存一次 suite 总耗时、前 10 个热点、峰值进程树 RSS、通过/失败/跳过与环境版本。相对变慢 20% 且绝对增加超过 5 秒触发一次原因审阅，不自动失败、不自动重跑。
- 默认无无限 retry；隔离 flaky 的 bug 和恢复条件，不把 retries 当稳定性证据。等待以可观察状态为准，超时作为上限；timeout 行为测试使用可注入短期限，不靠真实生产时长证明。

这些是初始建议，不是已上线的新门禁，也不要求为了满足预算删除关键测试。

## 消融与退役程序

以风险族为单位，记录被删断言、保留保障、代表性故障和适用平台即可：

1. 列出要退出的具体断言，不能整文件凭名称删除混合的行为/静态测试。
2. 做等价变更，确认保留保障不因重命名或文件移动变红。
3. 在同一边界注入代表性错误，比较退出前后的检出；算法/接口/真实事件至少选与风险相符的一层。少量故障注入是证据，不是穷尽证明。
4. 数据损失、路径安全、取消/提交 race 或公开格式的故障若漏检，先补保留层，再退出旧断言。
5. 记录同机同环境的通过/失败/跳过和成本；测试集合相同才比较并发优化，减少集合的测量明确注明失去哪些保障。

每次功能合并复用上述 5 个问题；每次版本发布只回看热点与已满足退出条件的临时保障，不要求周期性清点每条快单测。连续增加成本的风险族承担一次合并/降层任务。保留一份方案和一份证据记录，不不断生成新的治理文档、登记库和扫描器。

## 优先实施顺序（待维护者采纳）

1. 提取生命周期 readiness 的测试期限参数，保留生产默认值与真实进程回收；限制重测试并发，分离纯算法入口。
2. 将 30 分钟 tone30 的约 1.8GiB 生成场景从默认轻量回归中分层；固定 cache 解析不重造长源媒体，短媒体保留双声道/48kHz/真实内核，粗 mip 层级保留合成或冻结边界，长媒体生成明确在内核与发布验收中运行。先消除同轮重复生成，显式报告 NumPy/FFmpeg 缺失造成的 skip。
3. 将 HTTP 测试轮询间隔作为夹具参数，保留每例隔离与真实 HTTP；共享只读模板/静态资产，避免共享可变服务状态。
4. 合并或降级 editor_assets / Launcher asset 中的实现片段断言；保留公开 template、资源自包含、manifest 安全与行为接线。
5. 去掉 packaging contract 的重复执行；用显式 build 与忽略 postinstall 的安装组合消除重复前端构建。先保持同一构建结果的验证。
6. 对存续的历史重构工具和对应测试一起决定是否退役。工具仍能执行写入时，其拒绝误写的测试具有价值，不能只删守卫测试。

本文当前是待讨论计划。后续明确通过后才单独实施测试/CI 调整；本次分析没有删除用例或改变默认门禁。
