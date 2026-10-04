#!/usr/bin/env python3
# memory-recall: UserPromptSubmit hook
# 命中分片 keywords 时，把 ~/.workbuddy/memory/shards/*.md 的正文注入上下文。
# 设计约束：任何异常都静默退出 0，绝不阻断用户提问。

import os
import re
import sys
import glob
import json
import time

MAX_SHARDS = 3
MAX_CHARS = 7000
MEM_LIMIT = 4000  # MEMORY.md 注入上限，超过即静默截断
SHARD_DIR = os.path.join(os.path.expanduser("~"), ".workbuddy", "memory", "shards")
# 独立开关：与危险命令拦截用的 DISABLED 分开，互不影响
DISABLED = os.path.join(os.path.expanduser("~"), ".workbuddy", "hooks", "memory-recall.DISABLED")


def main():
    if os.path.exists(DISABLED):
        return
    if not os.path.isdir(SHARD_DIR):
        return

    # 必须按字节读再解码：Windows 下 stdin 默认不是 UTF-8，直接 read() 会把中文解成乱码，
    # 导致所有中文关键词静默失效（2026-10-04 实测踩到：只剩 ASCII 关键词能命中）。
    try:
        data_bytes = sys.stdin.buffer.read()
    except Exception:
        return
    if not data_bytes:
        return

    raw = None
    for enc in ("utf-8", "gbk", "cp1252"):
        try:
            raw = data_bytes.decode(enc)
            break
        except Exception:
            continue
    if raw is None:
        raw = data_bytes.decode("utf-8", errors="replace")
    if not raw:
        return

    # 只拿用户真正输入的文本做匹配。退回全文时要剥掉 JSON 键名，
    # 否则 "transcript_path" 这类结构字段会命中 PATH 之类的泛关键词。
    text = ""
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            for key in ("prompt", "message", "user_prompt", "text", "content", "query"):
                if isinstance(obj.get(key), str):
                    text = obj[key]
                    break
    except Exception:
        pass
    if not text:
        text = re.sub(r'"[A-Za-z_]+"\s*:', " ", raw)

    hits = []
    broken = []  # 缺 keywords 行的分片：永远不会被召回，且无报错，必须告警
    for path in sorted(glob.glob(os.path.join(SHARD_DIR, "*.md"))):
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().split("\n")
        except Exception:
            continue
        kw_line = lines[1] if len(lines) > 1 else ""
        m = re.search(r"keywords:\s*(.+?)\s*-->", kw_line)
        if not m:
            # 并发写入竞态：别的会话可能正在写这个文件，读到了半截。
            # 短暂等待后重读一次再判定，避免误报污染上下文。
            time.sleep(0.05)
            try:
                with open(path, encoding="utf-8") as f2:
                    lines = f2.read().split("\n")
                kw_line = lines[1] if len(lines) > 1 else ""
                m = re.search(r"keywords:\s*(.+?)\s*-->", kw_line)
            except Exception:
                pass
            if not m:
                broken.append(os.path.basename(path))
                continue
        kws = [k.strip() for k in m.group(1).split("|") if k.strip()]
        score = sum(1 for k in kws if k.lower() in text.lower())
        if score:
            hits.append((score, path, "\n".join(lines)))

    hooks_dir = os.path.join(os.path.expanduser("~"), ".workbuddy", "hooks")
    if os.path.exists(os.path.join(hooks_dir, "memory-recall.DEBUG")):
        try:
            with open(os.path.join(hooks_dir, "memory-recall.log"), "a", encoding="utf-8") as f:
                f.write("RAW_HEAD=" + raw[:400].replace("\n", "\\n") + "\n")
                f.write("MATCH_ON=" + text[:200].replace("\n", "\\n") + "\n")
                f.write("HITS=" + repr([os.path.basename(p) for _, p, _ in hits]) + "\n\n")
        except Exception:
            pass

    # 自检：主文件超限 / 分片缺 keywords。这两类故障都完全静默，只能靠主动告警暴露。
    warn = []
    mem_path = os.path.join(os.path.expanduser("~"), ".workbuddy", "MEMORY.md")
    try:
        with open(mem_path, encoding="utf-8") as f:
            n = len(f.read())
        if n > MEM_LIMIT:
            warn.append(
                "[记忆系统自检] MEMORY.md 已 %d 字符，超过 %d 注入上限，末尾约 %d 字符会被静默截断。"
                "必须外迁分片或精简：新内容插在「常驻区」之前，单条 >300 字符就建分片。"
                % (n, MEM_LIMIT, n - MEM_LIMIT)
            )
    except Exception:
        pass
    if broken:
        warn.append(
            "[记忆系统自检] 以下分片缺少第 2 行 keywords，永远不会被召回且无报错："
            + "、".join(broken)
            + "。格式：<!-- keywords: 词1|词2 -->"
        )

    if not hits and not warn:
        return

    hits.sort(key=lambda x: -x[0])
    out = []
    total = 0
    for score, path, body in hits[:MAX_SHARDS]:
        if total + len(body) > MAX_CHARS and out:
            continue
        out.append(body.rstrip())
        total += len(body)

    if not out and not warn:
        return

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    buf = ""
    if warn:
        buf += "\n".join(warn) + "\n"
    if out:
        buf += (
            "\n[记忆分片自动召回 · 以下为完整长期记忆，优先级等同 MEMORY.md]\n\n"
            + "\n\n---\n\n".join(out)
            + "\n"
        )
    if buf:
        sys.stdout.write(buf)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
