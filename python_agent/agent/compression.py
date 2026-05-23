"""
agent/compression.py — 语义压缩（Python 版 smartCompress）

按行分组、提取关键词、生成摘要
比分段截断更有信息量，比纯 AI 调用更快
"""

import re
from typing import List, Tuple


def smart_compress(raw_text: str, max_lines: int = 4, hint: str = "") -> str:
    """
    语义压缩：按行分组、提取关键词、生成摘要

    Args:
        raw_text: 原始文本
        max_lines: 最多保留几行
        hint: 补充提示

    Returns:
        压缩后的文本
    """
    all_lines = [l for l in raw_text.split("\n") if l.strip()]

    # 太短不需要压缩
    if len(all_lines) <= 2 and len(raw_text) <= 80:
        return raw_text

    # 过滤装饰线和空白行
    filtered = [
        l
        for l in all_lines
        if l.strip()
        and not re.match(r"^[\s]*[━━‑——=*_]{3,}[\s]*$", l)
        and len(l.strip()) > 0
    ]

    # 提取关键信息行（按语义权重排序）
    def weight(line: str) -> int:
        score = 0
        # 数字多 → 信息密度高
        score += len(re.findall(r"\d+", line)) * 2
        # 包含中文人名/地名
        score += len(re.findall(r"[\u4e00-\u9fa5]{2,}", line))
        # 时间词
        if re.search(r"[今昨前后几天上下左右早晚凌晨傍晚]", line):
            score += 2
        # Emoji 少 → 更正式的信息
        score += 1 if len(re.findall(r"[^\x00-\x7F]", line)) < 3 else 0
        # 短行（精华往往简短）
        if len(line) < 60:
            score += 1
        # 排除纯分隔符
        if re.match(r"^[\s]*[^\u4e00-\u9fa5a-zA-Z0-9]+[\s]*$", line):
            score -= 5
        return score

    scored: List[Tuple[str, int]] = [(l, weight(l)) for l in filtered]
    # 高权重优先，相同权重按原文顺序（stable sort）
    sorted_lines = sorted(scored, key=lambda x: -x[1])
    top = sorted_lines[:max_lines]
    # 恢复原文顺序
    final_lines = sorted(top, key=lambda x: filtered.index(x[0]))

    result = "\n".join(x[0] for x in final_lines)

    if hint:
        result += f"\n\n📌 {hint}"

    return result
