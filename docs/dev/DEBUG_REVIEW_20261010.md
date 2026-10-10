# 调试上下文与测试流程审查（2026-10-10）

基线：`3a10baf1`，独立分支 `fix/debug-context-and-test-flow-20261010`。
历史线索：会话 `01a11f97-0086-7d90-b175-ebee68402575`；结论以本次源码与实际执行结果核验，未将旧会话里的测试数量当作当前证据。
首阶段实现提交：`fbafe1e7`，已推送到 `jingkewsword/OMYAA-MAW-NRH-FFV` 的同名开发分支。

## 问题与处理

| 问题 | 状态 | 处理与证据 |
| --- | --- | --- |
| 全库搜索混入巨大生成物 | 已修复 | 基线便携 HTML 2,746,789 bytes、bundle 1,347,840 bytes、历史扫描 JSON 1,092,555 bytes；`.rgignore` 默认排除。显式文件搜索仍可访问，Git/构建/测试不受影响 |
| 约定要求避免大输出，但恢复步骤直接 `git diff` | 已修复 | AGENTS 改为文件清单→选定源码 diff；日志通过有界运行器读取摘要 |
| 用 `Select-String AssertionError` 仍可能输出数 MB 单行，且可能丢失退出码 | 已修复 | `scripts/run_check.py` 限制诊断数量、行宽与扫描大小；保留原始日志与退出码；200 万字符单行失败回归通过 |
| `CompactContainerAssertions` 被误认为通用保护 | 仅说明 | 原混入仅覆盖成员断言，无法覆盖 assertEqual/custom msg/第三方输出；保留原混入并用运行器兜底，不全局 monkey-patch unittest |
| `debug.log` 仍被版本控制 | 已修复 | 仅从本分支索引移除并忽略；本 worktree 原文件仍在，其他工作区不改动 |
| e2e 服务日志无限累积并在失败时整份输出 | 已修复 | 有界尾部，stdout/stderr 独立 UTF-8 解码；真实假服务输出 200 万字符后失败的测试通过 |
| Node / e2e 默认 uv 路径隐式同步 | 已修复 | 两处改 `--no-sync`；文档明确一次性准备环境、MAW_TEST_PYTHON 与 MAW_E2E_PYTHON 分工 |
| 超时、stdin/输出管道与后代服务造成命令挂起 | 已修复 | 运行器关闭 stdin、输出直接落文件、设 deadline；Windows 超时清理实际子进程回归通过；通用 e2e helper 的 POSIX 分组清理已实现，待 Linux CI 验证 |
| 全量重复跑、把 unit 当作全部零依赖 | 已修复 | 按变化选择 Python/Node/build/typecheck/browser/人工层；记录已通过层与源码状态，变化才使相关证据失效 |
| `cue-scroll-fixture.mjs` 独立服务生命周期 | 仅说明 | 它自行管理 child 与日志，不走通用 helper，本轮未改造。Windows 正常 stop 仍值得单独增加真实 fixture 回归；不能用本轮通用 helper 的通过结果代表它 |
| CI 覆盖范围被高估 | 仅说明 | 原 Editor job 只有指定 Python 装配契约与两份 browser spec，不是全套产品验证；新增 Windows/Linux 标准库工具矩阵，失败日志保留 7 天 |

## 当前验证记录

在本 worktree 根目录使用现有 Python 与 Node，无新增依赖安装，无便携 HTML/bundle 重生成。

| 验证 | 实际结果 | 本地证据（`.debug-runs/` 下） |
| --- | --- | --- |
| `python scripts/run_check.py --timeout 60 -- python -m unittest tests.test_run_check tests.test_compact_assertions` | 11/11 通过、0 skip；其中运行器新增 6 项、已有 compact assertions 5 项 | `20261010T050546Z-1dd42c38/result.json` |
| `python scripts/run_check.py --timeout 60 -- node --test tests/test_e2e_output_tail.mjs tests/test_e2e_server_lifecycle.mjs` | 6/6 通过、0 skip；含真实后代服务监听端口的释放 | `20261010T050823Z-28b1cc20/result.json` |
| 修改的 e2e helper 与 editor utils 测试脚本语法 | `node --check` 通过 | 终端退出码 |
| 默认 `rg --files` 排除上述产物；显式 `rg -l ... editor-bundle.js` 可访问 | 通过 | 定向文件枚举/搜索 |
| `git check-ignore debug.log .debug-runs/test.log` | 两者均忽略 | Git 输出 |
| `git diff --check` / 暂存差异检查 | 通过 | Git 输出 |

首次 Python 测试遇到沙箱临时目录权限失败，改用本次进程专属 `.debug-runs/tmp`。随后 Windows `taskkill /T` 在沙箱内被拒绝，运行器正确记录清理失败；在沙箱外重跑同一回归通过。Node 输出中的 `ℹ` 暴露了外层 Python GBK 编码问题，已为运行器 stdout/stderr 显式设 UTF-8 并补充中文/emoji 回归。这些失败没有被计为通过，也没有靠重装环境处理。

## 未验证边界与后续建议

- Linux 实机与 GitHub CI 尚未运行。工作流当前仅在 PR 或 main push 触发，开发分支 push 本身不会触发该矩阵；创建 PR 后观察 Debug tooling 两个平台结果。
- 没有跑完整 Python、Node、Chromium 产品套件；本轮不修改业务源码与生成产物，采用有针对性的标准库回归。新 worktree 没有产品依赖环境，未为本轮工具改动重装整套环境。
- Ruff 未运行：现有解释器没有 ruff 模块，已执行 Python 实际回归与静态语法检查，不能替代后续 CI lint。
- 日志摘要是启发式抽取，不承诺完整失败清单；巨型日志会明确标记扫描受限。强杀运行器、脱离进程组或父进程先退出的孤儿进程，仍需按记录 PID/路径检查，禁止按进程名全局清理。
- `.rgignore` 只影响遵守它的搜索工具，无法阻止 agent 显式读取生成文件或历史会话；流程约定和有界执行入口需要共同使用。
- 后续优先验证 cue-scroll 的独立生命周期，再考虑拆分 `test:unit` 中的纯逻辑与跨运行时测试；不要一次性大改断言或建立庞大的自动测试选择器。两者均是后续改进建议，不记作本轮已修复。

维护者使用入口见 [DEBUG_WORKFLOW.md](DEBUG_WORKFLOW.md)。本轮没有创建 PR、合并 main 或改动其他 worktree。
