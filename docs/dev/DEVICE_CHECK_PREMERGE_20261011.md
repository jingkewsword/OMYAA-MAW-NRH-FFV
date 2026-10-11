# MAW 实机检验预合并分支（2026-10-11）

本分支用于六份既有清单的实机检验。最新上游 main 为基线，保留五个最终 PR 的完整分支与独立合并提交；没有合入上游 main、标记正式 PR 已合、部署核验台、创建 tag 或 Release。#199 的核验与整合均排除。

运行形态为源码 Launcher + 本机 Server。两个 esbuild bundle 已按最终源码重建并提交；不需要运行 Node 来使用编辑器。本次没有生成 MAW.exe 或便携 blank-editor.html，不能把本分支称作已打包发行版。

## 基线与来源

- 上游 main：`14204d39bfc1bc504819de42605c4412c324d99b`。在整合开始与收尾时两次 ls-remote 一致。
- 受检生产整合：`9b364763faabc883b7833a02c6fff89444866787`。后续仅增加本交付文档，不改变生产源码、测试或 bundle。
- 目标：`jingkewsword/OMYAA-MAW-NRH-FFV`，分支 `code/maw-premerge-device-check-20261011`。
- LAN 入口：http://192.168.31.18:8876/ 。仅直接读取部署索引与源 HTML；服务、数据库、勾选及备注未修改。
- 六页共 163 项。页面是历史验收来源，人工项仍需用户实测；自动化与祖先覆盖不等于人工验收。#203 standalone 的 42 项已由合并页完整覆盖，不重复计数。

| 来源任务 | 项数 | 源 HTML SHA256 |
| --- | ---: | --- |
| maw-pr208 | 10 | `84c2686b3c7c90c4ffa2df2310edc93b591d9f2cbc671bef7ef82a5a214f097b` |
| maw-merged-verification-261011 | 82 | `8f7193e7c945a60082c3d2ad84da6a69dbab3ebc4d21864be29df963e214ddd7` |
| maw-pr-review-20261011 | 11 | `142221a80667c3c509f20b733aa11aa75eee89bafd10092f230f088afe7d5620` |
| maw-merged-prs-e3a531a | 35 | `60770e26cd2093398d76d1129b3183b89bc96cb2c99dcc268c951016f39e13fa` |
| maw-pr207-20261011 | 13 | `2dbb049938eabee0872c2eb0027e12c595d2f7d204ee7e167f39ad3f4aa129d0` |
| maw20-gap-delivery-20261011 | 12 | `d6c7efd1094c9bce17ad3d2dc8d0eb162635f1bf311c3f84ea3de4f6e845606d` |

## PR 覆盖

已在 main 的 PR 使用实际 merge commit 做祖先核对，不重新套用 squash 前的 head；新整合 PR 核对其精确最终 head 为本分支祖先。#205 是第二批反馈实现来源，不能仅根据最初候选名单省略。

| PR | 本次状态 | 精确覆盖对象（merge / head） | 原 base | 最终 head |
| --- | --- | --- | --- | --- |
| [#192](https://github.com/Moyf/moys-asr-workflow/pull/192) | 已在 main | `8cc84f73a96bf57923407f3c87bf388c4b19b6e4` | `main` | `be7d3e97e38cd176893b39ede7d349bea52c7978` |
| [#193](https://github.com/Moyf/moys-asr-workflow/pull/193) | 已在 main | `ef301bc1c50c9e85ea44c69099f2678067a587cb` | `main` | `f14cce2edff8f3cd4a636df2c2fb45267497d545` |
| [#194](https://github.com/Moyf/moys-asr-workflow/pull/194) | 已在 main | `3114e838de9573c035d75ebf31d627ba8ae22507` | `main` | `deecdcfd2b588931ffd4ecb9abd2310eda716bad` |
| [#195](https://github.com/Moyf/moys-asr-workflow/pull/195) | 已在 main | `58f635c941731f1463e6be34f79b716f2f70fa20` | `main` | `c00931606ecd39fb6f1916c62f5c710158754b5a` |
| [#197](https://github.com/Moyf/moys-asr-workflow/pull/197) | 已在 main | `88eb35789ecc988926c82e0015b914da02e1be0b` | `main` | `0cb25585cc7a2811b900141d4d37396a0b0723fd` |
| [#198](https://github.com/Moyf/moys-asr-workflow/pull/198) | 已在 main | `5238e3d21893f973653a9d21d21cae73ed0bbd66` | `main` | `443fe32c50d8b87aeb37d4195a944baa80529738` |
| [#200](https://github.com/Moyf/moys-asr-workflow/pull/200) | 已在 main | `44a585c64d23e74b775604cdb191c66086b28ae4` | `main` | `09f0661f2495f1f797d9f52334f0221f955d6a6b` |
| [#201](https://github.com/Moyf/moys-asr-workflow/pull/201) | 已在 main | `e3a531a15318308ac56473622bb0f6b9aac122e1` | `main` | `074f4537d6c9b833e356091a80ae9d748e0eb759` |
| [#203](https://github.com/Moyf/moys-asr-workflow/pull/203) | 已在 main | `d6b27a3665c92fb6fe1d83483263ad62f270220c` | `main` | `b031af850b328df42e3df8ac7babd688b00e9894` |
| [#204](https://github.com/Moyf/moys-asr-workflow/pull/204) | 已在 main | `5303aa8af9b596c4b24f349e54b4cf0e3b9e2aa5` | `main` | `82f60adf644fd17aed8be73bfc79e2a25b724068` |
| [#205](https://github.com/Moyf/moys-asr-workflow/pull/205) | 已在 main | `bb86f6550b15a20e365c9e494d185bee60bdc1e1` | `main` | `2236c98bc8355f21d042842b89a13654d07a4829` |
| [#206](https://github.com/Moyf/moys-asr-workflow/pull/206) | 已在 main | `eb3e8a1acfa67b86293cac5bdb85ab5d4571a4dc` | `main` | `dbd76b4fc8808941d4254dc7eec54cb6174c48c5` |
| [#207](https://github.com/Moyf/moys-asr-workflow/pull/207) | 已在 main | `09af19f13bd87fb46d7ea9849ef81ac76ddbe574` | `main` | `cbbf966df607eb47557a02bad07eb292ac1d0407` |
| [#208](https://github.com/Moyf/moys-asr-workflow/pull/208) | 新整合 | `30096059db863e92dd5804fe46217287176d2ba4` | `main` | `30096059db863e92dd5804fe46217287176d2ba4` |
| [#209](https://github.com/Moyf/moys-asr-workflow/pull/209) | 新整合 | `aba90989e4a9ec10e982523baa0ea905119dbde2` | `main` | `aba90989e4a9ec10e982523baa0ea905119dbde2` |
| [#210](https://github.com/Moyf/moys-asr-workflow/pull/210) | 新整合 | `12c68052036ac3dd8d8c02fea1bca5884b966fe8` | `main` | `12c68052036ac3dd8d8c02fea1bca5884b966fe8` |
| [#211](https://github.com/Moyf/moys-asr-workflow/pull/211) | 新整合 | `659e19ad9b513117ddfe3904f073b8691ead41b0` | `code/maw20-export-binding-261011` | `659e19ad9b513117ddfe3904f073b8691ead41b0` |
| [#213](https://github.com/Moyf/moys-asr-workflow/pull/213) | 新整合 | `99ea0736d3cfdb1be7e6eda4d29387a986527a14` | `code/maw20-media-tasks-261011` | `99ea0736d3cfdb1be7e6eda4d29387a986527a14` |
| #199 | 排除 | 不整合、不核验 | 不适用 | 不适用 |

整合顺序：#208 → #209 → #211 → #213 → #210。#211 依赖 #209，#213 依赖 #211，#210 独立。上游基线自身已包含 #212/#215/#217 的设置与标记改进，本任务没有主动引入清单之外的开放 PR。

冲突仅为 CHANGELOG 和已生成 bundle/meta；CHANGELOG 新增条目全部保留，Editor 与 Launcher 产物分别从最终完整源码重建，没有选取一方旧 bundle。生产源码自动合并。

设计核对：#208 空结果只使用既有音轨快照，不在失败后新增解码/探测；更换媒体与批量项目的数量隔离、取消优先和密钥脱敏保留。#210 复用操作 ID 与 commit 边界，在进入写出后拒绝取消。#209/#211 的快照与准入使用同一绑定代次，陈旧页与保存器等待后的导出不能混用新源；任务槽保留到进程、下载和临时输出清理完成。#213 只授信可靠字词范围，归一化前先撤回失效权限，预览、字幕与时间线消费同一投影，保留原文和其它来源。

## 第二批 40 项源码映射

每项分别定位最新 main 与整合树，40/40 均有实际实现定位；下表是源码证据，不是人工勾选。旧处理记录中残留“待处理”不作为当前事实。

| 项目 | 源码定位（整合树） | 当前说明 |
| --- | --- | --- |
| f261-01 | `web/shared/tooltip.js:153` / `anchorX` | 已在 main；人工待确认 |
| f261-02 | `web/shared/tooltip.js:19` / `TITLE_STORE_ATTR` | 已在 main；人工待确认 |
| f261-03 | `web/shared/tooltip.js:17` / `FORCE_NATIVE_SELECTOR` | 已在 main；人工待确认 |
| f261-04 | `web/editor/ui/editor-wiring-settings-help.js:400` / `contextualHelpButtons` | 已在 main；人工待确认 |
| f261-05 | `web/editor-template.html:802` / `timeline-timebase` | 已在 main；人工待确认 |
| f261-06 | `web/editor-template.html:1462` / `你可以在` | 已在 main；人工待确认 |
| f261-07 | `web/editor/ui/editor-wiring-settings-help.js:131` / `flashSettingsTarget` | 已在 main；人工待确认 |
| f261-08 | `web/editor-template.html:1074` / `subtitle-speaker-mapping-enabled` | 已在 main；人工待确认 |
| f261-09 | `web/editor/ui/editor-wiring-settings-help.js:30` / `settings-search-result` | Latest main uses click-to-navigate search results, superseding auto-jump wording. |
| f261-10 | `web/editor-template.html:1188` / `toast-position` | Latest main implements the three Toast positions; default remains top center. |
| f261-11 | `web/editor/media/waveform/markers.js:52` / `appendMarkerTrack` | 已在 main；人工待确认 |
| f261-12 | `web/editor/markers/editor-markers-panel.js:518` / `pointerdown` | 已在 main；人工待确认 |
| f261-13 | `web/editor/markers/editor-markers-panel.js:631` / `markers-item-note` | 已在 main；人工待确认 |
| f261-14 | `web/editor.css:3540` / `padding: 2px 14px 14px` | 已在 main；人工待确认 |
| f261-15 | `web/waveform.css:706` / `drag-preview` | 已在 main；人工待确认 |
| f261-16 | `web/editor.css:4192` / `markers-item-actions` | 已在 main；人工待确认 |
| f261-17 | `web/waveform.css:746` / `left: -4px` | 已在 main；人工待确认 |
| f261-18 | `web/editor-template.html:334` / `markers-actions-primary` | 已在 main；人工待确认 |
| f261-19 | `web/editor/styles/editor-colors.js:51` / `--subtitle-color-` | 已在 main；人工待确认 |
| f261-20 | `web/editor/ui/editor-wiring-settings-init.js:221` / `requestAnimationFrame` | 已在 main；人工待确认 |
| f261-21 | `web/editor/ui/editor-context-menus.js:300` / `warnWordTimings: false` | 已在 main；人工待确认 |
| f261-22 | `web/waveform.css:894` / `word-timing-mode` | 已在 main；人工待确认 |
| f261-23 | `web/editor/cues/editor-cue-events.js:140` / `请先退出字词码` | 已在 main；人工待确认 |
| f261-24 | `web/editor.css:710` / `order: -1` | 已在 main；人工待确认 |
| f261-25 | `web/shared/utils/ass-export.js:4` / `resolveAss` | PR207 replaces simple fixed margin with measured visibility-first group layout. |
| f261-26 | `web/shared/utils/ass-export.js:4` / `speakerLabelForSegment` | 已在 main；人工待确认 |
| f261-27 | `web/editor.css:1866` / `ass-style-preview-sample` | 已在 main；人工待确认 |
| f261-28 | `web/editor-template.html:1762` / `如果想要查看当前画面实际的 ASS` | 已在 main；人工待确认 |
| f261-29 | `web/shared/utils/ass-export.js:87` / `commentScale` | 已在 main；人工待确认 |
| f261-30 | `web/editor-template.html:1380` / `注释` | 已在 main；人工待确认 |
| f261-31 | `web/launcher/postprocess.js:446` / `custom2` | 已在 main；人工待确认 |
| f261-32 | `web/launcher/postprocess.js:189` / `restoreProviderForTask` | 已在 main；人工待确认 |
| f261-33 | `maw/gui_config.py:663` / `Deepseek 目前不提供转写模型` | 已在 main；人工待确认 |
| f261-34 | `maw/postprocess_llm.py:219` / `loopback_base_url` | 已在 main；人工待确认 |
| f261-35 | `web/launcher/postprocess.js:1656` / `auto_step_hint_burn_original` | 已在 main；人工待确认 |
| f261-36 | `maw/postprocess_pipeline.py:1064` / `green_screen=` | 已在 main；人工待确认 |
| f261-37 | `web/launcher/i18n/launcher-strings.js:120` / `🚀` | 已在 main；人工待确认 |
| f261-38 | `web/shared/editor-i18n.js:113` / `Show word timings` | 已在 main；人工待确认 |
| f261-39 | `web/editor-template.html:1467` / `split-trim-symbol-caption` | 已在 main；人工待确认 |
| f261-40 | `web/editor-template.html:2370` / `word-conversion-title` | 已在 main；人工待确认 |

历史文字变化需按当前行为实测：f261-09 现在显示搜索结果，点击才跳转，不再输入后自动跳页；f261-10 已有三个 Toast 位置选项；f261-25 的简单固定 MarginV 验收被 #207 的真实尺寸、整组可见性与动画时钟排布替代。不能为迁就旧文字撤回新 main。#203/#204/#206 的 11 个产品项、#207 的 13 个定位项、早前已合 35 项与新增两页的范围均由完整相关 merge/head 祖先覆盖及本轮回归支撑，真实模型、媒体与原生交互仍待用户。

## 本轮验证

| 验证层 | 结果 |
| --- | --- |
| 完整 Python | 2060 项，2030 成功、30 跳过，退出 0 |
| 完整 Node | 583/583，退出 0 |
| 独立锁定运行环境定向 Python | 537 项，536 成功、1 跳过，包含五项整合功能与 packaging contract |
| 实际 Edge 首轮 | 135 项，106 成功，29 个 ASS 像素用例因缺 Pillow 失败 |
| 补齐锁文件 build 组后的 ASS / libass | 完整 33/33 通过，含首轮失败 29 项和重复控制项 4 项 |
| 浏览器合计 | 覆盖 135 个不同用例；分批结果，不声称单轮 135 全绿 |
| 生成/静态契约 | Editor/Launcher bundle fresh，TypeScript、全仓 Ruff、diff check、Launcher version check 通过 |
| 实际源码运行 smoke | 独立 lockfile 环境启动 Server；HTTP 200、当前模块加载、空工程无旧视频导出能力、零 pageerror；截图检查通过，服务已停止 |

Edge 范围：launcher-api-errors、launcher-script-match-cancel、gap-removed-video-binding/transfer、gap-removed-media-jobs/cancel-timeout、ai-cleanup-local-export/punctuation/review-fallback、settings-structure、marker-editing-gate、ass-stacking-boundaries、shared-tooltip、editor-bundle、editor-transactions。

完整 Python 中存在既有 fixture 子进程 reader 的 UTF-8 解码诊断及刻意无效媒体的波形警告，套件退出 0；记录在证据中，没有扩大本任务修复。ASS 首轮缺测试依赖已经在隔离环境解决，没有修改生产代码或降低断言。一次环境安装命令被自动审批拦截，改为显式指向本任务 .venv 并获准后完成；其它会话 .venv 未修改。

本分支没有运行远端合并/发布 CI；上述为本机验证。真实供应商/LLM 效果、原生 pywebview/文件保存器、真实媒体流与切点、复杂字体/动画素材以及 163 项人工验收仍由用户完成。

## 获取和启动

在一个新目录获取，避免覆盖现有工作树：

```powershell
git clone --single-branch --branch code/maw-premerge-device-check-20261011 https://github.com/jingkewsword/OMYAA-MAW-NRH-FFV.git maw-device-check
Set-Location maw-device-check
uv sync --frozen
ffmpeg -version
ffprobe -version
uv run --no-sync python maw_gui.py
```

源码需要系统 FFmpeg/FFprobe。若仅直接打开编辑器：

```powershell
uv run --no-sync python server-editor/serve.py --blank --port 0
# 或直接使用真实工程的副本
uv run --no-sync python server-editor/serve.py "C:\samples\test-copy.mosp" --port 0
```

`--port 0` 由系统分配空闲本机端口，以终端输出的地址为准；不会与 LAN 核验台的 8876 服务混用。源码启动读取本仓库 .env，模型运行时按既有界面准备。实机建议先使用工程和媒体副本；这是本次手工验收输入，自动化 fixture 不能代替真实素材。

已生成并提交的运行产物：`web/editor/boot/editor-bundle.js`、对应 `.meta.json`；`web/launcher/boot/launcher-bundle.js`、对应 `.meta.json`。`blank-editor.html` 未重生成，使用 Launcher / Server 取得当前实现。若以后需要发行包，应在明确包装范围后按 `scripts/build-windows.ps1` 生成并另做完整打包验收。
