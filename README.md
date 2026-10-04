# workbuddy-memory-sharding

WorkBuddy 长期记忆整理策略的一次试验：把会静默截断的单一 `MEMORY.md`，改成 **主索引常驻 + 分片按需召回**。

## 问题

`~/.workbuddy/MEMORY.md` 每会话自动注入上下文，但**超过约 4,000 字符会被静默截断，且截断保留头部**。

2026-10-04 实测：文件 12,254 字符，只注入前 3,978 —— **后 68% 全部丢失**。

更麻烦的是结构性矛盾：记忆习惯性追加在文件末尾，而截断保留头部 —— **越新写的越先丢**。一条刚验证完的结论，从写下那天起就没生效过。

## 方案

索引常驻，正文按需。

- 主文件压到 4,000 以内，只放高频规则 + 分片索引表
- 正文外迁到 `memory/shards/*.md`，每个分片**第 2 行**写 keywords
- `UserPromptSubmit` hook 读用户提问，匹配 keywords，命中就把分片正文注入上下文

本质变化：从「**文件里写了什么**决定模型看到什么」换成「**用户问了什么**决定」。

关键点是走 hook 而不是靠提示词提醒模型去加载 —— 后者仍然依赖模型主动想起，前者是事件驱动的硬机制。

## 实测

| | 改造前 | 改造后 |
|---|---|---|
| 常驻上下文 | 3,978（被截断） | 2,442（完整注入） |
| 可召回总量 | 12,254 | 18,565 |
| 触发测试 | — | 12/12 分片命中 |
| 无关提问开销 | — | 0 字符 |

## 用法

1. 建 `~/.workbuddy/memory/shards/`，每个分片第 2 行写 keywords：

```markdown
# 分片标题
<!-- keywords: 词1|词2|词3 -->

正文…
```

2. 放 `memory-recall.py` 到 `~/.workbuddy/hooks/`

3. 在 `~/.workbuddy/settings.json` 加一条 hook（热加载，不用重启）：

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "[ -f '~/.workbuddy/hooks/memory-recall.DISABLED' ] && exit 0; python3 '~/.workbuddy/hooks/memory-recall.py'",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

4. 主文件只留高频规则 + 索引表

维护两条约定：**新内容插在常驻区之前**（截断保头部，放末尾等于白写）；**单条超 300 字符就建分片**。

## 踩过的坑

- **Windows 下 stdin 不是 UTF-8。** 直接 `sys.stdin.read()` 会把中文解成乱码，所有中文关键词静默失效，只剩 ASCII 关键词能命中。必须按字节读再依次试 utf-8 / gbk 解码。
- **关键词别用泛化英文词。** `PATH` 会被 payload 结构里的 `transcript_path` 字段名每次误命中。
- **hook 的 stdout 在 exit 0 时照样注入上下文** —— 这跟 PreToolUse「exit 0 不显示」的规则不一样，是条件性上下文注入唯一可行的路。
- **全局安全阀会误伤新 hook。** 已有的 `hooks/DISABLED` 若为存在状态，新脚本沿用会被静默关掉且无报错。用独立开关文件。
- **并发写入会读到半截文件。** 多会话并行时会出现，加 50ms 重读再判定即可。
- **超限和坏分片都是静默故障**，所以脚本内置了自检：主文件 >4,000 或缺 keywords 行时，每次提问注入告警。

## 局限

- 字面子串匹配，**没有语义召回**，问法避开关键词就会漏。换取的是零依赖、零延迟、行为可预测。
- 只在 `UserPromptSubmit` 触发，会话中途模型自己需要时仍要主动读。
- hook 自身故障则自检一起失效 —— 自检在脚本内部，救不了脚本本身。

## 文件

| 文件 | 说明 |
|---|---|
| `README.md` | 本文 |
| `memory-recall.py` | 召回 hook 脚本，放 `~/.workbuddy/hooks/` |
| `SKILL.md` | 维护用 skill，放 `~/.workbuddy/skills/memory-recall/` |
