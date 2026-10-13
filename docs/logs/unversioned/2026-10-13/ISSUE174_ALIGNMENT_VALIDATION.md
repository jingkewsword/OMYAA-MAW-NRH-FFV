# Issue #174 文稿驱动对齐验收（2026-10-13）

## 结论与范围

对照 [Issue #174](https://github.com/Moyf/moys-asr-workflow/issues/174) 的需求，本次在上游 main `a34d502a33cfe9fcff0288c13b04f6bba3ca48fa` 上检查现有实现并执行定向验收，未发现已证实、需要修改业务源码的缺口。交付验收证据和人工核查步骤，不新建功能、不改已有入口。Issue 经当日 GitHub API 核实仍 open、0 评论；本次不自动评论或关闭。

核心能力在 [文稿驱动对齐指南](../../../user/SCRIPT_DRIVEN_ALIGNMENT.md) 已说明。实际入口是 `maw/script_timestamp_alignment.py`，与已有工程的 `maw/script_alignment.py` 口播匹配不同。真实模型质量尚未验收，不能将本报告视为整个需求可以无条件关闭的证明。

工作分支：`codex/issue-174-script-alignment-validation`。使用本会话管理的独立 worktree；业务源码、用户指南、CHANGELOG 均未修改。已按锁文件准备独立 Python 与 Node 环境，没有同步其它 checkout 的 venv。前端 bundle 仅供本机测试，不入库；未生成 `blank-editor.html`。

## 需求 → 实现 → 证据 → 边界矩阵

状态采用仓库账本约定。已有能力通过验收使用“仅说明”，不将其记为本次新修复。

| 需求 / 验收点 | 状态 | 当前实现与入口 | 本次证据 | 未验证边界 |
| --- | --- | --- | --- | --- |
| 文稿 + 媒体直接生成 MOSP / SRT，全程跳过 ASR | 仅说明 | `maw/cli.py::_run_script_alignment`；`maw/gui_web.py::LauncherApi.run_timestamp_alignment` 的 script 分支；`maw/local_runtime_worker.py::main` 的 script-align；`run_script_alignment` | 22 项文稿回归；补充探针实际执行 worker branch，ASR engine 与 CLI 转写入口设 AssertionError 守卫；真实 FFmpeg + 替身对齐产物写出通过 | 模型为替身；不是实际 ForcedAligner 推理 |
| 非空文稿行 = cue，保留标点、空白与组合字符；整数毫秒 / items | 仅说明 | `read_script_lines` 忽略空行并 strip 行首尾；`tokens_to_script_segments` 恢复行内原文；模型输入 NFC；项目 `preserve_punctuation=true` | BOM、NFD 法语、日语浊音、韩语 Jamo、跨行 token、绝对偏移回归；worker 产物 2 cue / 5 items 经 Server 打开、POST 保存、磁盘、刷新后 ID / 原文 / 所有 start/end 逐项一致 | 行首尾空白和空行按现行指南规范；模型 token 跨行时仅在该 token 时间范围内分配，不代表每字声学测量 |
| ≤300s 整段单发，与既有 75s 工具隔离 | 仅说明 | `MAX_SCRIPT_ALIGNMENT_MS=300000`；`plan_script_anchors` 返回 single；`run_script_alignment` 不另切单发音频 | 300000ms 边界规划测试；短合成波形确认整段一次调用 | 300s 真实模型运行未测；不外推时间精度 / 速度 |
| >300s 静音锚点分块，禁止按字数比例切音频 | 仅说明 | `speech_ranges` 解析真实 silencedetect；行与 span 一一映射并合并 ≤300s 连续组；`_extract_audio_span`；每块加绝对 start | 660000ms / 33 行合成 WAV 经真实 FFmpeg 检测与切块，3 次替身对齐；每行 start 为 index × 20000 + 100；预检查与执行计划相同 | 合成 tone 与替身 token 只证明无工程偏移累积，不能证明 >10min 真人念稿无漂移 |
| 脏录音 / 区间数量错配至少有诊断或降级路径 | 仅说明 | 数量错配、超长连续语音、无语音、文字未完整覆盖、倒序 / 零时长 / 重叠 / 超界、自动 cue 跨 span 均拒绝；提示人工锚点或 ASR 后口播对齐 | 现有异常单测；补充真实 silencedetect 的 3 span / 1 行在模型前拒绝；自动 cue 跨语音范围拒绝 | 相同 span 数但内容读错、重复、口误可能仍输出；音频正确性不能由回传文稿覆盖率判断 |
| 人工锚点支持组行、跳过无关音频 | 仅说明 | `read_anchors` / `validate_anchors`；1 基非空行号、绝对整数毫秒、顺序完整覆盖、不重叠、每组 ≤300s；优先于短 / 自动策略 | 人工锚点文件、短低音量、覆盖 / 重叠 / bool 时间拒绝回归；补充两组人工锚点实际切块流程 | 需人工确认组内文稿与声音对应；本轮没有真人锚点听审 |
| 无模型预检查，输入变化不信任旧预览 | 仅说明 | `check_script_alignment` 仅准备媒体 / 规划；CLI --alignment-check；Launcher check_script_alignment；正式执行重新准备 | 模型构造 / runtime status 设断言守卫；FFmpeg 预检查不写输出；Chromium 输入变化清除结果且保留原工程 | 预检查不证明模型安装就绪，也不证明声音念对 |
| 对齐失败不写半成品工程 | 仅说明 | 所有块先累计在内存并校验，完成后才调用 `write_artifacts` | 首块文字缺失失败；第二块异常带行范围诊断；自动边界 / 数量拒绝；块间协作取消均未创建输出目录 | 指对齐 / 输入校验失败；writer 按文件原子替换，MOSP 与 SRT 不是跨文件事务。本轮未注入磁盘写入故障 |
| Launcher / 编辑器接线与可用布局 | 仅说明 | 工具箱 → 时间码 → 文稿模式；仅 Qwen；显示策略 / 行数 / 块数 / 音轨与听审提醒；输出路径进入工程栏 | 4 项 Launcher Chromium（后端返回替身）+ 1 项真实 Server 回读；中英文、输入检查、间距与截图；补充 worker 产物全时间码 round-trip | 没有真实 GUI pywebview 与模型联跑；未改布局 |
| 真实短录音、>10min 长念稿、脏录音听审与性能 | 阻塞 | 复用已有 ForcedAligner 及用户获准素材 | 本机检查：installed=false / runtime_available=false，managed local-runtime missing；没有本任务提供的获准真实素材 | 待有模型和素材的环境逐项听审；不擅自下载大模型、不测假加速 |

ForcedAligner 回传文字来自输入文稿。用 difflib 比对这些文字无法证明声音读对，因此本次不添加这种“兜底”。保留明确拒绝、人工锚点及 ASR 后口播对齐引导。锚点可视化、逐块进度、UI 停止、续跑与加速属于独立候选；本次没有据此扩大功能。补充取消证据只覆盖传入 cancel_event 后的块间协作检查，不证明 GUI 停止按钮或运行中的 FFmpeg / 模型立即取消。

## 自动化与环境证据

全部检查从本任务 worktree 以 `uv run --no-sync python scripts/run_check.py --timeout 180 -- <command>` 执行。原始输出在被忽略的 `.artifacts/checks/<run-id>/output.log`，对应 `result.json` 记录命令、cwd、退出码、耗时与 PID。以下路径均相对 worktree，验证业务基线均为 `a34d502a`，之后只增加本报告及索引。

| 层 | 内层命令 / 内容 | 实际结果 | result.json 所在 run-id |
| --- | --- | --- | --- |
| 文稿契约 | `uv run --no-sync python scripts/run_tests.py tests/test_script_timestamp_alignment.py` | 22 通过，0 跳过；21.33s | `20261013T025815Z-c11d5347` |
| 后端 / 工程 / SRT 契约 | `uv run --no-sync python scripts/run_tests.py tests/test_timestamp_alignment.py tests/test_project_io.py tests/test_postprocess_io.py` | 30 通过；1.19s | `20261013T025918Z-5681bff5` |
| Chromium / Server | `node node_modules/@playwright/test/cli.js test tests/e2e/script-timestamp-alignment.spec.mjs tests/e2e/script-alignment-editor-roundtrip.spec.mjs --project=chromium --workers=1` | 5 通过；38.31s；非全量 UI 回归 | `20261013T025843Z-5622ad48` |
| Editor 构建 | `node scripts/build-editor.mjs --check` | fresh，exit 0 | `20261013T025922Z-cfcda561` |
| Launcher 构建 | `node scripts/build-launcher.mjs --check` | fresh，exit 0 | `20261013T025926Z-b4016645` |
| 类型 | `node node_modules/typescript/bin/tsc -p tsconfig.typecheck.json` | exit 0 | `20261013T025928Z-c36dc69e` |
| 补充 worker / 负向契约 | `uv run --no-sync python .artifacts/issue174/contract-probe.py` | 5 组断言通过；12.83s | `20261013T030117Z-96487c33` |
| 补充全部时间码 / 间距 | `node .artifacts/issue174/browser-probe.mjs` | ID、cue/items 时间码精确回读；所有测量 ≥8px；25.64s | `20261013T030323Z-11d4a9b1` |
| 核查页生成 | `uv run --no-sync python tools/verification-checklist/build.py --data .artifacts/issue174/checklist.json --output .artifacts/issue174/verification.html` | exit 0 | `20261013T030631Z-86f22d5f` |
| 文档检查 | `uv run --no-sync python scripts/check_docs.py` | exit 1；0 新断链，1 基线结构错误 | `20261013T030638Z-a45ec14d` |
| 文档检查器回归 | `uv run --no-sync python scripts/run_tests.py tests/test_docs_check.py` | 19 通过；38.33s | `20261013T030652Z-7140e09c` |
| 文档基线对照 | `scripts.check_docs.read_tree` / `structure` 读取 a34d502a 和当前树 | 相同且只有已存在日志缺导航；本次未增加结构问题 | `20261013T030757Z-b86f213b` |
| 核查页浏览器预览 | `node .artifacts/issue174/checklist-preview.mjs` | 7 项均未勾选，0 页面错误，无横向溢出 | `20261013T030802Z-e7d92ad1` |

环境：Windows、Python 3.11.15、Node 24.20.0、pnpm 11.28.4、Playwright 1.62.0，使用已有 Chromium 和 FFmpeg 8.1.1。Node 按本分支锁文件安装并通过 postinstall 构建。独立 Python 仅安装本分支基础依赖，没有 qwen_asr / torch。构建 fresh 与类型检查是本次结果，旧开发记录中的 TS2339 不作为当前阻塞。

Launcher 实测像素：groupGap=10、hintMargin=10、hintGap=83、anchorsGap=10、controlsGap=20、outputGap=10、checkGap=20。hintGap 包含中间输出目录行，应结合其它测量读取。既有 4 项浏览器测试还断言输入检查结果与上方按钮距离 ≥8px。截图已自查，未改变产品布局。补充截图与数值在 `.artifacts/issue174/`；既有 spec 截图在 `test-results/`，均不提交。

环境 / 探针失败也保留：

- 首次将 `pnpm exec ...` 直接交给 run_check，Windows PowerShell shim 无法由 subprocess 启动，exit 127；run-id `20261013T025820Z-1ef42473`。改用 Node CLI 后同组用例通过，没有产品修改。
- 补充 round-trip 探针首次在 actual 映射中遗漏 id，而 expected 含已有 id，导致断言失败；run-id `20261013T030220Z-6b7f0f30`。核对两个小数组确认文字与时间码相同，修正探针字段后通过。不是产品缺陷。
- 文档结构检查失败项为 `docs/logs/agent-e2e-pitfalls-261011.md` 未登记日志导航。它由基线 a34d502a 新增，基线与当前结构错误完全一致；本次未改该日志或补写无关入口。后续文档维护登记该历史日志后可恢复整仓绿灯；本次报告的入口与链接检查没有新增问题。
- 普通沙箱访问独立 worktree 的解释器和 CIM 被拒绝，授权工具权限后执行；不是运行时缺陷。GitHub gh API 出口 403 限流，以已连接 GitHub API 核实 Issue 和登录身份。
- 测试 Server 由仓库 Windows Job 所有权管理器停止；没有为本任务保留常驻服务。实际模型、真实 GUI 联跑、发行包、远端 CI、完整浏览器套件及真人拖动 / 播放 / Seek 听审均未验证。

## 人工验收与 Issue 收尾建议

本机核查 JSON / HTML 使用 `tools/verification-checklist/build.py` 生成，放在 `.artifacts/issue174/checklist.json` 与 `verification.html`，不入库。所有人工勾选初始为空；自动化通过不转换为人工确认。

1. 准备已有本地 ForcedAligner 和一份获准干净短录音，文稿每个非空行对应预期 cue；先输入检查，再生成 MOSP / SRT。记录设备、模型版本、素材时长、冷启动与推理耗时。确认没有调用 ASR，逐句试听起止和字词码。
2. 对 >10min 干净念稿，先检查自动语音区间与行对应；保存诊断 anchors，重点听审第一 / 最后一行及每块前后两行。记录预期停顿、实际时间与漂移，而非只检查输出文字完整。
3. 用获准有口误 / 重复 / 跳行的录音，观察是否给出区间错配或边界诊断；能生成也必须听审。出现错误时先整理媒体 / 人工锚点，需识别真实内容时走 ASR 后口播对齐。
4. 对人工锚点组逐一确认首末行和源时间，验证其无重叠、每组 ≤300s；打开工程、试听、导出、保存并重开。
5. 将核查页未确认项与备注导出，形成实际模型质量证据后再决定 Issue 状态。

建议收尾说明（草稿，仅供维护者使用）：核心入口与短单发 / 长静音锚点策略已实现，本次定向契约和浏览器回读通过；真实短、长及脏录音质量验收仍需模型与获准素材，因此保留 Issue 或把质量验收另列明确待办。不要用合成结果宣称真人长录音无漂移，也不承诺 10–100 倍性能。

