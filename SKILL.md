---
name: memory-recall
description: 长期记忆分片系统的召回与维护。当需要某块长期记忆但不确定它是否已在上下文里（本机硬件、代理与 GitHub 通道、积分计费、沙箱限制、文件操作约定等），或要新增/修改记忆分片、调整触发关键词，或怀疑"记忆没生效"时使用。也用于体检 ~/.workbuddy/MEMORY.md 是否超限被截断。
agent_created: true
---

# 记忆分片召回与维护

## 为什么有这套东西

`~/.workbuddy/MEMORY.md` 每会话自动注入，但**超过约 4,000 字符会被静默截断**——2026-10-04 实测：文件 12,254 字符，注入只到 3,978 处，**后 68% 全部丢失**，丢掉的正是最新写入的章节。

原因是记忆追加在文件末尾，而截断保留头部 → 越新写的越先丢。

解决方式是索引化 + 按需加载：

| 层 | 位置 | 行为 |
|---|---|---|
| 主索引 | `~/.workbuddy/MEMORY.md`（< 4,000） | 常驻注入，只放高频规则 + 分片索引表 |
| 分片正文 | `~/.workbuddy/memory/shards/*.md` | 不常驻，命中关键词才注入 |
| 自动召回 | `~/.workbuddy/hooks/memory-recall.py` | UserPromptSubmit hook，命中即注入 |
| 完整备份 | `~/.workbuddy/memory/MEMORY.full.2026-10-04.bak` | 重构前原文，12,254 字符 |

## 架构（一句话）

用户提问 → hook 读 stdin 里的 prompt → 对每个分片第 2 行的 `keywords` 做子串匹配 → 按命中数排序取前 3 个、总字符 ≤ 7000 → 写 stdout → 注入上下文。

退出码恒为 0，任何异常静默，绝不阻断提问。无命中则零输出。

## 主动召回（hook 没命中时）

分片不一定被自动命中（关键词没覆盖到就漏）。需要时直接读：

```bash
ls ~/.workbuddy/memory/shards/          # 看有哪些分片
```

然后用 Read 读对应文件。当前分片：

| 分片 | 覆盖内容 |
|---|---|
| `proxy-network.md` | 代理端口、GitHub 下载/发布通道、502、镜像、6102 注入 |
| `git-credential.md` | CredentialHelperSelector 弹窗、credential.helper 多值键 |
| `hardware.md` | RTX 5070 Ti 12GB、驱动、DPI、WoWLAN 唤醒 |
| `sandbox-limits.md` | 持久进程、Start-Process/Popen 被拦、回收站删除 |
| `tools-paths.md` | ffmpeg/ffprobe 路径、Bash shim、lms.exe 卡住 |
| `file-ops.md` | 压缩=打包、移动不用硬链接、删除授权、TC260 AIGC 标识 |
| `credits.md` | 积分与 token 换算、选模型成本 |
| `verify-source.md` | 判断功能是否存在必须查源码/版本号 |
| `identity-study.md` | air 的数学背景、定位、讲法 |
| `creative-defaults.md` | 视频默认 20s |

**判据：宁可多读一个分片，也别凭印象答。** 读分片比答错便宜。

## 新增分片（标准格式）

在 `~/.workbuddy/memory/shards/` 建 `.md`，**第 2 行必须是 keywords 行**，脚本靠它匹配：

```markdown
# 分片标题
<!-- keywords: 词1|词2|词3 -->

正文…
```

规则：
- keywords 用 `|` 分隔，做**子串**匹配（不是分词），所以写"下载"就能命中"下载失败"。
- 单个关键词别太泛（"git" 会每轮命中），也别太长（长短语几乎命中不了）。
- 关键词区分大小写不敏感，中文可用。
- 建完**离线测一遍**再算完事：
  ```bash
  echo '{"prompt":"触发词测试"}' | '~/.workbuddy/binaries/python/versions/3.13.12/python.exe' '~/.workbuddy/hooks/memory-recall.py'
  ```
  看 stdout 里有没有新分片标题。

## 维护主文件

两条硬规则（写进了 MEMORY.md 顶部，照做）：

1. **新内容插在 `## 常驻区` 之前。** 截断保头部，放末尾等于白写。
2. **单条超过 300 字符就建分片**，不要往主文件堆。

## 排错

- **怀疑记忆没生效** → 先看本轮上下文里有没有 `[记忆分片自动召回` 开头的段落。没有就是没命中，手动读分片。
- **hook 完全不触发** → 检查 `~/.workbuddy/settings.json` 的 `hooks.UserPromptSubmit` 里有没有 memory-recall 那条；改配置热加载，不用重启。
- **想临时关掉** → 建空文件 `~/.workbuddy/hooks/memory-recall.DISABLED`。注意**不要**用 `hooks/DISABLED`，那是危险命令拦截的开关，两者独立。
- **每次提问都注入一堆东西** → 说明某个分片关键词太泛，收窄它。上限是 3 个分片 / 7,000 字符。
- **体检主文件是否超限** → `wc -m ~/.workbuddy/MEMORY.md`，> 4,000 就有截断风险。

## 全量体检

用 Write 写成临时 .py 再跑（**别走 heredoc**，见坑 5），跑完删掉。检查项：主文件体积、逐分片用其首个关键词触发验证、索引表与目录比对、无关提问零输出、全关键词轰炸不超上限、hook 配置与备份在位。

**基线（2026-10-05 00:14 实测全绿）**：主文件 2,442 / 4,000；12 分片 16,123 字符；12/12 触发命中；无关提问 0 字符；全关键词轰炸 6,327 字符（7,000 上限生效，只取前 3 个分片）。

下次体检若偏离这个基线，就是出问题了。

## 踩过的坑（2026-10-04 上线当天）

1. **stdin 必须按字节读再解码。** 最初用 `sys.stdin.read()`，Windows 下 stdin 默认不是 UTF-8，payload 里的中文被解成乱码 —— 结果是**所有中文关键词静默失效，只剩 ASCII 关键词能命中**，表现就是"问显存却召回了工具路径"。必须 `sys.stdin.buffer.read()` 后依次试 `utf-8` / `gbk` / `cp1252`。
2. **关键词别写泛化的 ASCII 单词。** `tools-paths.md` 原本有 `PATH`，结果 payload 结构里的 `transcript_path` 字段名把它**每次都命中**。→ ① 优先只拿 `prompt` 字段匹配；② 退回全文时先 `re.sub(r'"[A-Za-z_]+"\s*:', " ", raw)` 剥掉 JSON 键名；③ 单字母/通用英文词不要做关键词。
3. **`hooks/DISABLED` 会让新 hook 静默失效。** 那个文件是危险命令拦截的开关、当前存在，沿用会把召回一起关掉且无报错。本脚本用独立的 `hooks/memory-recall.DISABLED`。
4. **并发写入会读到半截文件。** air 常并行开多个会话，别的 agent 也在往 `shards/` 写分片。实测出现过一次：读到正在写入的文件，判定为"缺 keywords"并误报。已加 `time.sleep(0.05)` 后重读一次再判定。若仍偶发误报，忽略即可——只影响一轮，下一轮自动恢复。
5. **测试脚本别用 heredoc 写正则。** Bash heredoc 会吞反斜杠，`r"keywords:\s*-->"` 传进去就废了，会得出"所有分片都不合规"的错误结论。要跑检查就**用 Write 写成临时 .py 再执行**，跑完删掉。

## 调试

建空文件 `~/.workbuddy/hooks/memory-recall.DEBUG`，之后每次提问会往 `~/.workbuddy/hooks/memory-recall.log` 追加：原始 payload 前 400 字符、实际用于匹配的文本、命中的分片名。**验证完记得删掉 DEBUG 文件和 log**，别长期留着写日志。

## 已知边界

- hook 只在 `UserPromptSubmit` 触发，即**每轮用户提问时**。会话中途我主动想到要用，得自己 Read。
- 匹配是字面子串，没有语义召回。问法完全避开关键词就会漏 —— 所以本 skill 的存在是必要的兜底，不是可选的。
