# 版本管理与发布流程

## 版本号规则

遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/)：`MAJOR.MINOR.PATCH`。

| 位 | 什么时候加 | 本项目举例 |
| --- | --- | --- |
| MAJOR | 有不兼容的变更（配置格式不兼容、命令行参数移除、协议行为改变） | 门户协议从 v1 换成 v2 |
| MINOR | 向下兼容地新增功能 | 新增安卓端、新增「满员自动腾位」 |
| PATCH | 向下兼容的问题修复 | 修掉界面卡在「正在检测中」 |

预发布版本用连字符后缀，排序低于同版本正式版：

```
1.1.0-rc.1  <  1.1.0
```

**不要**在已发布的版本上重新打 tag。发错了就发下一个 PATCH。

## 版本号存在哪

同一个版本号在三个地方出现，发布前必须一致：

| 位置 | 字段 | 用途 |
| --- | --- | --- |
| `src/campusnet/__init__.py` | `__version__` | 桌面端 / CLI / 打包产物 |
| `android/app/build.gradle.kts` | `versionName` | 安卓端显示版本 |
| `android/app/build.gradle.kts` | `versionCode` | 安卓端升级判定（整数，必须单调递增） |
| `CHANGELOG.md` | `## [x.y.z] - 日期` | 变更记录 |

`versionCode` 用固定公式，避免手滑：

```
versionCode = MAJOR * 10000 + MINOR * 100 + PATCH
```

`1.0.0` → `10000`；`1.0.1` → `10001`；`1.2.0` → `10200`。

一键核对：

```bash
python tools/check_version.py           # 校验一致性
python tools/check_version.py --strict  # 额外要求 HEAD 已打 tag
```

## 产物命名

```
CampusNet-<版本>-win64.zip         桌面端（GUI + CLI 两个 exe 打成一个包）
CampusNet-Android-<版本>.apk       安卓端
```

带平台和架构，是为了以后要出 arm64 或多平台时不至于改名。

## 发布清单

按顺序做，任何一步失败就停下来修，不要跳过。

1. **改版本号**
   - `src/campusnet/__init__.py` 的 `__version__`
   - `android/app/build.gradle.kts` 的 `versionName` / `versionCode`
2. **写 CHANGELOG**
   - 把 `## [Unreleased]` 的内容挪到新的 `## [x.y.z] - YYYY-MM-DD` 小节
   - 分类用：新增 / 变更 / 修复 / 移除 / 文档
   - 更新文件底部的 compare 链接
3. **跑测试**
   ```bash
   python -m unittest discover -s tests
   cd android && ./gradlew testDebugUnitTest lintDebug
   ```
4. **校验版本一致性**
   ```bash
   python tools/check_version.py
   ```
5. **打包**
   ```bash
   # 桌面端
   powershell -ExecutionPolicy Bypass -File tools/build.ps1
   # 安卓端（需要 android/keystore.properties，见下）
   cd android && ./gradlew assembleRelease
   ```
6. **真机/本机冒烟**
   - 桌面端：双击 `CampusNet.exe`，确认能检测状态、登录、下线
   - 安卓端：`adb install -r` 后确认状态检测与通知
7. **提交并打 tag**
   ```bash
   git add -A && git commit -m "chore(release): v1.0.0"
   git tag -a v1.0.0 -m "v1.0.0"
   git push origin main --tags
   ```
8. **建 Release 并上传产物**
   - 标题用 `v1.0.0`
   - 正文直接取 CHANGELOG 里该版本的段落
   - 附件：`CampusNet-1.0.0-win64.zip`、`CampusNet-Android-1.0.0.apk`

## 安卓签名

发布包必须用固定密钥签名，否则用户无法覆盖安装后续版本。

`android/keystore.properties`（**不入库**，已在 `.gitignore` 中）：

```properties
storeFile=../../campusnet-release.keystore
storePassword=***
keyAlias=campusnet
keyPassword=***
```

首次生成：

```bash
keytool -genkeypair -v -keystore campusnet-release.keystore \
  -alias campusnet -keyalg RSA -keysize 2048 -validity 10000 \
  -dname "CN=CampusNet, OU=Dev, O=NWAFU, L=Xianyang, ST=Shaanxi, C=CN"
```

**这个 keystore 要单独备份。** 丢了就无法给已安装的用户推送更新，
只能让他们卸载重装（配置和密码都会丢）。

没有 `keystore.properties` 时 `assembleRelease` 会跳过签名，
产出未签名的 `app-release-unsigned.apk`——只可用于本地验证，不要分发。

## 为什么不把二进制提交进 Git

`dist/`、`*.exe`、`*.apk` 都在 `.gitignore` 里。二进制进 Git 历史会让仓库
体积永久膨胀（每个版本 +30MB，且删不掉），克隆越来越慢。

产物统一放 **GitHub Releases**，和仓库页面在同一个地方，用户点开就能下载。
