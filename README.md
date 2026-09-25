# 通用短剧工作流

本仓库维护可复用的 AI 短剧制作工作流（当前规则版本 **v3.5**）：六个 Skill、项目模板、最终视频提示词排版规范，以及两个离线工具。公共文件只定义流程和字段含义；剧本、角色、主语言、真实素材名和制作进度由各短剧项目自己保存。

## 从哪里开始

1. 先读 [维护入口](AGENTS.md) 和 [工作流规则索引](工作流规则索引.md)，按当前任务读取相应 Skill。
2. 新建项目时，在本仓库目录运行下方命令。将两个占位符替换为真实的父目录和剧名；父目录中应包含 `_通用短剧工作流`。初始化工具只补缺失文件，不覆盖项目已有内容。
3. 在新项目里核对《项目启动说明.md》，填写《项目参数.json》，并用《制作台账.json》记录任务和实际验收结果。

```powershell
python -B tools/init_project.py --root '<短剧根目录>' --project-name '<新剧名>'
```

## 六个 Skill

| Skill | 主要职责 |
|---|---|
| [screenplay-prebreakdown-analysis](Codex适配剧梦提示词库（模版）0914/screenplay-prebreakdown-analysis/SKILL.md) | 核对剧本事实、对白与旁白来源 |
| [ai-short-drama-director](Codex适配剧梦提示词库（模版）0914/ai-short-drama-director/SKILL.md) | 镜头任务、空间、连续性和导演判断 |
| [cinematic-acting-execution-library](Codex适配剧梦提示词库（模版）0914/cinematic-acting-execution-library/SKILL.md) | 可观察的表演写法 |
| [sd25-video-prompt-compiler](Codex适配剧梦提示词库（模版）0914/sd25-video-prompt-compiler/SKILL.md) | 时间预算、拆段与视频提示词内容编译 |
| [dreamina-sd25-prompt-adapter](Codex适配剧梦提示词库（模版）0914/dreamina-sd25-prompt-adapter/SKILL.md) | 剧梦真实素材引用与内容适配 |
| [dreamina-short-drama-production](Codex适配剧梦提示词库（模版）0914/dreamina-short-drama-production/SKILL.md) | 平台制作范围、提交、验收和断点恢复 |

最终稿按[视频提示词输出规范](视频提示词输出规范_资产全名版.md)排版。Skill 包内的 [README](Codex适配剧梦提示词库（模版）0914/README.md)提供更详细的职责与生产链说明。

## 单生成段离线检查

复制[本段执行清单模板](Codex适配剧梦提示词库（模版）0914/dreamina-short-drama-production/assets/本段执行清单.template.json)，根据当前项目来源填写。模板中的 `unknown` 和 `null` 表示尚未核对，不能直接当作合格清单。

```powershell
python -B tools/workflow_check.py '<已填写的本段执行清单.json>' --prompt '<本段最终提示词.md>'
```

[检查器](tools/workflow_check.py)会核对清单及其与**一个生成段**最终提示词的镜头时间、对白、画面文字和资产引用。只传清单、不传 `--prompt` 时，仅表示清单检查；结果中的 `static_contract_passed` 为 `null` 或 `false`，不能当作最终稿已检查。未填写模板预期会报缺项。工作流不含自动上传、生成或消耗积分的授权。

静态检查无法证明实际视频切镜、音轨原文与说话人、画面文字拼写、旁白画面语义或平台真实引用绑定。成片仍须依据实际结果验收。
