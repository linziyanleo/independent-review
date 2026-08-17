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
- **记忆默认配置** — 后端、模型、effort、轮次等偏好按项目、主机、全局
  三级记忆（`~/.config/independent-review/preferences.json`）。
- **有界轮次预算** — 默认一轮；每轮都是独立计费调用，调度器不会自行
  串联多轮。
- **对抗式验收** — 输出结构化 findings，由你在本地核实；对本地无法
  定论的争议，可发起一轮 rebuttal 复审。
- **结构化结果契约** — 归一化的结果信封，包含后端失败分类与显式的
  证据缺口说明。

## 依赖

- Python 3.10+
- 主机上至少安装并登录一个受支持的评审 CLI（如 `qodercli`、`codex` 或 Pi）

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
  --artifact-file /path/to/plan.md
```

记忆偏好设置：

```bash
python3 "$DISPATCHER" prefs set --scope project --cwd "$REPO" --backend <name> --effort high
python3 "$DISPATCHER" prefs show
```

作为 agent skill 使用时，将本仓库安装到 skills 目录
（如 `~/.agents/skills/independent-review`），`SKILL.md` 是 agent
运行时的入口。

## 目录结构

```
SKILL.md            Skill 入口与操作契约
scripts/            调度器（independent-review.py）
backends/           评审 CLI profile（JSON）
references/         profile 模式、结果契约、安全与重试规则
agents/             Agent 定义
tests/              调度器测试（pytest）
```

## 运行测试

```bash
python3 -m pytest tests/
```

## 许可证

[MIT](LICENSE)
