# 本地按影响选测：实施与验收

基线：第一批 `0ae27edc`，上游与 fork main `7e463fb4`。第二批依赖第一批的长媒体归组；未修改 main、第一批分支、GitHub 工作流或 ESM 测试 helper。

## 范围与处置

- 已修复：提取现有 test_workflow 本地入口、Node 归组、路径消费者与单次浏览器结果校验；不带 GitHub 输出、分片聚合或 APT。
- 已修复：README/user 文档须执行真实网站消费者；生成目录与非 Markdown 文档夹具保守扩大，避免历史 HTML 工具输入漏选。
- 已修复：test 组补 soundfile。旧能量谷测试把 NumPy/soundfile 放同一 import 块，缺 soundfile 会造成 11 项跳过；修正提示文案，未放宽 required。
- 已修复：真实 macOS MobileAsset 资产用例在 Windows/Linux 按精确 ID+原因记平台不适用；合成目录仍执行，macOS 与未知平台不豁免。
- 已修复：网站同步消费的四份工程/历史文档漏选 website；新增契约与同步脚本的文档清单逐项比对。修复前该测试四项失败（`.artifacts/checks/20261029T182309Z-a7911854/result.json`）。
- 已修复：开发阶段 `--component all` 补上 Launcher 核心；修复前回归测试失败（`.artifacts/checks/20261029T182337Z-82c04914/result.json`）。
- 仅说明：主要 Python 归组/夹具已在 main，不重复搬运。Node 映射由本批实际入口消费，无过渡运行器。

## 验证

- 本地完整环境的选择/执行/浏览器报告/字体契约 54 项通过；唯一 skip 为 Windows 上精确 macOS 资产不适用。补充文档 HTML 边界两项通过。
- 能量谷既有 12 项 required 真实通过，零 skip。uv 0.13.4 lock --check 通过，仅增加已锁定 soundfile 的 test 组归属。
- 初次系统 Python 环境缺依赖时 discovery 产生 FailedTest、Playwright 未安装，required 正确拒绝；独立依赖准备后通过，未过滤失败。
- 修改后选择与浏览器报告契约 30 项通过（`.artifacts/checks/20261029T182346Z-4ee7ef51/result.json`）；沙箱应用运行因浏览器目录为空失败，本机浏览器环境重跑中。
- 开发入口三组均通过（`.artifacts/checks/20261029T182542Z-7abd82d6/result.json`）。独立审查提出的两项均已修复复核，无未处置阻塞意见。
- 应用选测 `f89353140770`：lint、编辑器及 Launcher 构建、类型检查、Node 浏览器 7 项通过；Python common 在 240 秒超时，未输出单项日志；其后 smoke 与所选 e2e 未运行。正在取堆栈定位，不能将整条选测记为通过。
- 实际 CLI：README 网站和清单工具分别通过 `cdba4082349e`、`6ed55335e962`；独立应用 smoke 和 tooltip 浏览器选测通过 `5e3b19ef1ad8`；长媒体组通过 `be050f0cd7de`。common Node 928 项通过（`.artifacts/checks/20261029T183034Z-1ef47c59/result.json`）。
- 未验证：媒体组 `03f4fa42b249` 的 Python gate 240 秒超时，长媒体另行通过。一次 50 秒限时诊断中用例仍推进，30 秒堆栈位于媒体导出进程创建；最后记录的现有用例单独通过（`.artifacts/checks/20261029T183158Z-1602a070/result.json`），无法据此解释原超时。
- common 超时后一次限时诊断在 60 秒仍推进，64 秒以 Windows 访问冲突退出；最后记录的现有用例单独通过（`.artifacts/checks/20261029T183016Z-46100d9f/result.json`）。不能将此次异常与原超时等同，未确定根因。两项单测及相关应用代码相对基线未改；保留 required 严格失败，不将整组记为通过。

## 边界

本批不接 GitHub 动态 jobs，两个临时 PR 的线上路径验收留到第三批接线后；现有 CI 成功不能冒充本地选择已在 GitHub 生效。全部测量只对应本次环境，不宣称稳定性能比例。
