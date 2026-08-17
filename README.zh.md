# independent-review

[English](README.md)

通过可配置的评审 CLI 后端，对代码、diff 或方案执行一次独立的只读评审。
评审在干净的独立上下文中进行，与编写代码的会话隔离，使评审者不受作者
会话中既有假设的影响。

## 特性

- **后端中立** — 评审 CLI 以 JSON profile 描述，可自由替换，而非硬编码
  集成。内置 profile：Pi、Qoder CLI、Codex CLI。
- **三种证据模式** — `review-diff`（粘贴 diff）、`review-paths`（指定路径
  + 只读工具访问）、`review-artifact`（冻结文档，如方案、规格、runbook）。
- **记忆默认配置** — 后端、模型、effort、轮次等偏好按项目、宿主 agent、
  全局三级记忆（`~/.config/independent-review/preferences.json`）。
- **有界轮次预算** — 默认一轮；每轮都是独立计费调用，调度器不会自行
  串联多轮。
- **对抗式验收** — 每条重要 finding 在本地核实后才被接受；本地无法定论
  的争议可发起一轮 rebuttal 复审。
- **混合评审契约** — 评审者的完整 Markdown 分析原文交付，外加一个提取
  出的决定性裁决。裁决冲突或缺失属于 `unknown` 投递失败，绝不静默放行，
  且诊断会保留评审正文供人工审计。

## 依赖

- Python 3.10+
- 主机上至少安装并登录一个受支持的评审 CLI（`qodercli`、`codex`，或
  `pi` + `node`）。全部适配层已内置在 `scripts/adapters/`——本 skill
  没有任何外部 skill 依赖。

## 使用

```bash
DISPATCHER=scripts/independent-review.py

# 列出已发现的 backend profile 及其可用性
python3 "$DISPATCHER" backends

# 评审最终 diff
python3 "$DISPATCHER" review-diff \
  --backend auto --cwd "$REPO" --diff-file /path/to/final.diff

# 以只读工具访问评审指定路径
python3 "$DISPATCHER" review-paths \
  --backend <name> --cwd "$REPO" --paths 'src/auth tests/auth'

# 评审冻结产物（方案、规格、runbook）
python3 "$DISPATCHER" review-artifact \
  --backend <name> --effort high --cwd "$REPO" \
  --artifact-file /path/to/plan.md --template default

# 将未决争议发回同一评审者复审（反驳轮）
python3 "$DISPATCHER" review-diff \
  --backend <name> --cwd "$REPO" --diff-file /path/to/final.diff \
  --rebuttal-file /path/to/rebuttal.md
```

按项目、宿主 agent 或全局记忆偏好：

```bash
python3 "$DISPATCHER" prefs set --scope project --cwd "$REPO" --backend <name> --effort high
python3 "$DISPATCHER" prefs set --scope host --host kimi-code --rounds 2
python3 "$DISPATCHER" prefs resolve --cwd "$REPO" --host kimi-code
python3 "$DISPATCHER" prefs show
```

作为 agent skill 使用时，将本仓库安装到 skills 目录
（如 `~/.agents/skills/independent-review`），`SKILL.md` 是 agent
运行时的入口。

## 解读结果

裁决是证据，不是接受。`review.text` 是评审者的完整分析；对每条 high 和
medium finding，先对照当前本地代码核实，再记录处置
（`accepted`/`rejected`/`unverified`）。信封结构、失败分类与重试规则见
[references/result-contract.md](references/result-contract.md)。

## 新增评审后端

把一个 JSON profile 放进 `~/.config/independent-review/backends/` 即可
——只要该 CLI 匹配已有的 profile `kind`，无需改任何代码：

```json
{
  "schema_version": 1,
  "name": "mycli",
  "display_name": "My CLI",
  "kind": "argv-stdin-jsonl",
  "auto_priority": 90,
  "discovery": {"binaries": {"mycli": {}}},
  "command": ["{bin:mycli}", "run", "--json", "--cd", "{cwd}", "-"],
  "identity": {"model": {"flag": "--model"}},
  "result": {"strategy": "jsonl-terminal-message"},
  "timeouts": {"default": 1200}
}
```

`jsonl-terminal-message` 期望 Codex 风格事件（`turn.completed` 加
`agent_message` 项）；其他输出形态经一个小型 adapter 接入
（`adapter-prompt-file`）。完整 schema 见
[references/backend-profile.md](references/backend-profile.md)，多个常见
CLI 的调研笔记见
[references/candidate-backends.md](references/candidate-backends.md)。

## 新增评审类型

把 `<name>.md` 放入
`~/.config/independent-review/review-templates/`，再传
`--template <name>`。模板只承载该评审类型的关注点与输出指引；固定的安全
前言、输入围栏、证据范围和裁决契约仍由 dispatcher 持有。用户模板绝不从
被审 checkout 加载。

## 安全

- 评审者只读；粘贴类模式完全不暴露工具。
- 每轮恰好一次计费调用；`unknown` 结果绝不自动重试。
- profile 与偏好只从 skill 目录和用户配置目录加载——绝不从被审仓库
  加载。详见 [references/safety-and-retry.md](references/safety-and-retry.md)。

## 目录结构

```
SKILL.md            Skill 入口与操作契约
scripts/            调度器（independent-review.py）与内置 adapter（adapters/）
backends/           评审 CLI profile（JSON）
references/         契约、backend 说明与内置评审模板
agents/             Agent 定义
tests/              调度器测试（unittest）
```

## 运行测试

```bash
python3 -m unittest discover -s tests
```

## 许可证

[MIT](LICENSE)
