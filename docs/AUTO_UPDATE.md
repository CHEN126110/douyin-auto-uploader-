# 应用内自动更新（Tauri 2 updater）操作手册

本工具已接入 Tauri 2 应用内自动更新：启动 8 秒后静默检查一次，用户也可在「设置 → ℹ️ 关于 → 检查更新」手动检测，有新版可下载安装；安装前确认后台空闲，Windows 安装程序负责关闭并重新启动应用。本文档说明**每次发版要做什么**，以及注意事项。

> 关键认知：**代码提交 ≠ 发布版本**。往 GitHub 推代码不会让用户收到更新。只有「打包 + 签名 + 发正式 Release」之后，旧客户端才检测得到新版。

## 一、更新机制（原理）

```
客户端（启动后静默 / 用户手动点检查）
  → 读取 https://github.com/CHEN126110/douyin-auto-uploader-/releases/latest/download/latest.json
  → 比对版本（latest.json 的 version > 当前 tauri.conf.json 的 version？）
  → 有新版 → 下载 setup.exe + 用内置公钥验签（此阶段后端保持运行）
  → 下载成功后才优雅停掉 python-backend（释放 exe 占用）→ 覆盖安装 → 重启
  → 安装失败则自动把后端拉回来
```

下载与安装是分开的两步（`update.download()` + `update.install()`，不是 `downloadAndInstall()`）。
整包 110 MB 从 GitHub 拉，断流和超时是常态；如果像常见写法那样先停后端再下载，一旦下载失败，
用户就停在「应用开着但采集、发布、商品列表全用不了」的状态且没有恢复入口。

- 更新源：GitHub Releases（公开仓库 `CHEN126110/douyin-auto-uploader-`）
- 签名公钥：写在 `tauri-app/src-tauri/tauri.conf.json` 的 `plugins.updater.pubkey`
- 签名私钥：`%USERPROFILE%\.tauri-keys\douyin-sock-publisher.key`，密码在同目录 `password.txt`（**仓库外，绝不进 git**）

### 密钥状态（2026-08-29 更新）

原密钥对的私钥已遗失，当天重新生成了一对，`tauri.conf.json` 的 pubkey 已同步换成新公钥（指纹 `012F530C0FE38CAA`）。

- 作废的旧公钥指纹：`DC424DADDE4EB172`。当时仓库没有任何 Release，没有线上客户端依赖它，所以换钥无损。
- 唯一影响：**曾手动拷给别人的 4.0.28 安装包内嵌的是旧公钥，那些机器验不过新签名，必须手动重装一次新版**才能接上自动更新。
- 新私钥若再丢，后果是永久性的：无法再给已装用户推任何更新。**请离线异地备份 `.tauri-keys\` 整个目录**。

## 二、发版流程（主路径：GitHub Actions）

工作流文件：[.github/workflows/release.yml](../.github/workflows/release.yml)，`windows-latest` 上完成 sidecar 打包 → 回归测试 → Tauri 构建 → 签名 → 生成 latest.json → 发布预发布候选 → 回验候选资源。通过旧版升级验收后再把候选提升为正式最新版。

### 一次性准备：配置仓库 Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret：

| Secret 名 | 值 |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | `%USERPROFILE%\.tauri-keys\douyin-sock-publisher.key` 的**文件内容**（不是路径），整段粘贴 |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | `%USERPROFILE%\.tauri-keys\password.txt` 里的那串密码 |

私钥及密码只交给签名进程或仓库 Secrets；不要打印到终端、写入构建日志或提交到仓库。

### 每次发版

```powershell
# 1. 统一升版本号（package.json / Cargo.toml / tauri.conf.json / cfg.yaml 四处）
./tauri-app/scripts/bump-version.ps1 4.0.29

# 2. 提交并打 tag 推送，Actions 自动接手
# 仅 git add 本次审查通过的源代码、配置和测试，禁止加入本地数据或浏览器资料
git commit -m "release: v4.0.29"
git tag v4.0.29
git push origin DouYin
git push origin v4.0.29
```

推 tag 后到 Actions 页面看「发布桌面端」这个工作流。全绿代表候选安装包和签名资源可下载，尚未改变正式 latest。必须完成实际升级验收后再提升为正式版本。整轮约 30–60 分钟（首次无缓存偏慢，主要花在 pip 装依赖 + PyInstaller + Rust LTO）。

也可以在 Actions 页手动触发（workflow_dispatch），需填已存在的 tag，可选填更新说明。

### 工作流做了哪些保护

- **启动链 import 自检**：装完 pip 依赖后立刻 `import` 后端启动时会用到的模块。requirements.txt 与实际 import 脱节时几秒内红掉，而不是等 PyInstaller 打完十几分钟、产出一个能装不能跑的包（PyInstaller 对缺失模块只写 WARNING，退出码仍是 0）。
- **sidecar 冒烟测试**：真的把打出来的 `python-backend.exe` 跑起来，等 `/health` 返回 200 才继续。只验证「exe 文件存在」挡不住任何运行期问题。放在 Rust 构建之前，坏包连签名环节都进不去。
- **MCP Server 依赖**：`mcp-server/node_modules` 被 gitignore 排除，但整个目录会被打进安装包。CI 里单独 `npm ci --omit=dev` 并校验依赖可解析，否则装机后内置 MCP Server 一启动就 `ERR_MODULE_NOT_FOUND`。
- **UTF-8 输出**：`windows-latest` 是 en-US 镜像（ACP=1252），Actions 把 stdout 接成管道，Python 会按 locale 编码写 stdout，脚本里的中文日志会直接 `UnicodeEncodeError` 打断 CI。job 级 `PYTHONUTF8=1` + 脚本内 `reconfigure` 双保险。
- **版本号一致性校验**：tag 与 4 处版本号任一不符立即失败，避免「界面显示一个版本、updater 按另一个判断」。
- **产物改 ASCII 名**：GitHub 上传 Release asset 时会把文件名里的中文逐个替换成 `.`，中文安装包名会让 latest.json 的下载地址 404。工作流统一改名成 `DouyinSockPublisher_<版本>_x64-setup.exe`。
- **候选优先**：`gh release create --prerelease --latest=false`，不会触发现有用户更新。验收后通过 Release API 将 `prerelease` 设为 `false`、`make_latest` 设为 `true`。候选安装包禁止自动覆盖。
- **候选回验**：读取本次 tag 下的 `latest.json`，核对版本及签名，并检查安装包地址；正式提升后另外验证公共 latest 指向同一份已测安装包。

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

## 四、版本现状与升级验收

### 当前状态（2026-10-10）

- 正式最新版：**`v4.0.29`**（`prerelease=false`、`make_latest=true`），已通过 4.0.28 → 4.0.29 真实升级验收。
- 候选阶段的三个资源在提升为正式版时**字节未变**：`DouyinSockPublisher_4.0.29_x64-setup.exe`（165,869,457 字节）、`…exe.sig`、`latest.json`。提升动作只改了 Release 元数据（标题说明）和 `latest.json` 的 `notes`，安装包与 `signature` 均未触碰。
- 本地开发机 `tauri-app/src-tauri/target/release/douyin-sock-publisher.exe` 仍是 4.0.28 的旧构建；重新编译不会自动发布，同版本也不会触发升级，要收更新必须重新构建或安装新版。

### 每次发版的验收顺序

1. 审查提交文件，只包含程序、默认配置及去敏测试证据；保留本地未选中的工作区改动。
2. 用干净的代码副本构建，`ci_prepare_build_assets.py` 生成空商品库与默认设置，禁止把开发机数据打进安装包。
3. 签名并生成候选 Release，保持正式 latest 仍指向上一个版本。
4. 在隔离安装目录执行旧版到候选包的升级，验证签名、安装覆盖、后端版本与启动，并比较测试商品和设置指纹。
5. `/internal/update-readiness` 必须显示采集、抖店发布、淘宝发布、图片处理均空闲后才停止后端安装；无法读取状态时明确拒绝安装。
6. 验收通过后提升为正式 latest，再核对公开更新清单及安装包哈希。

### 提升为正式版（候选验收通过后）

工作流只负责「发候选 + 回验候选资源」，**不会自动改 latest**：正式化是一道人工验收门。用带 `contents: write` 的令牌调 Release API 即可，两个字段都要给，缺 `make_latest` 只会去掉预发布标记、latest 仍指向旧版：

```bash
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/CHEN126110/douyin-auto-uploader-/releases/<release_id> \
  -d '{"prerelease": false, "make_latest": "true"}'
```

`latest.json` 里的 `notes` 会原样显示在用户的更新弹窗里，候选阶段写的「候选版本，等待升级验收」这类内部措辞必须在正式化前改掉。该文件是**未签名资源**，替换 `notes` 不影响安装包验签，但改名/换 URL 会让下载 404：

```bash
# 1) 删除旧 asset（必须先删，同名上传会被拒）  2) 用 uploads.github.com 同名重传
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  https://api.github.com/repos/CHEN126110/douyin-auto-uploader-/releases/assets/<asset_id>
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  --data-binary @latest.json \
  "https://uploads.github.com/repos/CHEN126110/douyin-auto-uploader-/releases/<release_id>/assets?name=latest.json"
```

提升后必须复查公共链路（不是带 tag 的地址）：

```bash
curl -sL https://github.com/CHEN126110/douyin-auto-uploader-/releases/latest/download/latest.json
# 期望 version=4.0.29、notes 为正式措辞，且 platforms.windows-x86_64.url 指向本次安装包
curl -sIL https://github.com/CHEN126110/douyin-auto-uploader-/releases/download/v4.0.29/DouyinSockPublisher_4.0.29_x64-setup.exe
# 期望 HTTP 200 且 Content-Length 与 Release 上的 asset 一致
```

Rust 壳现在和 Python 一样尊重显式 `DOUYIN_DATA_DIR`，必须是绝对路径。验收可将测试数据放入独立目录；不设置时仍使用原应用数据目录。不要指向真实商品目录做破坏性测试。

## 五、注意事项与风险

- **私钥是更新信任根**：丢了就再也无法给已装用户推更新（只能引导手动重装）；泄露则他人能签发恶意更新让用户自动安装。离线异地备份，绝不进 git，绝不贴聊天记录。
- **整包更新**：安装包包含 Python 后端及 node 运行时，体积应以每次发布的实际产物为准；当前没有增量更新，每次下载完整安装包。模型权重独立存放，不随更新包重复分发。国内下 GitHub 大文件可能很慢，必要时把更新源迁到国内对象存储——只需改 `tauri.conf.json` 的 endpoints 和发布脚本的上传目标，客户端代码不用动。
- **停后端的时机**：`src/services/updater.ts` 在**下载并验签成功之后、安装之前**检查 `/internal/update-readiness`，空闲后调用 Rust `stop_python_backend` 并确认后端已停止，避免覆盖安装时 exe 被占用而失败；安装若失败会 `invoke("start_python_backend")` 把后端拉回来。
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
| 更新时弹「打开文件 - 安全警告 / 无法验证发布者」 | Windows 附件管理器对**未签名**安装包的提示：`tauri-plugin-updater` 在 Windows 上用 `ShellExecuteW` 启动安装器（`updater.rs` 的 install 分支），本机 `HKLM\Software\Microsoft\Windows\CurrentVersion\Policies\Attachments\ScanWithAntiVirus=3` 时就会拦一次。**点「运行」即继续**，安装包随后仍要过内嵌公钥的 minisign 验签；这与版本改动无关，安装包也没有 Zone.Identifier。自动化测试里要改用 `cmd /c start`，`Start-Process` 会一直阻塞在这个对话框上 |
| 验签失败（signature 相关报错） | 客户端内嵌的公钥与签名用的私钥不是一对。检查 `tauri.conf.json` 的 pubkey 与 Secrets 里的私钥是否配套；换过密钥的旧客户端必须手动重装 |
| CI 在「解析并校验版本号」失败 | tag 与 4 处版本号不一致。先跑 `bump-version.ps1`，提交后重新打 tag |
| CI 在「整理产物」报找不到 .sig | 两个签名 Secrets 没配或配错，`createUpdaterArtifacts` 没开 |
