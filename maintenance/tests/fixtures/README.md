# 迁移回归的真实历史样本

这些文件只用于临时合成项目与冻结发布复测，不是当前执行规则，也不授权迁移真实项目。测试读取静态样本，不需要 `.git`，不执行历史工具。`provenance.json` 记录完整 Git commit、历史 writer 和原始模板的 SHA-256。

## 无 schema 物理路径锁

来源：`4f30aee26776a365d364fde969dc8c6fbf73f447`。

`legacy-3.5-noschema/AGENTS.project.template.md` 与 `项目参数.template.json` 是对应 Git blob 的原始字节。版本锁是按该提交的 `tools/init_project.py` writer 合同从同一提交资源 blob 构造的静态样本；物理位置选用历史 Windows 默认公共目录，不指向测试环境。

历史 writer 实际保存以下字段，没有 `schema`：

```python
json.dump({'workflow_version':'3.5','common_root':str(common),'files':entries},
          out, ensure_ascii=False, indent=2)
```

资源集严格依照原 writer：根目录六个模板/入口（`项目启动说明.template.md`、`视频提示词输出规范_资产全名版.md`、`AGENTS.project.template.md`、`AGENTS.md`、`工作流规则索引.md`、`制作台账.template.json`），旧包中非 `_升级` / `_备份` / 点号目录内的 `.md` / `.json` 文件，以及 `tools/workflow_check.py`、`tools/init_project.py`。本提交实际合计 20 个资源；路径保持旧包名和 Windows 反斜杠，各哈希由对应 Git blob 的原始字节计算。根 README 当时不在 writer 的资源集内，不人为补入。

## 基础设施 1.0 的 v2 控制文件

来源：`6d2ca1b67ea808d12d8254cecbba8c80fd251d01`。

`infrastructure-1.0/AGENTS.project.template.md`、`项目参数.template.json`、`workflow.manifest.json`、`bundle.manifest.json` 是该提交原始字节。对应包名当时为 `Codex适配剧梦`。模板没有新的 `WORKFLOW-BOOTSTRAP` 管理标记。

`工作流版本锁.json` 由该提交全部运行文件的临时 Git 导出快照，交给当前只读 `load_layout` / `make_lock` 构造；没有执行该提交的工具。保存该历史快照的全部 26 个资源 ID、路径和真实原始字节哈希，`infrastructure_version` 为 `1.0`。只有临时导出位置提示换成固定历史 Windows 物理位置，避免样本携带已清理临时目录。

`工作流绑定.json` 依照该提交 `tools/init_project.py::_binding` 的默认同父目录结果构造：binding-v1、浅层 `['..']`、`max_depth=1`，以及固定历史位置提示。

`support.py::historical_project` 直接从这些历史控制样本建立临时项目，按历史 writer 行为填写项目 name/root/common_root，并替换更早 AGENTS 的 `{{COMMON_ROOT}}`；不调用当前或历史初始化器。回归覆盖先只读 plan、错误摘要零写入、批准摘要后的 apply、真实旧控制字节备份、绑定解析、v2 内容锁验证及用户块外 UTF-8/BOM/CRLF 字节保留。
