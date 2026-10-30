# v2 绑定索引适配与复核

基线固定为 `ce0fdc3b`。本 PR 合入该 v2 提交并保留旧分支历史；目标仍为 `2.0dev`，依赖 PR 8。只处理性能与诊断开关，不修改格式契约。

## 实现

按 source/target CueRef 对实际引用轨道建立调用内索引。关闭开关时使用相同 v2 数据的线性查找；缺失端点不覆盖既有偏移，组数据不变。索引每次重建，不跨历史或工程保留。

控制台用法见 [调试指南](../../../engineering/DEBUG_WORKFLOW.md)。默认开启、会话内有效、不进入普通设置、不写入工程。两个 PR 的开关独立。

## 定向验证

- Node：绑定、轨道模型和双语模块共 42 项通过。
- 编辑器构建、新鲜度检查和 TypeScript 检查通过。
- Chromium：binding-index-diagnostics 单项通过，覆盖组数据、主副交换、撤销/重做、保存重开、工程切换及开关前后 SRT/ASS/工程结果一致。
- 负向对照：临时恢复 ce0fdc3b 的绑定模块后，新增 5 项测试失败；其中性能机制断言实际观察到 200 次线性 find，而预期为 0。已恢复实现。
- Node v24.19.0、Python 3.11.15、Windows、Playwright Chromium 构建修订号 1234。Node 低于 package.json 当前声明的版本范围，安装产生 engine 警告；本地通过不替代声明版本上的远端 CI。
- 首轮浏览器启动因复用环境缺少 send2trash 失败；随后建立本任务独立、按 uv.lock 安装的基础环境解决，未修改其他工作树环境。

命令：

```text
node --test tests/test_multi_subtitle_binding_offsets.mjs tests/test_project_tracks.mjs tests/test_multi_subtitle.mjs
node scripts/build-editor.mjs --write
node scripts/build-editor.mjs --check
node node_modules/typescript/bin/tsc -p web/tsconfig.typecheck.json
node node_modules/@playwright/test/cli.js test --config=tests/config/playwright.config.mjs --project=chromium --workers=1 tests/e2e/binding-index-diagnostics.spec.mjs
```

执行时均通过 scripts/run_check.py 限时记录；复验需指定可用的 MAW_E2E_PYTHON。未跑全量。

## 性能采样

真实 Chromium 编辑器门面，合成 3,000 对绑定；1 轮预热，随后 5 轮交错开关取中位数：关闭 75.5 ms，开启 0.8 ms。测量仅覆盖绑定重算，不是整体保存或拖动时间。

性能不设 CI 时间阈值。真实大工程、长媒体与桌面原生文件选择器仍需按 [人工核验清单](binding.checklist.md) 验收。

## 独立审查与已知基线失败

独立只读审查未发现 blocker/major。核对了 CueRef 身份、首次匹配、缺失端点和历史恢复；没有持久索引失效问题。

基线 PR 8 的 ce0fdc3b 远端 CI 并非全绿：Editor 59/63，含旧 DATA.segments 访问及保存后 dirty 断言；Windows Preview 出现 project 未定义。见 [Editor](https://github.com/jingkewsword/OMYAA-MAW-NRH-FFV/actions/runs/40919152565/job/123607350174) 与 [Windows](https://github.com/jingkewsword/OMYAA-MAW-NRH-FFV/actions/runs/40919152588/job/123607349745)。本次未扩修这些基线问题，也不将定向通过表述为整组通过。PR 8 后续变更需在最终集成时重新核验相关入口。

审查中的非阻塞措辞建议已处理：测试标题限定实际覆盖入口，浏览器修订号与采样统计口径已明确。

## 2026-10-30 基线 CI 修复同步

PR 8 的 `f87c3c98` 已获 Editor、Windows Preview、Ruff 和两平台 Debug tooling 全部通过。本轮只同步该相关修复提交（原始来源 f87c3c9829cb79093eba80d8f92cc96eadc2b281），没有引入另一个说话人改动；无冲突，原优化及默认开启的诊断开关保留。

保存前 v2 校验失败现在显示可定位/修复的错误提示，返回 false 并保持 dirty，不执行写入。失败夹具改用正确的 v2 轨道访问；常规保存测试使用 v2 输入，旧工程另存保护继续由独立迁移测试覆盖。

本轮定向 Node 59/59，构建、新鲜度与类型检查通过。浏览器所选 9 个场景最终均通过：原有 ASS 定位/历史/保存、贴图范围、静态排版、保存错误定位与小/大重叠修复，以及本 PR 的诊断场景。首次两项因基础测试环境缺少 Pillow 失败，按 uv.lock 补充 Pillow 12.3.0 后仅重跑这两项，2/2 通过；没有以重跑冒充首轮整组通过，未跑全量。

独立只读审查未发现 blocker/major：校验在写入和确认检查点前完成；绑定偏移仍使用当前 CueRef，清理缓存不参与原始工程保存。此前列出的基线 CI 问题已有对应修复；本 PR 新 head 的远端结果仍需单独核实。真实长媒体、原生选择器和最终依赖整合仍待人工验收。

## 2026-10-30 说话人核心阶段集成

继续同步 #15 的全绿阶段提交 `86aab171`，包含 #8 的 `f87c3c98`，不包含 #40 的完整说话人界面。本 PR 目标仍为 2.0dev，当前依赖扩展为轨道核心 #8 与身份核心 #15；审阅性能自身增量应相对 86aab171 比较。上一轮性能 head 的五项远端 CI 已全部通过，本轮新 head 另行核验。

仅 CHANGELOG 有冲突，已保留两侧条目；性能源码没有冲突，也没有为身份核心增加新缓存键或双格式运行时。身份仍由工程表和 cue.speaker 的稳定 ID 表达。

本轮定向 Node 66/66、Chromium 2/2、构建/新鲜度和类型检查通过。新增断言使用同名同色但不同 ID 的人物，验证身份分配、合并、撤销/恢复与优化开关前后结果一致；清理单测还覆盖身份清空。浏览器通过真实身份命令和保存重开入口。没有测试 #40 的管理界面、九色快捷键、身份改名或姓名渲染，不宣称这些能力已交付。

相同浏览器采样方法复核：3,000 对绑定重算关闭 75.9 ms、开启 0.8 ms。仅为本地合成工程局部耗时，不代表用户整体交互提速。

独立只读审查无 blocker/major：身份是 cue 标量字段，变化会使缓存失效；历史恢复后的新对象重新投影，绑定查找不按姓名/色值匹配。原开关默认开启、相互独立、关闭不改变输出的契约保持。未跑全量。
