# CI 影响门禁：复核与验证

基线：第二批 `14a9ac86`。第三批将选测计划接到 Windows、POSIX 与浏览器分片；沿用 required 测试及报告，不引入额外 APT 配置。

## 已处理

- 仅完整浏览器被选中时，Windows 无本地测试包，显式结束该步骤，避免空参数触发全量。
- 浏览器分片安装 dev 依赖，满足现有 Pillow 夹具；Windows 预览保留 tone30 的当前类名。
- 预览保留现有完整验收；仅文档、网站及独立核对清单变更跳过预览。失败、缺失或无效选择不能视为跳过。
- Python 和浏览器必需报告缺失或不合格均失败；四片须同版本、同范围、完整且各用例实际通过。

## 验证状态

- 本地 43 项 required 契约测试通过，无 skip，含真实 Playwright 分片发现（`.artifacts/checks/20261029T183831Z-03151e79/result.json`）；文档检查通过（`.artifacts/checks/20261029T183831Z-41009046/result.json`）。
- 独立复核发现空包误扩大、Pillow 缺失、tone30 类名和预览范围问题，均已修复并复验；最终无未处置阻塞项。真实 GitHub Actions、临时 PR 矩阵及 branch protection 现状待核验。
- 第二批 Windows common/media 本地 240 秒超时尚无确定原因，不能据此声称已通过。
