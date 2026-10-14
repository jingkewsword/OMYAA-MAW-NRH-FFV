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


## 第一阶段开发发现与结论（2026-10-13）

维护者随后授权按 plan 在同一分支实施，一个 Sol 子代理负责媒体/HTTP 夹具。因额度接近触底，维护者要求先整理提交；以下记录是阶段验收，不表示完整集合或远端 CI 已成功。现行入口见[测试分层](../../../INDEX.md#engineering-test-workflow)，剩余验收见[计划](../../../plans/TEST_SUITE_GOVERNANCE.md)。

1. **冻结 cache 解析无需生成源媒体。** 原读取测试只需现存文件 stat 与 cache 内容；它们现为 6 个独立 frozen cases，缺 NumPy/FFmpeg 的 probe 仍 6/6 通过。全部原 `self.assert*` 表达式保留，另外检查 30 分钟 cache 的 8 个 wave/spectral/loudness mip header。短生成 2 例、长生成 1 例独立；生成器输出指向私有临时目录，不改写提交中的 cache 或维护者已有 WAV。长例只合成一次 tone30，17.636s；仍保留约 1.8GiB 的真实长生成成本，没有声称内核内存降低。
2. **HTTP 空等可直接消除。** 6 个文件的 37 处启动线程仅增加 `poll_interval=0.01`；去掉该参数后的 AST 与原文件一致。154 个 HTTP/媒体/取消/SSE/探活用例通过、无 skip。相同 102 例单次 A/B：57.648s → 39.953s，减少 30.7%；CPU 36.109s → 35.641s，RSS 187.523 → 192.582MiB。没有证明 p95 或内存改善。审计原 104 例含额外 2 个 bind-only 测试，本次 A/B 不包含它们，不混用分母。
3. **失活期限不是业务边界。** 真实 helper 的 30s/45s 默认仍保留，合成进程矩阵显式注入 Windows 10s / POSIX 1.5s。Windows 生命周期组 30/30、无 skip，71.81s；其中仍含所有 22 个进程树/端口/旁观进程保护场景。Linux/macOS 尚未在本机验证，不把 Windows 结果外推。
4. **required skip 揭露了缺依赖。** 首轮 common 无业务失败，却有 11 个 energy-valley skip。实际是 NumPy 与 soundfile 一起导入，提示文本只写 NumPy。补 soundfile 后全部执行；test 组为 NumPy/Pillow/soundfile，dev 组提供 ruff，不引入 ASR 模型。锁文件仍为原 185 个 package name/version，uv 更新了锁格式与解析元数据；`uv lock --check` 通过。
5. **分组避免维护精细映射的膨胀。** cheap Python/Node 常驻，只有昂贵边界按类/方法或文件分流；全发现集合与 pack 并集一致、无重复。新用例默认 common。叶子浏览器改动选择消费者族，共享 schema/state/host/history/boot/布局、测试基础设施和未知改动扩大。纯 docs/网站/工具各走对应入口。required 依赖/编码器/fixture skip、Node/Playwright skip 和 timeout 阻断；明确的 OS 不适用项保留原因。
6. **只退役有替代证明的实现形态。** 删除完整 188 项清单快照和 gap core 函数/缓存变量命名集合这两个方法；依赖装配、路径逃逸、冻结无 Node、持久化/格式、安全和 CSS 混合契约保留。原审计的命名等价/显示错误故障注入证明区分能力，当前全体 Node common 行为集通过；本轮没有把剩余混合静态文件整批删除。
7. **复用构建也要验证新鲜度。** test workflow 每批构建 editor/Launcher 一次；CI install 禁用重复 postinstall。Windows `-PreparedEnvironment`、AppImage `--prepared-environment` 在复用前执行两个 bundle `--check`；缺失/过期会失败。独立手动打包仍准备并构建。PowerShell 对依赖、freezer、测试与 PyInstaller 非零退出显式失败。实际 PyInstaller/AppImage 产物尚未验证。

| 已执行集合 | 结果 | 范围说明 |
| --- | --- | --- |
| 开发核心 | Python 65、Node 33 通过 | 两项子命令 0.66s / 1.58s |
| Python common | 2017 运行，0 失败/错误，4 平台不适用 | 3 Windows symlink 权限 + 1 非 Windows opener；131.86s 是该次环境测量，不当作稳定预算 |
| Python media / long-media | 66 / 2 通过、无 skip | 44.42s / 22.75s |
| Node common / browser / tools | 584 / 5 / 27 用例，无 skip/失败 | JUnit 结果已验证；browser 使用真实 Chromium |
| HTTP/browser smoke | 13 通过 | 两个真实 server/文件事务 specs，24.23s 外层 |
| Python tools | 101 运行，0 失败/错误 | Unix checksum 的 Windows 不适用单独记录；首轮 Pages 构建断言失败修复后复验通过 |
| lint / workflow / 文档 | ruff、actionlint v1.7.12、YAML/表达式、锁一致性、文档结构与归档通过 | actionlint 本机没有启用 ShellCheck/Pyflakes；打包脚本另做 PowerShell parse/Bash -n |
| 完整 Chromium | **未完成** | 794 例，停止前进度标记 317/794；外层 489.36s，按维护者要求终止自身进程树，退出 1 来自主动终止，不作为业务失败 |

完整浏览器运行尚未形成最终 Playwright 统计，因此进度标记既不是通过数，也不是完成数。这个运行再次说明：全量浏览器不适合每次开发调用。当前 900s 完整门禁是否适合 Linux CI 仍需实测；若不足，应先按 spec 分片并汇总所有片的 required 结果，不能放宽为“部分通过即可”。本轮未实现该分片方案，也没有绕过完整验收。

后续顺序：先恢复完整 Chromium/CI 验收并校准分片和预算，再跑 Linux/macOS 进程与媒体/实际打包；核对 GitHub 保护规则，将汇总 `Required test gate` 设为 required。此阶段 CI 配置只是已提交的实现，不能冒充实际远端结果。

原始证据位于 `.artifacts/fixture-refactor/summary.json`、`.artifacts/test-workflow/3e125ce66216/`、`9092281d980b/` 与 `7f5f2c56cb70/user-stop.json`；第一次缺 soundfile 和第二次 Pages 断言失败均保留。完整日志只定向读取，阶段导出不提交媒体、venv、bundle 或个人绝对路径。

## 第二阶段开发发现与阶段保存（2026-10-13）

接续基线 `0735166b3206d53259053b5d69388d6871420082`，维护者授权继续推进，随后要求阶段性提交、推送与本地 docs 更新。实施前预期已写入[计划](../../../plans/TEST_SUITE_GOVERNANCE.md#第二阶段预期与验收)。一个 Sol 子代理只读审查入口与 CI；主代理集成修复并核验实际文件和结果。

本阶段没有再删除产品行为测试。重点是完整浏览器预算及测试结果可信度：测试组织如果能把“没执行”变成绿灯，增加数量也无法守住产品边界。

| 发现 / 预期 | 实际改动与结果 | 未完成边界 |
| --- | --- | --- |
| 完整 Chromium 超出开发反馈预算 | 新增可复用四片 CI，独立机器各 2 workers、900s，保留文件隔离。实际 Playwright 全集 794 例，四片 200/198/217/179，集合无重无漏 | 只验证发现与分配，未执行真实四片；没有证明墙钟、CPU 或 RSS 改善 |
| 部分执行可能被当作完整成功 | 完整发现 → 分片计划 → 实际 JSON 检查 → 同 SHA / 配置 / 范围的四片汇总；缺片、重复、失败、skip、retry、空完整集和脏 scope 故障注入均被拒绝 | 小型真实 Playwright fixture 验证 CLI 语义，未代替 794 例真实浏览器运行 |
| 聚焦与未执行报告假绿 | `--forbid-only` 同时用于发现与执行；运行必须每个计划 ID 实际成功一次；`--list` 的空 results 不算通过 | 保留拒绝 .only 的真实 CLI 回归；不放宽 retry 使失败消失 |
| 发布可能绕过质量失败 | 原 `!cancelled()` 条件只约束 Windows success；现显式要求 test-quality、browser-gates 和 Windows success，打包也先等待质量与浏览器汇总 | 发布条件契约通过，未创建 tag 或运行真实发布 |
| selector 缺失输出被当作 false | 汇总严格校验 11 个 flag，并拒绝失败、取消、意外 skip 的 required job | 远端 CI 和 branch protection 设置尚未验收 |
| 混合消费者漏选 | export / gap 族补 waveform-history，gap 另补 waveform-deletion；保留现有真实用户操作与导出断言 | 没有按每个便宜案例增加路径规则，后续新增未知路径仍保守扩大 |
| AST 无法看到动态 unittest | pack 加载后按实际 ID 分组；变更无法静态判断的模块时扩大 required 组。全发现集合归属与合成动态模块回归通过 | 动态发现不再静默省略；不引入新的永久 loader 框架 |
| 发布平台生命周期缺口 | Windows 与辅助平台发布校验补 lifecycle；Python required 同时拒绝 expected failure；Node required 拒绝空集 | Linux/macOS 真实进程树与实际发布产物未验证 |

最新针对性验证运行 63 项，全部通过、0 skip，内部 60.728s、外层 65.05s。涵盖 browser_results、test_workflow、run_tests_runner、packaging_contract 与 release_notes；不是 63 个真实浏览器旅程。小型 CLI fixture 只有四个纯断言，用来验证 Playwright 发现、文件分片、实际结果和 `.only` 拒绝。

证据路径：

- 63 项 required 回归：`.artifacts/checks/20261013T091912Z-a77fcb2e/result.json`。
- ruff：`.artifacts/checks/20261013T092021Z-0d4a3342/result.json`，通过。
- 三份工作流 actionlint：最新 `.artifacts/checks/20261013T092857Z-6271dffc/result.json`，通过；未启用 ShellCheck/Pyflakes。
- 文档：`.artifacts/checks/20261013T092901Z-14b6b880/result.json`，0 新断链、0 结构错误；14 个已登记历史断链保留。`git diff --check` 通过。
- 794 例发现与分片：`.artifacts/checks/20261013T091658Z-07a2128f/result.json`、`.artifacts/phase2/discovery/summary.json`，后者明确 `runtime_complete=false`；各片完整/分片发现 JSON 保留。

首轮 packaging/release 回归 `.artifacts/checks/20261013T091356Z-77a2ed10/` 有 22 个系统 Temp 权限错误，以及一个沿用旧发布条件文本的断言失败。22 个错误不能归因产品；改用仓库私有 Temp 与正常本机权限复验，旧条件断言改为必要准入契约，最终上述 63 项全通过。保留首轮结果，避免把环境失败隐藏或重复重建依赖。

阶段保存后接续顺序：在固定、干净的提交上执行代表性 Windows 分片；再取得远端四片和汇总实际结果，记录每片耗时与资源；完成 Linux/macOS 生命周期、媒体与实际打包。运行过程中不改变 HEAD，发现成功或单片成功都不能宣称全套通过。只有取得实际 CI 后才校准片数/时间预算；required 保护设置是仓库外配置，仍需独立确认。原第一阶段中“本轮未实现分片”描述的是当时状态，当前实现与验收以上表为准。

## 第三阶段真实分片验收（2026-10-14）

维护者授权继续同一分支，先 Windows 代表性分片，再远端四片与汇总，遇到失败修复；真实发布暂不执行。本轮独立检出原分支，保护其他工作树与共享 Git 状态。

固定、干净提交 `08ad65e1` 上，第 1/4 片覆盖 19 specs、200 例，包含 AI 清理、ASS 实际 Canvas/libass、列表布局/滚动、工程事务与语言。构建、typecheck、完整/分片发现通过；真实运行 327.56s，197 通过、3 失败、0 skip、0 flaky。结果 `.artifacts/test-workflow/a4a13539c6ad/`，外层 `.artifacts/checks/20261014T110434Z-d3785c02/result.json`。这是完整失败记录，不能合并定向通过数冒充干净分片成功；原分片服务进程已按本次路径确认回收。

| 失败 | 原因与修复 | 定向证据 |
| --- | --- | --- |
| 粗斜体字号动画的副轨右边界相差 4px | 初始验证 100px 字体探针的取整误差，4096px 探针使原场景通过，但完整复验出现分数缩放的新边界差异，不能作为最终修复。直接原因是行位图固定 2px guard 裁切了斜体字形的外伸笔画；最终恢复原字体比例和行高规则，按已有实际 inkPadding 测量扩大位图 | 原/新失败场景同时通过，最终完整 36 项真实 Canvas/libass 边界通过，3px 原阈值保留；Node 假测量器按真实字号返回指标，334 项行为/Canvas 与最终 3 项 raster 回归通过 |
| 英文表情包提示读取不到 title | 共享 tooltip 按既有契约转存为 data-title；改为验证真实提示属性，保留用户名称与引用来源断言 | 原表情包名称用例通过；不恢复重复的浏览器原生 title |
| 英文壳层仍含中文提示 | 动态音频按钮在语言事件后写回中文，设置跳转缺翻译；显式翻译动态文本，补齐提示字典，监听 data-title。扩大扫描后发现的导入和工程设置提示也补齐 | 6/7 定向首次通过，扩大扫描检出的两个缺口补齐后英文壳层单例通过；没有排除中文节点来使检查变绿 |

334 项 Node 回归：`.artifacts/checks/20261014T111350Z-01c0c2fe/result.json`；7 项定向浏览器首轮：`20261014T111353Z-21a63af2`（6 通过，1 个扩大扫描发现）；修复后壳层：`20261014T111514Z-9e843dd3`（1 通过）；typecheck：`20261014T111514Z-45085320`（通过）。完整修复分片和远端 CI 仍待执行。

用户 fork 的 Actions 已启用；本机 gh 可正常访问，main protection 返回 Branch not protected，rulesets 空。未修改保护设置。Windows 复验成功后在同一 fork 内建立 Draft PR 以取得四片与汇总证据，不向上游发 PR、不合并、不创建 tag/Release。

`8f9b75b` 干净分片复验 199 通过、1 失败、0 skip，真实执行 293.88s；`.artifacts/test-workflow/47a94b91c961/` 和 `.artifacts/checks/20261014T111655Z-d660fe4b/result.json` 保留失败。随后原比例加全 run 行高校正的完整 ASS 试验仍 35/36，记录 `20261014T112416Z-6757a538`，该方案也未采用。真实斜体 `actualBoundingBoxRight` 超出 advance 约 6px，而旧行位图只留 2px，符合被裁切的 4px 差异；按 inkPadding 扩大位图后，原/新两场景通过（`20261014T112818Z-dc028ad8`），完整 ASS 36/36、无 skip（`20261014T112915Z-d2e7506b`，137.97s）。最终 raster 3/3 和 typecheck 为 `20261014T112913Z-409a0cc3` / `20261014T112914Z-6fecbd27`。

最终固定、干净提交 `79833e2` 的完整 Windows 第 1/4 片 **200/200 通过、0 skip、0 unexpected、0 flaky**。构建、类型、完整/分片发现均成功；实际 Playwright 执行 279.81s，外层整个分片流程 287.8s。`browser-run.json` 明示 clean=true、完整范围 editor-e2e、planned_ids=passed_ids=200。证据 `.artifacts/test-workflow/22b18bd16c5b/`、`.artifacts/checks/20261014T113242Z-921fafa3/result.json` 和 `20261014T113250Z-b3ee902f/result.json`。下一提交仅记录该结果，未改变受检源码；远端四片按推送提交独立执行，不把单片当全套通过。

### 远端首轮与定向修复

正常推送 `fee114c`，在用户 fork 建立 [Draft PR #2](https://github.com/jingkewsword/OMYAA-MAW-NRH-FFV/pull/2)。[Editor run 38558144389](https://github.com/jingkewsword/OMYAA-MAW-NRH-FFV/actions/runs/38558144389) 四片分别196/200、190/198、214/217、176/179，共776/794、18失败，0 skip/flaky；缺少通过的片被汇总和 Required test gate 正确拒绝。文档、Ruff及Linux业务组全部通过；Windows lifecycle 20/30。Windows preview run 38558144361 构建、包装契约、EXE自动烟测成功，仅上传Actions artifact；未合并、创建tag或Release。原始失败报告下载到本轮忽略证据区。

| 风险族 | 发现与修复 | 实际定向证据 |
| --- | --- | --- |
| 入口迁移与前置条件 | 双语设置从旧wrapper转到现行双语页；AI整理从匹配checkbox迁到AI任务；普通匹配保留真实计算取消/重启；批量fixture补合成key，保存自定义提示原文而请求时trim；toolbar tooltip读取data-title；帮助与原窗并存后显式关闭原窗 | Windows首轮11/14后剩余3/3；Linux同14项全部通过，原用户操作、保存/undo/取消断言保留 |
| 文本查找焦点 | 打开后的50ms自动focus覆盖紧接着的Ctrl+F；改为显示窗口时同步聚焦，不增加sleep掩盖竞态 | 原快捷键/regex/替换旅程在Windows和Linux通过 |
| Windows监督环境 | scroll夹具把私有LOCALAPPDATA等同时给PowerShell控制器和应用， hosted环境下10个scroll场景未启动；控制器使用正常OS环境，C#显式把原隔离环境交给应用，Job所有权/默认期限不变 | 本机28项生命周期通过；新增父环境标记不得进入应用、LOCALAPPDATA必须私有的检查，scroll ready通过；远端仍需第二轮确认 |
| 非UTF控制台 | Windows job未设置UTF，失败输出的✖导致cp1252异常，summary未保存；入口像run_check一样显式UTF，Windows job与夹具也设置UTF | 模拟cp1252控制台的失败仍返回1、保存原诊断和summary；汇总/入口15项通过，无skip |
| 字体依赖 | Linux无本机Arial，@font-face只写local Arial时请求失败 | 增加已安装Liberation Sans的真实local候选；同一字体度量回归实际通过，未skip |
| 像素参考与遮挡 | libass跨画布大小或位置会改变少量抗锯齿，不能以原生/guard byte完全一致判断几何丢失。原生渲染保留，guard与同画布独立viewport clip做精确byte比较；zero outside/3px原阈值保留，新增真实offscreen故障检出。时钟参考只校准pos/an，保留原始时间/fs/t/fade，并检出重启时钟故障。11行M在合成图被副轨遮挡而扫描成14段，独立原ASS层实际为11/3/3，按独立层验证行数，合成位置/越界仍验证 | 隔离Linux容器38项完整ASS/相关字体预览全部通过，另14项交互全部通过；原794场景保留，未引入新场景计数或放宽容差 |

Linux38：`.artifacts/checks/20261014T123957Z-dc207183/result.json`，105.28s；Linux14：`20261014T124532Z-15b34a31`，25.95s。Windows生命周期28：`20261014T120855Z-3198bdfa`，62.55s；3项交互修正后：`20261014T120958Z-5704990f`。汇总/入口15：`20261014T124543Z-3c9f53c0`。Ruff、typecheck、bundle新鲜度均通过。测试容器独立、源码只读挂载，不改变主机/Ubuntu全局依赖；安装中代理不可达和Node20不支持pnpm的环境错误仅修复对应层。完整最终Windows分片和第二轮远端四片仍待执行；上述定向结果不能替代它们。
