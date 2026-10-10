# Electron 独立编辑器开发记录

日期：2026-10-10。维护者明确要求三项都做：同步 main、应用内更新、安装后直接打开独立编辑器。截图中的商业化讨论仅作背景，不实现定价、授权或售后条款。

## 基线与范围

- 从 upstream/merge/starlit-main 的 89775f6 建立独立 worktree 与 codex/starlit-desktop-updater 分支。
- 本轮 main 为 3a10baf；合并前 main 独有 36 个提交，桌面分支独有 26 个提交。
- 上轮三个更新包识别文件的改动先保存到命名 stash，合并完成后已恢复。
- 保留原工作区 WIP；维护者随后明确要求阶段性提交推送。当前认证账号 jingkewsword 对已改名的 fork jingkewsword/OMYAA-MAW-NRH-FFV 有 ADMIN 权限，使用本任务独立开发分支，不发布 Release、不修改定价。

| 项目 | 状态 | 处理与验证 |
| --- | --- | --- |
| main 合并 | 已修复 | bef52dd；解决 27 个冲突文件，保留 ESM 构建、桌面原生能力；定向 Node 36 项与 typecheck 通过，Python 475 项中三个失败修复后定向重测 3 项通过 |
| 安装后直接进入编辑器 | 已实现 | Installer 改为编译期检查资源；安装完成、可选桌面快捷方式与工程关联直接进入 MOSE；安装包编译验收进行中 |
| 应用内更新 | 已实现 | 独立 MOSE 清单和缓存、后台检查/下载/取消、哈希校验、未保存确认及安装交接；Windows 安装版可退出安装，其余包手动安装 |
| 分层验收 | 已通过主要检查 | 更新/桌面/打包 Python 62 项、desktop Node 28 项、根目录 Node 497 项通过；实际打包 exe 的 Electron E2E 4/4 通过 |
| 商业模式 | 仅说明 | 抢先体验与最终开放是方向参考，不添加付费限制 |

## 验证边界

- 编辑器 bundle freshness 与 TypeScript 检查通过；未重生成 `blank-editor.html`，内联副本待发布前统一重生成。
- Python 初次完整回归 1945 项：1 个清单顺序断言未包含新增模块，26 项跳过；修正后该用例与桌面更新/API 测试共 9 项重测通过。最终完整重测进行中。
- PyInstaller 生成独立后端，Electron 44.1.0 / electron-builder 26.0.12 生成 Windows x64 MOSE.exe。打包版 4 项 E2E 全通过：取消退出、第二实例打开、后端清理；偏好跨重启；原生/拖入工程与保存；更新面板、权限隔离、说明转义、开关持久化。原生选择对话框由测试替身提供路径。
- 更新面板间距实测 16px；明暗主题截图位于 `build/desktop-qa-packaged/`。截图中的 99.0.0 和 HTML 字符串是转义测试数据，不是真实发布版本。
- 本机 electron-builder 解压签名工具中的 macOS 符号链接失败；将已下载归档的 Windows 工具解压到工作区缓存后成功构建，无需修改系统权限。没有配置发行签名证书。
- 本地后端按 MAW.spec 直接构建，未执行全套 ASR 托管 Runtime 冻结流程；本地包用于独立编辑器验收，不代表完整 Launcher 各识别引擎已验收。
- 未在用户系统执行安装/卸载、文件关联变更或真实跨版本更新。CI 安装测试脚本已补充 MOSE 快捷方式与直接打开命令检查，需隔离 Windows 环境实际运行。macOS/Linux 原生构建、签名/公证和实际更新未在本机验收。
- 发布流水线同时生成 MAW 与 MOSE 两份更新清单；正式发布仍需上传真实资产与 MOSE 清单。本轮不创建 Release。
