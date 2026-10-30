# v2 清理缓存适配与复核

基线固定为 `ce0fdc3b`。本 PR 合入该 v2 提交并保留旧分支历史；目标仍为 `2.0dev`，依赖 PR 8。只处理性能与诊断开关，不修改格式契约。

## 实现

将缓存接到当前主轨播放和公共 cleanupSegments 导出入口，覆盖主副轨、按轨和动态导出。关闭仅绕过缓存，仍使用同一投影算法与 scope 分组。开关变化立即清空播放/导出缓存；无关句快捷返回保持不变。

控制台用法见 [调试指南](../../../engineering/DEBUG_WORKFLOW.md)。默认开启、会话内有效、不进入普通设置、不写入工程。两个 PR 的开关独立。

## 定向验证

- Node：清理缓存 10 项通过，覆盖 provenance/gaps、字词、原地变更、结构、切工程、范围恢复及开关。
- 编辑器构建、新鲜度检查和 TypeScript 检查通过。
- Chromium：ai-cleanup-scope-integration 的 S3-T04/T05/T06 均通过，覆盖真实播放、ASS/普通预览、scope 修改、撤销/重做、工程切换、主副导出及 v2 保存重开。
- 负向对照：临时恢复 06bdbf81 的缓存模块后，新增诊断开关测试失败，原 9 项缓存测试通过。已恢复实现。
- Node v24.19.0、Python 3.11.15、Windows、Playwright Chromium 构建修订号 1234。Node 低于 package.json 当前声明的版本范围，安装产生 engine 警告；本地通过不替代声明版本上的远端 CI。
- 首轮浏览器启动因复用环境缺少 send2trash 失败；随后建立本任务独立、按 uv.lock 安装的基础环境解决，未修改其他工作树环境。
- S3-T06 首轮另存测试的模拟句柄缺少迁移保护所需 getFile，导致没有写入结果；补充空文件句柄后定向复验通过。生产保存实现未修改。

命令：

```text
node --test tests/test_cleanup_projection_cache.mjs
node scripts/build-editor.mjs --write
node scripts/build-editor.mjs --check
node node_modules/typescript/bin/tsc -p web/tsconfig.typecheck.json
node node_modules/@playwright/test/cli.js test --config=tests/config/playwright.config.mjs --project=chromium --workers=1 tests/e2e/ai-cleanup-scope-integration.spec.mjs -g "S3-T04|S3-T05|S3-T06"
```

执行时均通过 scripts/run_check.py 限时记录；复验需指定可用的 MAW_E2E_PYTHON。未跑全量。

## 性能采样

真实 Chromium refreshSubtitlePreview，合成 100 个清理范围；每次切换先准备 1 次，再重复预览 10 次；1 轮预热，随后 5 轮交错开关取每轮 10 次调用平均耗时的中位数：关闭 2.3 ms，开启 0.07 ms。包含预览调用，但不是整段媒体帧率；开启的暖缓存数字不含准备成本。

性能不设 CI 时间阈值。真实大工程、长媒体与桌面原生文件选择器仍需按 [人工核验清单](cleanup.checklist.md) 验收。

## 独立审查与已知基线失败

独立只读审查未发现 blocker/major。核对了主副轨 SRT、ASS、动态导出及预览消费者，没有发现可达的缓存结果写回污染；接受每次值快照检查与缓存内存成本。CRLF 卫生问题已转换为 LF。

基线 PR 8 的 ce0fdc3b 远端 CI 并非全绿：Editor 59/63，含旧 DATA.segments 访问及保存后 dirty 断言；Windows Preview 出现 project 未定义。见 [Editor](https://github.com/jingkewsword/OMYAA-MAW-NRH-FFV/actions/runs/40919152565/job/123607350174) 与 [Windows](https://github.com/jingkewsword/OMYAA-MAW-NRH-FFV/actions/runs/40919152588/job/123607349745)。本次未扩修这些基线问题，也不将定向通过表述为整组通过。PR 8 后续变更需在最终集成时重新核验相关入口。

审查中的非阻塞措辞建议已处理：测试标题限定实际覆盖入口，浏览器修订号与采样统计口径已明确。

首次推送 17cf01cc 的远端 Node 测试出现 6 项 Resolve/OTIO 失败：隔离测试夹具只传入 AsrEditorUtils，没有传入新增缓存初始化所需的 AsrGapRemoveCore。已补入同一真实模块加载器提供的依赖，不改生产逻辑、不跳过或降低原有断言；定向复验该文件 6 项通过。

## 2026-10-30 基线 CI 修复同步

PR 8 的 `f87c3c98` 已获 Editor、Windows Preview、Ruff 和两平台 Debug tooling 全部通过。本轮只同步该相关修复提交（原始来源 f87c3c9829cb79093eba80d8f92cc96eadc2b281），没有引入另一个说话人改动；无冲突，原优化及默认开启的诊断开关保留。

保存前 v2 校验失败现在显示可定位/修复的错误提示，返回 false 并保持 dirty，不执行写入。失败夹具改用正确的 v2 轨道访问；常规保存测试使用 v2 输入，旧工程另存保护继续由独立迁移测试覆盖。

本轮定向 Node 33/33，构建、新鲜度与类型检查通过。浏览器所选 11 个场景最终均通过：原有 ASS 定位/历史/保存、贴图范围、静态排版、保存错误定位与小/大重叠修复，以及本 PR 的诊断场景。首次两项因基础测试环境缺少 Pillow 失败，按 uv.lock 补充 Pillow 12.3.0 后仅重跑这两项，2/2 通过；没有以重跑冒充首轮整组通过，未跑全量。

独立只读审查未发现 blocker/major：校验在写入和确认检查点前完成；绑定偏移仍使用当前 CueRef，清理缓存不参与原始工程保存。此前列出的基线 CI 问题已有对应修复；本 PR 新 head 的远端结果仍需单独核实。真实长媒体、原生选择器和最终依赖整合仍待人工验收。
