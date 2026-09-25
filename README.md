# 通用短剧工作流

本仓库维护可复用的 AI 短剧制作工作流（创作规则 **v3.5**、定位基础设施 **1.0**）：六个 Skill、项目模板、最终视频提示词排版规范，以及离线工具。公共文件只定义流程和字段含义；剧本、角色、主语言、真实素材名和制作进度由各短剧项目自己保存。

## 更新说明（2026-09-26）

- 公共工作流和 Skill 包的外层目录可以改名或随工作区搬迁；固定清单与资源 ID 负责定位，重复或损坏的候选会明确报错。
- 新项目建立 `工作流绑定.json` 和按资源内容 SHA-256 核验的 v2 版本锁；旧项目须审阅单项目迁移计划后显式接入，内容差异不会自动接受。
- 工作目录只保留制作规则、模板、入口与必要工具。升级记录、测试和历史备份不随核心仓库发布；六个 Skill 的创作规则与平台费用门禁保持原样。

## 从哪里开始

先读 [维护入口](AGENTS.md) 与 [工作流规则索引](工作流规则索引.md)。两个外层目录可改名；根目录 `workflow.manifest.json` 和包内 `bundle.manifest.json` 是固定身份标识。工具按资源 ID 解析文件，根 README 不直接链接可变包目录。

```powershell
python -B tools/workflow_paths.py doctor --json
python -B tools/workflow_paths.py list-resources --json
python -B tools/workflow_paths.py resolve skill.director --json
python -B tools/init_project.py --root '<新项目创建父目录>' --project-name '<新剧名>'
```

`--root` 只指定项目落点；公共目录默认由脚本自身位置定位，也可显式 `--common`。初始化先预检，建立项目 `工作流绑定.json` 与 v2 内容锁；已有旧项目须单独迁移，不通过重复初始化接受新版本。

从项目恢复时，先按项目 `工作流绑定.json` 的浅层 `search_roots` 只读查找固定标识；候选唯一且清单完整后，运行 `doctor --project '<项目目录>' --json`。`doctor` 不带项目只核对公共结构，不能表示该项目的内容锁通过。多份候选须明确 `--common`；内容哈希不同须先审查，不能自动刷新锁。

旧项目迁移只处理明确指定的一部剧。先运行 `python -B tools/migrate_workflow.py plan --project '<旧项目目录>' --common '<公共目录>' --output '<计划文件.json>'`，审阅旧锁映射、内容差异、拟修改控制文件与阻塞项；再用 `Get-FileHash -LiteralPath '<计划文件.json>' -Algorithm SHA256` 取得摘要，执行 `python -B tools/migrate_workflow.py apply --project '<旧项目目录>' --plan '<计划文件.json>' --approve-plan-sha256 '<摘要>'`。应用前会复核计划前置哈希，原控制文件备份留在该项目 `_workflow_migration_backups/`。不迁移剧本与素材的其他绝对路径。

## 六个 Skill

| 资源 ID | Skill | 主要职责 |
|---|---|---|
| `skill.prebreakdown` | screenplay-prebreakdown-analysis | 剧本事实、对白与旁白来源 |
| `skill.director` | ai-short-drama-director | 镜头任务、空间、连续性和导演判断 |
| `skill.acting` | cinematic-acting-execution-library | 可观察的表演写法 |
| `skill.compiler` | sd25-video-prompt-compiler | 时间预算、拆段与视频提示词内容编译 |
| `skill.adapter` | dreamina-sd25-prompt-adapter | 剧梦真实素材引用与内容适配 |
| `skill.production` | dreamina-short-drama-production | 平台制作范围、提交、验收和断点恢复 |

最终稿按 [视频提示词输出规范](视频提示词输出规范_资产全名版.md)排版。包内详细生产链可用 `resolve doc.bundle_readme` 定位。以上资源 ID 由本仓库工具解析，不是 Markdown 或 Codex 原生链接。

## 单生成段离线检查

先用 `python -B tools/workflow_paths.py resolve template.segment_check --json` 找到清单模板，根据当前项目来源填写。模板中的 `unknown` 和 `null` 表示尚未核对。

```powershell
python -B tools/workflow_check.py '<已填写的本段执行清单.json>' --prompt '<本段最终提示词.md>'
```

[检查器](tools/workflow_check.py)仍可独立运行，只传清单时仅检查清单。静态检查不能证明实际视频切镜、音轨、文字拼写或平台真实引用绑定；成片须按实际结果验收。工作流本身不授权上传、生成或消耗积分。
