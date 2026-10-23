# Windows 测试主门禁提交前复核

基线：上游 main `ed52f7a7`，吸收 #298、#299；汇总测试线原 head `c4b9999d`。独立审查者未参与实现，复核实际 runner、门禁条件、退出码、平台适用性、测试 ID 和原断言。当前结论：下列修订完成后无未处理的阻塞代码问题；最终提交的 CI 仍独立验收。

| 发现 | 实际影响与处理 | 验证 |
| --- | --- | --- |
| shared builder-only 未选择完整浏览器 | 两个 builder 会影响真实 Editor/Launcher 装配，原 tools/media/preview 与 smoke 不能覆盖所有消费者。在现有选择规则加入完整浏览器 fallback，保留其余组并集。不是当前 #301 完整改动集漏测的证据 | 原规则负例失败，修订后通过；不新增选择框架 |
| 新 main 的 macOS 实机字体目录测试在其他平台跳过 | 实机 MobileAsset 路径在 Windows/Linux 不适用；按完整 ID 与原原因精确标注 N/A。macOS 缺资产、错 owner 或错原因仍拒绝，合成目录测试仍执行 | 新策略旧红后新绿；原 54 项 required 失败记录保留；定向 2 项中 1 项真正执行、1 项原样 skip/N/A，required 通过 |
| 文档残留旧 Windows 生命周期 job 名称 | 实现已将 Windows 生命周期并入业务主 job，文档统一为 Windows 业务与 POSIX 差异任务 | 对照实际 YAML 与汇总条件修正 |

runner 采用 main 的标准 `unittest.discover` 后筛组，保留动态/imported/load_tests、导入失败哨兵和类级 skip。pack 回退串行，不恢复旧 AST 预选或 pack-worker 原型；无 targets 的完整文件并行保留。唯一撤回的原型测试对应已经撤回的 pack-worker 实现，没有删除业务工况。

冲突涉及的五份 Python 测试保留 main 原测试 ID；FontTools 真实 TTC 补充回归使用独立类名，避免覆盖 main 的 mock 流生命周期回归。真实 FFprobe、媒体处理、SQLite/ZIP、HTTP、取消与回收断言保留。

Windows 主 job 保留原选择和报告；依赖、symlink 权限或 Bash 工具链缺失仍失败。POSIX 只保已有路径、符号链接、checksum、生命周期和真实坏文件差异证据；完整浏览器四片及发布的既有平台规则保留。Linux/macOS 全量迁移等待真实环境数据。

复核发现仅允许 Windows 的初版规则仍会使既有 Linux `release.yml` 质量入口（完整 common required）因 macOS 专属目录 skip 必然失败，进而阻塞发布；因此精确承接 Windows/Linux，而非泛化允许所有 POSIX。macOS 与未知平台仍不能把缺实机资产算通过；没有为该修订迁移或重跑 Linux 全套。

本地证据：runner 19 项零失败/skip；burn 52 项、local server 95 项零失败/skip；fonts 与 batch 54 项零业务失败，首次因上述实机目录 skip 拒绝 required，未重跑掩盖。真实 Chromium 的工程打开及原文本输入回归 10 项通过，零 skip/retry。构建、新鲜度和类型检查通过。脚本语法和本地契约不等于新 Windows CI 的实际能力或完整浏览器验收。

同一干净 `a5f1316b`、同一 Windows 环境完整串并单次对照：2746 个 selected ID 与 run 数一致，零失败/错误，12 个 skip 保留；382.125→209.458 秒。11 项 skip 不能满足 required；这些数据仅证明该树完整无 targets 引擎的样本收益，不证明 pack 并行等价或新门禁通过，不作为扩大 skip、提高期限或增加 retry 的依据。
