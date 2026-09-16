#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从门户 lang.js 提取 zh-CN 文案表，生成 src/campusnet/data/error_codes.json。

用法:
    python tools/extract_error_codes.py [lang.js 路径]

lang.js 可从门户下载（注意去掉 ?v= 查询串）:
    http://172.26.8.11/static/themes/pro/js/lang.js
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRC = os.path.join(os.environ.get("TEMP", "."), "srun_probe", "lang.js")
OUT = os.path.join(ROOT, "src", "campusnet", "data", "error_codes.json")


def extract_object(src, key):
    """从 JS 源码里抠出 key 后面的第一个完整对象字面量（按花括号配对，跳过字符串）。"""
    i = src.index(key)
    i = src.index("{", i)
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(src)):
        ch = src[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise ValueError("花括号不配对，无法解析")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    if not os.path.exists(path):
        print("找不到 lang.js: %s" % path)
        print("请先从门户下载，或把路径作为第一个参数传入。")
        return 2
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    table = json.loads(extract_object(src, "translate"))
    zh = table.get("zh-CN", {})
    codes = sum(1 for k in zh if k.startswith("E") and k[1:].isdigit())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(zh, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    print("已写入 %s" % OUT)
    print("条目总数 %d，其中 E 开头错误码 %d 条" % (len(zh), codes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
