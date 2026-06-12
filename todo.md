# TODO — 桌面打包后续优化

## 高优先级

- [x] **ICNS 图标** — 将 `static/icon128.svg` 转为 `.icns` 格式，替换 PyInstaller spec 中的 `BUNDLE_ICON`
- [x] **首次启动引导** — 用户首次打开时引导配置 API Key（当前需手动在 `.app/Contents/MacOS/` 下创建 `.env`）
- [x] **macOS 代码签名 + 公证** — 已创建 `scripts/sign_and_package.sh`（需 Apple Developer 证书才能实际签名）

## 中优先级

- [x] **Whisper 模型下载状态** — 前端调用 `/api/model-status` 展示"模型下载中"提示，避免用户误以为卡住
- [ ] **Windows 构建验证** — 在 Windows 机器上跑 `scripts/build_windows.ps1`，确认 .exe 可正常启动
- [x] **窗口关闭确认** — 目前 `confirm_close=False`，关闭窗口即退出，考虑加一个"任务进行中"的提示

## 低优先级

- [ ] **自动更新** — macOS 用 Sparkle，Windows 用 Squirrel
- [x] **安装器** — DMG 已集成到 `scripts/sign_and_package.sh`，含 Applications 快捷方式
- [ ] **通知** — 转录完成后系统通知（pywebview 不支持原生通知，需额外处理）
- [ ] **菜单栏图标** — macOS 菜单栏常驻，窗口可关闭但服务不退出
- [ ] 绑定 TG/slack，tg发送链接，自动下载并转录，转录完成后发回文本消息。 
