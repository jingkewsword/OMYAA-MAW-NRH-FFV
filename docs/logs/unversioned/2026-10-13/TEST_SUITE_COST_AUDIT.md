# MAW 测试成本分析记录

日期：2026-10-13。状态：分析完成。范围：分析、测量、文档；生产源码、测试与 CI 未修改。下文阶段记录保留当时的测量范围；最终结论以本节概要与收束结论为准。

## 先看结论

| 问题 | 最有依据的定位 | 优先处置 |
| --- | --- | --- |
| 反馈时间 | 两条生命周期 hang 真实等待 45/30 秒，占 Node CI 关键路径约 88% | 保留进程树、端口和旁观进程断言，注入短测试期限 |
| 资源 | 30 分钟 tone30 单例独立 21.47 秒、树 RSS 1832.63MiB；全量峰值约 2.04GiB | 固定 cache 解析和短真实生成常驻，长媒体验收显式分层，消除重复生成 |
| HTTP 成本 | 相同 104 例 0.5/0.01 秒 poll 对照均通过，suite 58.52/29.73 秒 | 优化夹具，保留真实 token/path/Range 边界；单次收益需 CI 确认 |
| 低价值断言 | 等价变量重命名让静态断言红，真实分类故障却让它绿；331 条行为测试正确响应 | 退出实现形态断言，按独立风险补/保留行为保障 |
| 并发 | 相同 624 个 Node 用例 default/c4 为 13.94/19.85 秒，RSS 1151/1141MiB | 不采用“并发降低一定更快更省”的假设 |

长期机制见[测试治理方案](../../../plans/TEST_SUITE_GOVERNANCE.md)：新增用例证明独立风险、选择最便宜的有效层；成本预算约束反馈链，退役需要故障检出对照。不是以数量、覆盖率百分比或“全部绿”代替质量。

## 基线与证据规则

- 当前上游 main：`a34d502a33cfe9fcff0288c13b04f6bba3ca48fa`，独立副本基于此提交。
- 旧本地目录的 `7514f18` 与正式本地基线的 `e107c63` 均不是本次当前版本依据。
- CI 时间来自 GitHub job / step 的 started_at 和 completed_at；它不包含内存数据。
- 本机测量必须分别记录墙钟、CPU、进程树内存与通过 / 失败 / 跳过，环境缺失不能当作性能改善。
- 消融只在隔离副本实施；测试绿灯不能单独证明可删除。

## 已取得的 CI 线索

在 2026-10-12 与 2026-10-13 的两次 Editor 构建中，`pnpm run test:unit` 均耗时 86 秒；真实 file / HTTP Editor 检查分别 14 和 13 秒。Windows Preview 的全量 Python 测试在 2026-10-12 为 83 秒，PyInstaller 构建为 30 秒。需要进一步定位单测为何比浏览器启动路径更慢。

来源：[当前 Editor CI](https://github.com/Moyf/moys-asr-workflow/actions/runs/38335333550)、[前一次 Editor CI](https://github.com/Moyf/moys-asr-workflow/actions/runs/38255804653)、[Windows Preview](https://github.com/Moyf/moys-asr-workflow/actions/runs/38255804690)。

## 待核实事项

- 全量 Python 成本是否集中在 HTTP 服务器 shutdown / 重复模板装配。
- Node `tests/*.mjs` 包含多少真实浏览器 / 子进程生命周期测试，是否存在固定延时。
- E2E 全量不等于 CI 的单个 bundle 启动 spec；不得用后者时间估计前者。
- 静态源码成员断言是否重复行为测试；架构依赖守卫是否具有独立价值。

对应方案：[测试长期治理](../../../plans/TEST_SUITE_GOVERNANCE.md)。

## 阶段结论一：Node 最大耗时来自真实启动期限

从当前 Editor CI 的 TAP 日志提取：646 个测试全部通过、零跳过，测试总时间 85.94 秒。`test_e2e_process_lifecycle.mjs` 的 `scroll: hang` 为 45.713 秒，`helpers: hang` 为 30.103 秒，两条在同一文件串行运行，合计 75.816 秒，是整套关键路径的约 88.2%。不能将其与其他并行文件的时间直接相加估计 suite 总时间。

源码对应：scroll fixture 启动期限 45000ms，helpers 的期限 30000ms。用例真的等到期限再断言子孙进程被回收、端口释放、旁观进程仍活着。这些边界值得保留；等待生产完整期限不是独立的保障。下一步在隔离实验中缩短期限，并比较断言、故障检出与时间。

两次 Windows Preview 的全量 Python 步骤分别为 75 秒与 83 秒，打包 34 秒与 30 秒。packaging contract 已单独运行 2 秒，又在全量 discovery 中包含一次；存在明确重复，但它不是最大热点。全量 E2E 不在当前这条 CI 中执行；其成本不能由 13 秒的选定 spec 推算。

## 阶段结论二：源码断言要与实际行为分开

`test_editor_assets.py` 中存在明确的实现耦合候选：固定完整 188 项清单、`z-index: 490`、`GAP_DISPLAY_PROJECTION_CACHE`、特定函数声明和代码表达式。它们能在重命名或等价实现后报错，却不一定发现运行行为坏掉。`test_editor_utils.mjs` 已直接执行 gap provenance 的恢复、清除、移动和组合行为；是否可完全替代静态检查还需实验。

不能由此推导“所有源码测试都无用”：manifest 路径逃逸、重复或缺失模块、依赖顺序、装配后的 TDZ / hoisting、冻结运行不得调用 Node 构建、跨语言默认值一致，都对应真实外部契约或尚存的 classic 共享作用域风险，应保留有效保障。

## 本机测量状态

规模：92 个 Python 文件、38 个顶层 Node 文件、70 个 E2E spec；非空行分别 40862、11882、26507。这些是文件与文本规模，不是风险覆盖率。

第一轮本机 Python 全量测量在外层 240 秒期限处终止（实际 241.06 秒、exit 124）。该轮前置静态清单提取有明显工具开销，且逐例计时只在完成后写入，因此不能把 241 秒解释为 suite 的纯耗时。已改为低成本提取与逐例落盘；后续定位采用分文件测量，并保留未完成状态，禁止把缺失结果当通过。

Node 完整 Windows 套件在 180 秒限时处未完成（181.02 秒、exit 124）；Linux CI 的 85.94 秒不能直接当成本机预期。Windows 单例的额外成本包含 PowerShell Job supervisor 启动/编译与子进程启动，具体各自占比尚未隔离。随后一次按名称过滤的实验未正确排除生命周期场景，已提前停止，不使用它比较同集合性能。

明确排除 `test_e2e_process_lifecycle.mjs` 后，其余 37 个 Node 文件、624 个用例全部通过、零跳过：

| 条件 | 测量命令墙钟 | Node 报告 suite 时间 | 采样树 RSS 峰值 | 观察 CPU | 最大进程数 |
| --- | --- | --- | --- | --- | --- |
| 默认并发（16 logical CPU 的本机） | 13.94s | 13.52s | 1151.47MiB | 55.08s | 20 |
| 显式 concurrency=4，相同集合 | 19.85s | 19.29s | 1141.00MiB | 57.16s | 17 |

初步判断：把并发从默认改成 4 在这次样本中变慢约 42%，树 RSS 只降约 0.9%。不能据“并发多”就宣布改成 4 会解决资源占用；下一步需看浏览器与大 fixture 的峰值组成。RSS 为 100ms 目标间隔的进程树采样总和，共享页可能重复统计、短进程可能漏采；不是独占物理内存，也不是整机内存占用。采样开销与 Python wrapper 启动在命令墙钟内。此消融用于归因，不建议删掉 22 个进程边界场景。

## 阶段结论三：Python 的本机等待与夹具成本

优化采集器后的逐例测量已经定位一个容易误判的本机热点：`test_ffmpeg` 的 10 个优先级测试合计 25.29 秒，当前 Python 进程 CPU 合计仅 0.20 秒。源码没有在这些用例里执行真实 FFmpeg，而是创建多个假 `ffmpeg.exe` / `ffprobe.exe` 文件、解析路径与清理临时目录。因此它主要不是解码或算法成本；这些读写/路径调用在本机很慢。不能仅凭此推断是 Defender，未做系统追踪，也未改变系统设置。

这些用例对应用户显式配置优先、工具分别回退、bundle / Homebrew / PATH 优先级与严格模式等独立行为，应保留。优化候选是把优先级组合降到可控文件系统夹具，保留少量真实文件路径与平台扩展名集成检查，而不是删掉优先级保障。

当前另一热点是 `test_docs_check`：19 例合计 16.40 秒，其中严格模式一个方法 11.19 秒；它为多个组合重复启动检查器/fixture Git。此处适合让大部分语义通过函数调用证明，保留 CLI 退出码、Unicode 路径和真实 Git 枚举的代表性场景。完整 Python 结果尚未结束，上述排名仅对应已完成部分。

## 用例价值与处置候选（不是已删除清单）

| 具体位置 / 断言 | 价值判断 | 建议动作与替代保障 |
| --- | --- | --- |
| e2e_process_lifecycle：scroll / helpers 的 hang | 独立的失活超时清理边界，必须有 | 注入短启动期限，保持同一真实进程树、端口释放和旁观进程断言；生产默认另用一个廉价参数契约检查 |
| e2e_process_lifecycle：owner exit / exception / signal / hold | OS 所有权的不同路径；信号与内核回收不能由 mock 证明 | 保留公共 supervisor 的退出/强杀边界；两个 wrapper 的全笛卡尔矩阵可按共享路径收束，但须证明 wrapper 自己的 ready/error/timeout 接线 |
| local_editor_server：HTTP token、bound media、path escape、Range、下载 | 外部边界与真实传输语义 | 保留；先降低 fixture poll 间隔，再把纯输入组合下沉，不共享可变项目跨用例状态 |
| gap_removed_media_jobs：cancel / committing / progress / timeout / descendants | 会丢产物或留进程的状态机和提交竞态 | 保留；事件驱动等待；能纯状态机证明的组合不重复启动真实进程 |
| gap_removed_audio_export：AAC/MP3 非包边界完整解码对照、float/高位深 | FFmpeg 真行为可能与 mock 完全不同 | 保留代表性真实编解码；组合矩阵做算法层，真实编解码在相关媒体改动与发布运行；不能因慢删除 |
| test_ffmpeg：显式配置、环境、bundle、Homebrew、PATH、严格模式 | 产品找不到工具或找到错误工具的真实规则 | 保留优先级组合；可控 FS fixture + 少量真文件集成，优化本机假 exe 创建/删除成本 |
| docs_check：同一严格模式方法反复 CLI/Git | 默认/strict/历史例外语义有价值，重复进程不是独立风险 | 语义组合下沉函数层，CLI/Git/退出码保留代表案例 |
| editor_assets.test_editor_script_manifest_is_ordered_and_complete | 全清单精确相等固定了文件布局；混入独立依赖顺序风险 | 退出 188 项完整 tuple；保留缺失/重复/路径安全、必要的相对顺序、真实 bundle 启动 |
| editor_assets.test_hint_stack_stays_above_floating_surfaces | `z-index: 490` 仅证明数字存在，不证明没被父 stacking context 遮挡 | 改成共享的 owner promotion / hit-test 行为与一个代表性遮挡场景；已有相同行为保障时删除字面量断言 |
| editor_assets.test_gap_core_exposes_restore_and_clear_semantics | 函数名/缓存变量名/`underlying` 不出现；函数存在不证明 restore / clear 正确 | 优先退出实现形态断言；保留 editor_utils 的恢复、清除、移动及 provenance 往返行为 |
| editor_assets.test_waveform_gap_display_type_uses_shared_core_and_subtle_protected_style | 函数名/表达式与 CSS 字符串，不能证明来源分类正确 | 来源分类在算法层；保护样式与交互在代表性浏览器场景验证 |
| editor_assets：overall_gap_move / shrink_gaps 的 section.index + 代码片段 | 等价提取/重命名会失败，错误函数体可能仍保留 needle | 保留“移动不改变来源、收缩不引入 manual override”的行为；删除实现片段前核对 UI 调用接线 |
| editor_assets：checkpointed_import 的多个 function needle | 检查保存安全的目标有价值，但仅检查声明存在 | 用 import / checkpoint / cancel / save 行为替代；已有 open/new-project 真场景不能自动覆盖所有失败分支 |
| editor_manifest：symlink escape、空/重复/缺失、frozen 禁止 source build | 路径和分发边界，明确独立价值 | 保留；路径分布组合可共享表格 fixture |
| editor_bundle：hoisting、TDZ、write、registration slot、stale artifact、遗漏/unsafe paths | 混合 classic/ESM 语义真实，不能只让 tsc 或 happy-path 启动替代 | 保留，合并重复解析/装配 fixture |
| punctuation_defaults_contract | 当前多入口保留独立默认常量，防静默漂移 | 保留跨入口一致性目标；可改为读取 parser 实际默认值，减少源码拼写依赖 |
| launcher_contract：browser mock 与 backend configuration keys / types | 浏览器预览和真实 bridge 容易漂移的跨语言协议 | 保留；不能当作单纯 mock 验证删除 |
| test_type_gate：自造 fixture 的 TS2322 canary | 证明工具能报类型错，不能证明项目 tsconfig 含所有业务模块 | 工具链/类型配置变更时运行，常驻重点改为真实项目类型门；低成本，非首要性能削减项 |
| compact_assertions_usage 与 scanner 自测 | 有界失败输出是实际运行安全；scanner 还限制测试写法 | 保留 runner 的长行/退出码/超时回收；scanner 是否常驻可再议，当前 AGENTS 明确要求，需联动修改约定后才能退役 |
| refactor_layout_tools / ns_rewrite_scope | 重构工具正确性；其中“旧 mutation CLI 拒绝 sliced layout”保护源码不被误写 | 仅工具/迁移修改触发；工具存续时保留拒绝误写测试，工具退役时再一起退役 |
| cue-list-action-buttons-layout 等窄屏几何 | 文字裁切/可点击/间隔是 DESIGN 与用户体验契约 | 浏览器层有独立价值；按 toolbar / settings / launcher 共享场景合并启动，不仅因为 CSS 数字就删除 |
| word-timing / split-desynced-items / Unicode | 非 BMP、时间边界、不冒充精确词级时间 | 算法层保留组合；浏览器保留真实选择/拖动/撤销接线 |
| editor-transactions、playhead/subtitle-seek-race、waveform-history | 真 DOM 事件与媒体异步/预览取消、dirty/undo/redo | 保留核心场景；稳定算法的等价组合下沉，不能被纯 VM 单测完全代替 |
| packaging_contract 单跑 + Python discovery | 同一个集合重复执行 | 同一环境删除一次重复执行；成本仅约 2 秒，不夸大收益 |

判定“为测而测”以断言为单位。一个文件可以同时含应保留的路径契约、低价值函数名断言和真实行为回归，不能按文件标题整批删掉。

## 阶段结论四：30 分钟信号才是已观察到的最大内存卡点

优化后的 Python 全量测量在 300 秒期限处终止（300.97 秒、exit 124）。1886 条已完成用例的逐例记录保留，停在 `GeneratedFixtureTests.test_tone30_generated_matches_fixture` 的夹具生成/内核生成阶段，不能把它标记通过。

`tests/test_data/gen_fixtures.py:gen_tone30` 的注释明确是 30 **分钟**，`n = 44100 * 1800 = 79,380,000`，仅 `np.zeros(n, dtype=float64)` 就是 635,040,000 字节（约 605.62MiB）。tone 构造、FFT 粉噪声、round/clip/astype 与 tobytes 存在多个临时数组，随后写约 151MiB 的 PCM 再走真实生成。观察到进程树峰值 2087.68MiB。全量这一峰值尚未按单例隔离，正在单测量该例，不据峰值时序宣称排除了其他内存来源。

另外 `FixtureReapeaksTests.setUpClass` 会生成缺失的源 WAV；`GeneratedFixtureTests._compare_reapeaks` 还会再生成一次同名 WAV。大媒体构造在同一全量运行里存在重复。

边界拆分建议：固定 REAPER cache 的解析/层布局/双声道/采样率放快回归；生成兼容性使用短音频；缓存指纹用短真实 WAV；30 分钟长度留为明确的长媒体验收/性能场景，运行环境、退出条件和触发范围可见。不能把整份 reapeaks_fixture 删掉，真实跨语言兼容的独立风险仍需保留。

单独运行上述长媒体生成用例已通过，零跳过。用例墙钟 21.47 秒、测试进程 CPU 45.34 秒；含采样 wrapper 的命令墙钟 23.29 秒，观察进程树 CPU 48.02 秒，树 RSS 峰值 **1832.63MiB**。峰值时测试 Python 本身为 **1822.98MiB**，第二个 Python 启动层为 9.64MiB，因此已可把约 1.8GiB 的资源热点归到这个用例，而不是 Chromium 或其他并行文件。

当前 Windows CI 的完整 discovery 实际为 2182 例、72.714 秒、**跳过 67 例**。CI 基础环境没有 NumPy，且相关真实 FFmpeg 场景也受工具可用性条件控制；67 不全是同一原因，不把它们都归到 NumPy。源码显示上面的长媒体生成同时需要 NumPy 和 FFmpeg；单纯 CI 绿灯未证明它执行过。应把 required / optional / unavailable 的验证范围显式报告，避免“全量”名义掩盖依赖驱动的跳过。

长媒体的价值还包括粗分辨率 mip 层级，短音频不能自动证明所有长媒体层级等价。迁移到短回归之前，明确保留哪些粗层级的冻结 cache 解析与合成边界；真实 30 分钟生成在内核/容器/长媒体相关变更和发布验收中显式运行。本文不以一次样本推导 p95 或稳定资源上限。

## 消融实验：实现形态不等于行为保障

仅在审计进程读取源码时替换，生产源码、测试、bundle 未改写：

| 实验 | editor_assets 的 2 条相关静态断言 | editor_utils 的 331 条行为测试 | 推论 |
| --- | --- | --- | --- |
| `GAP_DISPLAY_PROJECTION_CACHE` 等价重命名为 `gapDisplayProjectionCache` | 1 失败（只找不到变量名），1 通过 | 331 通过，0 跳过 | 至少该变量名断言阻碍等价重构，未提供独立行为保障 |
| `getGapRemoveDisplayType` 函数入口直接 `return "unknown"`，保留名称/其余文本 | 2 通过 | 329 通过、2 失败，0 跳过 | 存在明显行为故障时源码 needle 仍绿，真实来源分类断言检出了故障 |

故障由 `keeps display provenance metadata while presenting one merged gap` 与 `classifies common and legacy-migrated gap display types` 检出。这里支持退出两个用例中的特定实现形态断言，不证明 editor_assets 整个文件都可删除，也不是对全风险集合的穷尽 mutation score。

## 消融实验：缩短等待，保留进程边界

临时 Node loader 把 Windows readiness 的 45/30 秒期限都缩为 10 秒，保留真实进程树场景与原断言。两个 hang 用例均通过、零跳过，分别为 11.78 与 11.04 秒，总 suite 为 23.23 秒，命令墙钟 23.55 秒、树 RSS 峰值 453.22MiB。原默认等待在 Linux CI 对应 45.71/30.10 秒；这里平台不同，不将其直接计算成同机百分比收益。源码层面的被消除固定等待为 55 秒。

前次相对 loader 路径在合成工作目录中无法加载，修正为绝对 file URL 后才取得上述有效结果；路径失败未计入实验收益。生产默认期限和其他 20 条生命周期路径未被该实验覆盖，实施时还需保持默认值与其他回收路径。

## 完整性核对与尚未验证范围

Python 全量在单进程 300 秒期限处未完成；随后只补未完成部分与单例，不重复整套。按 discovery 的实际用例 ID 核对，**2188 个 ID 全部对应到了完成记录**，2166 通过、22 跳过，无额外或缺失 ID；不是“一次完整套件通过”。一次单文件导入缺少 discovery 隐式加入的 tests 路径，已在审计采集器中补齐相同导入上下文，14 条 verification checklist 用例通过，最初 import error 不作为业务失败或性能收益。

本机与 CI 的 2188 / 2182 计数不同；class setup 的跳过以及环境条件会影响 unittest 的实际计数，不用数量差异推断漏了 6 个功能。当前本机 skips 也意味着对应边界未执行。census 导入阶段出现一次 subprocess 读流 UTF-8 解码线程警告，census 仍正确产出 ID；未调查该环境读流问题，不将它解释为产品错误。

E2E 仅运行 `--list`：**794 例 / 70 文件**。完整交互与媒体场景没有全部执行，本文关于这些文件的处置属于源码/设计分析和候选；不会拿 624 个 Node 测试或两个 hang 场景冒充浏览器 E2E 全量保障。

docs 检查结果：0 新断链、14 个登记历史断链，但还有 1 个结构错误，`docs/logs/agent-e2e-pitfalls-261011.md` 未进日志导航。该文件在本次 HEAD 原已跟踪，HEAD 的日志索引没有对应入口；是当前基线已有问题，本次两份文档登记没有制造新断链。不为使审计绿灯而修改无关历史日志。

## 消融实验：HTTP 夹具轮询

只在审计进程内把 HTTPServer.serve_forever 的测试轮询从 0.5 秒改为 0.01 秒，不修改服务器生产默认、不移除请求/断言、不跨例共享项目。对相同 104 例（local_editor_server 91 + server_align 13）做独立集合对照：

| 条件 | suite 总时间（含载入） | 用例体合计 | 观察进程树 CPU | 树 RSS 峰值 | 结果 |
| --- | --- | --- | --- | --- | --- |
| 原 0.5 秒 | 58.52s | 57.95s | 38.23s | 188.51MiB | 104 通过、0 跳过 |
| 测试夹具 0.01 秒 | 29.73s | 28.87s | 26.83s | 198.81MiB | 104 通过、0 跳过 |

这组单次 A/B 的总时间下降约 49.2%，但 CPU 也变化，存在缓存/系统负载/执行上下文差异；不能把全部收益归因于 poll，也不是稳定百分比承诺。两轮都是同一集合且所有断言通过，支持实施测试夹具参数优化，再在 CI 中确认。35 个真实 server 启动的 shutdown 等待是明确的成本来源；不能为了快把真实 HTTP/token/path/Range 测试全换成 mock。

## 收束结论

1. **最大明确等待卡点**：Node 生命周期文件的 45/30 秒真实期限，两条占 Linux CI 85.94 秒关键路径的约 88%；保留回收边界、缩短测试期限。
2. **最大已定位资源卡点**：30 分钟 tone30 的完整信号构造与生成兼容性单例，独立 21.47 秒、约 1.8GiB 树 RSS；拆分短回归与显式长媒体验收，先消除重复生成。
3. **Python 的持续反馈热点**：HTTP 集合、假 exe / 路径 fixture、重复 CLI/Git 子进程；优化夹具/执行层优先于删除保障。
4. **最值得退役的断言**：固定变量名、函数声明、整个文件布局、特定表达式/数字的源码 needle，已用等价重命名误报与真实分类故障漏报演示。删除粒度是断言，不能把混合文件整批撤掉。
5. **必须守住**：字幕真源、整数毫秒与 Unicode、多轨/undo/redo/取消事务、保存/导出结果、本机路径和令牌、进程所有权、真实媒体布局、bundle 语义与公开入口。性能慢并不使这些保障失去价值。

本次仅新增计划与证据文档并登记索引；审计采集器、loader、故障注入和原始日志在忽略的 `.artifacts/audit/`。报告中的 expected failures 来自进程内故障注入，不代表当前生产测试失败。长期方案状态为分析完成、方案待讨论，未批准实施。生产测试、源代码和 CI 均未修改。

## 后续：开发必跑与合并执行推荐

用户进一步要求区分开发必跑、按改动跑、合并时跑。已经在[治理方案的测试分层章节](../../../plans/TEST_SUITE_GOVERNANCE.md#测试分层与触发)补齐具体文件与风险族映射、条件性重门禁、发布与过渡策略；推荐尚未改写 runner/CI。

为推荐的小核心补充实测（同一基线）：

| 核心 | 现有用例 | 结果 | 外层命令时间 | 测试器内部时间 |
| --- | --- | --- | --- | --- |
| Python 工程契约/写入/备份 | project_contract + project_io + project_backups，共 65 例 | 65 通过、0 跳过 | 1.31s | 0.076s |
| 编辑器状态/事务/host/历史 | editor_runtime + editor_state + editor_commands + editor_host + editor_history_gestures，共 33 例 | 33 通过、0 跳过 | 1.58s | 1.119s |

约 2.9 秒不包含构建、typecheck 和叶子功能的影响回归，不把 98 条核心冒充完整产品覆盖。证据目录为 `.artifacts/checks/20261013T034910Z-81872dbb/` 与 `.artifacts/checks/20261013T034912Z-b123164e/`，均有原始输出和 result.json。

核心结论：常驻快核心服务开发反馈；合并时全部便宜的算法/契约避免跨模块漏选；实际主流程用少量真实浏览器证明；命中进程/媒体/容器/打包等边界时，重验证是该 PR 的 required 门禁，不能一律推迟到发布。普通 docs/网站/独立工具不套用完整应用流程。

更新 docs 后 check_docs 再次得到 0 新断链，仍仅有基线的未登记日志结构错误；diff --check 通过。

## 讨论分支保存

维护者要求将本次测试梳理保存为独立分支，并把推荐测试规则放入 plan，待后续讨论通过再升级流程。已建立 `docs/test-suite-governance-20261013`，基于本次固定审计提交。当前 fork/main 与 upstream/main 的实时引用均仍为该基线。

分支内容限定为本计划、审计记录、主题索引与日志索引；不提交 `.artifacts/`、测试音频、依赖环境、采集器或本地输出。计划已明确标记“待讨论，未批准实施”，并列出讨论事项及通过后的实施/验收/规则升级路径。
