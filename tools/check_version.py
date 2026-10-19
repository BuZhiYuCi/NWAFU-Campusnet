#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布前的一致性检查：版本号在多处定义，必须完全对齐。

检查项：
  1. src/campusnet/__init__.py 的 __version__
  2. android/app/build.gradle.kts 的 versionName
  3. CHANGELOG.md 是否有对应小节 `## [x.y.z] - YYYY-MM-DD`
  4. android 的 versionCode 是否随版本递增（与上一 tag 比较）
  5. 工作区是否干净（避免带着未提交改动打 tag）

用法：
    python tools/check_version.py            # 只校验
    python tools/check_version.py --strict   # 额外要求 HEAD 已打 tag

退出码：0 全部通过；1 有未通过项。
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT_PY = ROOT / "src" / "campusnet" / "__init__.py"
GRADLE = ROOT / "android" / "app" / "build.gradle.kts"
CHANGELOG = ROOT / "CHANGELOG.md"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def read_version_py():
    text = INIT_PY.read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else None


def read_version_gradle():
    text = GRADLE.read_text(encoding="utf-8")
    name = re.search(r'versionName\s*=\s*"([^"]+)"', text)
    code = re.search(r"versionCode\s*=\s*(\d+)", text)
    return (name.group(1) if name else None,
            int(code.group(1)) if code else None)


def changelog_has(version):
    if not CHANGELOG.exists():
        return False
    text = CHANGELOG.read_text(encoding="utf-8")
    return re.search(r"^##\s*\[%s\]" % re.escape(version), text, re.M) is not None


def git(*args):
    return subprocess.run(["git", *args], cwd=str(ROOT),
                          capture_output=True, text=True).stdout.strip()


def previous_tag():
    """上一个「真正的」历史版本 tag。

    必须排除指向 HEAD 自身的 tag：否则在刚打完 tag 的发布提交上检查时，
    会拿自己和自己比，误报 versionCode 未递增。
    """
    head = git("rev-parse", "HEAD")
    tags = git("tag", "--list", "v*", "--sort=-v:refname").splitlines()
    for name in tags:
        if git("rev-parse", "%s^{commit}" % name) == head:
            continue
        return name
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true",
                        help="额外要求 HEAD 已打上对应 tag")
    args = parser.parse_args()

    problems = []

    py_ver = read_version_py()
    if not py_ver:
        problems.append("src/campusnet/__init__.py 里找不到 __version__")
    elif not SEMVER.match(py_ver):
        problems.append("__version__ = %r 不符合 SemVer（X.Y.Z）" % py_ver)

    gradle_ver, version_code = read_version_gradle()
    if not gradle_ver:
        problems.append("android/app/build.gradle.kts 里找不到 versionName")
    elif py_ver and gradle_ver != py_ver:
        problems.append(
            "版本号不一致：__init__.py=%s，build.gradle.kts=%s" % (py_ver, gradle_ver))

    if version_code is None:
        problems.append("android/app/build.gradle.kts 里找不到 versionCode")

    if py_ver and not changelog_has(py_ver):
        problems.append("CHANGELOG.md 缺少 `## [%s]` 小节" % py_ver)

    if git("status", "--porcelain"):
        problems.append("工作区有未提交改动，打 tag 前请先提交")

    tag = "v%s" % py_ver if py_ver else None
    prev = previous_tag()
    if args.strict and tag:
        if git("tag", "--list", tag) == "":
            problems.append("HEAD 尚未打 tag：%s" % tag)

    if prev and version_code is not None:
        try:
            old = git("show", "%s:android/app/build.gradle.kts" % prev)
            m = re.search(r"versionCode\s*=\s*(\d+)", old)
            if m and version_code <= int(m.group(1)):
                problems.append(
                    "versionCode 未递增：当前 %d，上一版 %s 是 %s"
                    % (version_code, prev, m.group(1)))
        except Exception:
            pass

    print("桌面端 __version__ : %s" % (py_ver or "?"))
    print("安卓  versionName  : %s" % (gradle_ver or "?"))
    print("安卓  versionCode  : %s" % (version_code if version_code is not None else "?"))
    print("CHANGELOG 小节     : %s" % ("有" if py_ver and changelog_has(py_ver) else "无"))
    print("上一版 tag         : %s" % (prev or "（无，首次发布）"))
    print()

    if problems:
        print("发现 %d 个问题：" % len(problems))
        for p in problems:
            print("  - %s" % p)
        return 1

    print("版本号一致，可以发布。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
