# 应用内自动更新（Tauri 2 updater）操作手册

本工具已接入 Tauri 2 应用内自动更新：启动 8 秒后静默检查一次，用户也可在「设置 → ℹ️ 关于 → 检查更新」手动检测，有新版可一键下载安装重启。本文档说明**每次发版要做什么**，以及注意事项。

> 关键认知：**代码提交 ≠ 发布版本**。往 GitHub 推代码不会让用户收到更新。只有「打包 + 签名 + 发正式 Release」之后，旧客户端才检测得到新版。

## 一、更新机制（原理）

```
客户端（启动后静默 / 用户手动点检查）
  → 读取 https://github.com/CHEN126110/douyin-auto-uploader-/releases/latest/download/latest.json
  → 比对版本（latest.json 的 version > 当前 tauri.conf.json 的 version？）
  → 有新版 → 下载 setup.exe → 用内置公钥验签
  → 先优雅停掉 python-backend（避免 exe 被占用）→ 覆盖安装 → 重启
```

- 更新源：GitHub Releases（公开仓库 `CHEN126110/douyin-auto-uploader-`）
- 签名公钥：写在 `tauri-app/src-tauri/tauri.conf.json` 的 `plugins.updater.pubkey`
- 签名私钥：`%USERPROFILE%\.tauri-keys\douyin-sock-publisher.key`，密码在同目录 `password.txt`（**仓库外，绝不进 git**）

### 密钥状态（2026-08-29 更新）

原密钥对的私钥已遗失，当天重新生成了一对，`tauri.conf.json` 的 pubkey 已同步换成新公钥（指纹 `012F530C0FE38CAA`）。

- 作废的旧公钥指纹：`DC424DADDE4EB172`。当时仓库没有任何 Release，没有线上客户端依赖它，所以换钥无损。
- 唯一影响：**曾手动拷给别人的 4.0.28 安装包内嵌的是旧公钥，那些机器验不过新签名，必须手动重装一次新版**才能接上自动更新。
- 新私钥若再丢，后果是永久性的：无法再给已装用户推任何更新。**请离线异地备份 `.tauri-keys\` 整个目录**。

## 二、发版流程（主路径：GitHub Actions）

工作流文件：[.github/workflows/release.yml](../.github/workflows/release.yml)，`windows-latest` 上完成 sidecar 打包 → Tauri 构建 → 签名 → 生成 latest.json → 发 Release → 回验端点。

### 一次性准备：配置仓库 Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret：

| Secret 名 | 值 |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | `%USERPROFILE%\.tauri-keys\douyin-sock-publisher.key` 的**文件内容**（不是路径），整段粘贴 |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | `%USERPROFILE%\.tauri-keys\password.txt` 里的那串密码 |

取内容的命令（输出会直接打印到终端，注意别录屏/截图外传）：

```powershell
Get-Content "$env:USERPROFILE\.tauri-keys\douyin-sock-publisher.key" -Raw
```

### 每次发版

```powershell
# 1. 统一升版本号（package.json / Cargo.toml / tauri.conf.json / cfg.yaml 四处）
./tauri-app/scripts/bump-version.ps1 4.0.29

# 2. 提交并打 tag 推送，Actions 自动接手
git add -A
git commit -m "release: v4.0.29"
git tag v4.0.29
git push origin DouYin --tags
```

推 tag 后到 Actions 页面看「发布桌面端」这个工作流。全绿即代表：Release 已发、latest.json 已上传、端点已回验可达。整轮约 30–60 分钟（首次无缓存偏慢，主要花在 pip 装依赖 + PyInstaller + Rust LTO）。

也可以在 Actions 页手动触发（workflow_dispatch），需填已存在的 tag，可选填更新说明。

### 工作流做了哪些保护

- **版本号一致性校验**：tag 与 4 处版本号任一不符立即失败，避免「界面显示一个版本、updater 按另一个判断」。
- **产物改 ASCII 名**：GitHub 上传 Release asset 时会把文件名里的中文逐个替换成 `.`，中文安装包名会让 latest.json 的下载地址 404。工作流统一改名成 `DouyinSockPublisher_<版本>_x64-setup.exe`。
- **强制正式版**：`gh release create --latest`，不是草稿也不是预发布，否则 `releases/latest` 命不中。
- **发完回验**：拉一次真实 endpoint，核对 latest.json 的 version，并 HEAD 一次安装包地址。这步过了才算发布成功。

## 三、发版流程（兜底：本地手动）

CI 挂了或要临时出包时用：

```powershell
cd tauri-app
./scripts/bump-version.ps1 4.0.29
npm run package:release -- -EmitUpdaterManifest -ReleaseNotes "本次更新说明（中文）"
```

产物在 `src-tauri/target/release/bundle/nsis/release-assets/`，三个文件：

- `DouyinSockPublisher_4.0.29_x64-setup.exe`（已按 ASCII 改名）
- `DouyinSockPublisher_4.0.29_x64-setup.exe.sig`（签名存档；updater 实际读 latest.json 里内嵌的 signature，不单独下这个文件）
- `latest.json`

然后在 GitHub 建 tag = `v4.0.29` 的 Release，**原样上传这三个文件、不要重命名**，发布为正式版。

脚本会自动从 `%USERPROFILE%\.tauri-keys\` 读私钥和密码；私钥不在默认位置时先设 `$env:TAURI_SIGNING_PRIVATE_KEY`。

## 四、首次上线检查清单

当前 GitHub 上 **一个 Release 都没有**，所以客户端点「检查更新」必然报错（endpoint 404）。要让链路真正跑起来：

1. **先把本地代码推上去**。远端 `DouYin` 分支停在 2026-05-21 的 `4.0.8`，本地是 `4.0.28`，差 3 个月。CI 构建的是远端代码，不推就等于发布旧版。
   推之前务必确认 `.gitignore` 生效：`upload-browser-profile/`（138 MB，含登录态 cookie）、`logs/`、`*.db`、`*.key` 都必须被忽略——仓库是 **public**，推上去就是公开泄露。
2. 配好上面两个 Secrets。
3. 打 `v4.0.28` 发第一个 Release，作为基线（此时没有比它更旧的在线客户端，不会触发任何人更新，但 endpoint 从此不再 404）。
4. 用这个基线安装包装一台机器，再 `bump-version.ps1 4.0.29` 发第二个 Release，在那台机器上实测「检查更新 → 下载 → 覆盖安装 → 重启」全程。
5. 重点确认更新后 `python-backend.exe` 真的被换成新版（不是因被占用而残留旧版）。

## 五、注意事项与风险

- **私钥是更新信任根**：丢了就再也无法给已装用户推更新（只能引导手动重装）；泄露则他人能签发恶意更新让用户自动安装。离线异地备份，绝不进 git，绝不贴聊天记录。
- **整包更新**：安装包内置 `python-backend.exe`（约 90 MB）+ node 运行时（约 85 MB），总计 110 MB 上下，无增量、每次整包重下。国内下 GitHub 大文件可能很慢，必要时把更新源迁到国内对象存储——只需改 `tauri.conf.json` 的 endpoints 和发布脚本的上传目标，客户端代码不用动。
- **更新前停后端**：`src/services/updater.ts` 已在下载前调 `POST /internal/terminate`，避免覆盖安装时 exe 被占用而失败。
- **版本只能向前**：updater 只在 latest.json 版本更高时触发。误发了 bug 版只能再发更高版修复，不能让用户自动回退，所以**发布前的冒烟测试不能省**。
- **dev 模式测不了真安装**：`npm run tauri:dev` 下只能测「检查」这一步，下载+覆盖安装必须用安装版测。
- **静默检查的边界**：启动后 8 秒自动查一次，无新版或检查失败都不打扰用户；发现新版仍会弹确认框，用户可以选「稍后」。
- **代理环境**：开 Clash TUN 时 GitHub 可能变慢，但 updater 走普通 HTTPS，公开仓库匿名可下。

## 六、相关文件

| 文件 | 作用 |
|---|---|
| `.github/workflows/release.yml` | CI 发布流水线（构建/签名/发 Release/回验端点） |
| `tauri-app/scripts/ci_prepare_build_assets.py` | CI 前置：补齐被 gitignore 排除但打包必需的资产（空库、默认设置、node.exe） |
| `tauri-app/user_settings.default.json` | 去敏的设置模板，CI 用它生成 user_settings.json |
| `tauri-app/src-tauri/tauri.conf.json` | `plugins.updater`（公钥/更新源）、`bundle.createUpdaterArtifacts` |
| `tauri-app/src-tauri/src/main.rs` | 注册 updater / process 插件 |
| `tauri-app/src-tauri/capabilities/default.json` | `updater:default`、`process:allow-restart` 权限 |
| `tauri-app/src/services/updater.ts` | 检查/下载/安装流程（含停后端、下载进度） |
| `tauri-app/src/App.vue` | 启动后延迟静默检查 |
| `tauri-app/src/components/SettingsPanel.vue` | 「关于」tab 的版本号 + 检查更新按钮 |
| `tauri-app/package-release.ps1` | 本地打包 + 签名 + 生成 latest.json |
| `tauri-app/scripts/bump-version.ps1` | 一键统一 4 处版本号 |

## 七、排障

| 现象 | 原因与处理 |
|---|---|
| 点检查更新报错、日志显示 404 | 仓库没有正式 Release，或 latest.json 没作为 asset 上传，或 Release 是草稿/预发布 |
| 检测到新版但下载失败 404 | latest.json 里的 url 与 Release 上实际 asset 名不符——多半是 asset 名带中文被 GitHub 改成了点，改用 ASCII 名重发 |
| 下载完安装失败 | `python-backend.exe` 被占用。确认 `/internal/terminate` 生效；必要时 `Stop-Process -Name python-backend -Force` 后重试 |
| 验签失败（signature 相关报错） | 客户端内嵌的公钥与签名用的私钥不是一对。检查 `tauri.conf.json` 的 pubkey 与 Secrets 里的私钥是否配套；换过密钥的旧客户端必须手动重装 |
| CI 在「解析并校验版本号」失败 | tag 与 4 处版本号不一致。先跑 `bump-version.ps1`，提交后重新打 tag |
| CI 在「整理产物」报找不到 .sig | 两个签名 Secrets 没配或配错，`createUpdaterArtifacts` 没开 |
