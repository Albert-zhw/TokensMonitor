<div align="center">

# 🪙 TokensMonitor

**把散落在各个 AI 平台的余额与用量，收进一张清爽的卡片面板**

一站式监控 ChatGPT / DeepSeek / 智谱 / MiniMax / 硅基流动 / Moonshot / OpenRouter / AtomCode 等平台的
余额、套餐额度、今日消费、请求次数与 Token 消耗 —— 每分钟自动刷新，电脑手机都能看。

[![License](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)]()
[![Python](https://img.shields.io/badge/Python-3.8+-green.svg)]()

**[⬇ 下载 EXE](#-快速开始) · [🚀 快速开始](#-快速开始) · [🧩 支持平台](#-支持平台) · [❓FAQ](#-faq)**

</div>

---

## ✨ 为什么做这个

如果你同时用着好几个 AI 平台——这个充了值、那个领了套餐、还有一个按量计费——
你大概每天都要挨个打开网页看一眼还剩多少。

**TokensMonitor 把这件事变成打开一个网页**：

- 💳 **一屏总览**：所有平台的余额、额度、今日消费，卡片式陈列
- 🔄 **自动刷新**：每分钟后台静默更新，数据永远新鲜
- 📶 **5h / 周额度进度条**：类官方风格的用量窗口展示
- 📱 **跨设备访问**：手机、平板连同一 WiFi 直接打开
- 🔐 **可视化配置**：填 key 像填表一样简单，每个字段都有取值指引
- 🛡 **断网兜底**：查询失败时自动展示上次数据，绝不闪红报错

## 🚀 快速开始

### 方式一：开箱即用（推荐）

1. 从 [Releases](../../releases) 下载 `TokensMonitor-v1.0-win64.zip`
2. 解压后**双击 `TokensMonitor.exe`**
3. 浏览器自动打开面板 → 首次进入设置页时**设置一个管理口令**
4. 点击「＋ 添加」选择平台，按字段旁的 **？** 提示填入 key —— 完成！

> 程序会常驻系统托盘（🪙 图标）：左键打开面板，右键退出。
> 想让手机也能看？手机连同一 WiFi，浏览器输入电脑 IP + 端口即可。

### 方式二：源码运行

```bash
git clone <本仓库地址>
cd TokensMonitor
python server.py          # 仅需 Python 3.8+，零第三方依赖
```

浏览器打开 `http://127.0.0.1:8787` 即可。

## 🧩 支持平台

| 平台 | 展示内容 | 凭证 | 自动续期 |
|---|---|---|---|
| **ChatGPT（Codex）** | 套餐、5h/周额度、重置次数 | 本机 Codex 登录态 | ✅ 全自动 |
| **DeepSeek** | 余额、今日消费/请求/Token、累计消费 | API Key + 网页 Token | 部分 |
| **智谱 BigModel** | GLM Coding Plan 5h/周额度进度条 | API Key | — |
| **MiniMax** | 通用/视频双模型 5h/周额度 | Token Plan Key | — |
| **硅基流动** | 余额、已用、充值、今日消费/用量 | 控制台 Cookie | — |
| **Moonshot（Kimi）** | 余额、代金券 | API Key | — |
| **OpenRouter** | 额度、已用（USD） | API Key | — |
| **AtomCode** | 今日 Token、5h 窗口、7 天用量、套餐 | GitCode Cookie | — |
| **SISCT / VoAPI 系** | 余额、今日消费/请求/Token、平均响应 | JWT + 账密 | ✅ 全自动 |
| **AI STORE** | 积分余额、当日请求/积分/Token、成功率 | Cookie | — |
| **自定义接口** | 任意能返回 JSON 的余额接口 | 自定义 | — |

> 💡 新平台适配超简单：在 `server.py` 写一个探针函数注册进 `PROBERS`，
> 在 `settings.html` 的 `FIELDS` 加几行表单定义 —— 欢迎提 PR！

## 🖥 界面预览

```
┌─────────────────────────┐  ┌─────────────────────────┐
│ ● DeepSeek    [deepseek]│  │ ● SISCT2API     [sisct] │
│                         │  │                         │
│ ¥5.53 余额              │  │ $13.70 余额             │
│ ┌──────────┐┌─────────┐│  │ ┌──────────┐┌─────────┐│
│ │今日请求 0││消费 ¥0  ││  │ │今日请求 6││消费 $1.4││
│ └──────────┘└─────────┘│  │ └──────────┘└─────────┘│
│ ┌──────────┐┌─────────┐│  │ ┌──────────┐┌─────────┐│
│ │Token 138 ││累计 ¥4.5││  │ │Token 34K ││响应 26s ││
│ └──────────┘└─────────┘│  │ └──────────┘└─────────┘│
└─────────────────────────┘  └─────────────────────────┘
┌─────────────────────────┐
│ ● MiniMax  [minimax]    │
│ 5小时用量 ▓▓▓░░░░░ 15% │
│          4 小时后重置   │
│ 周额度   ▓▓▓▓▓░░░ 14%  │
│          4 天后重置     │
└─────────────────────────┘
```

- 🌗 深色 / 浅色主题一键切换
- 🎯 卡片拖动排序（配置页与前台实时同步）
- ⭕ 托盘常驻：左键打开面板，右键退出

## ⚙️ 配置速查

所有配置通过**可视化设置页**完成（地址 `/ssseetinnggg`，首次进入设置口令）。
每个字段旁的 **？** 按钮都有详细的取值指引。

<details>
<summary><b>手动编辑 config.json（高级）</b></summary>

```jsonc
{
  "host": "0.0.0.0",              // 0.0.0.0 允许局域网访问
  "port": 8787,
  "refresh_seconds": 60,          // 自动刷新间隔
  "title": "TokensMonitor",       // 页面标题，随意改
  "settings_password": "******",  // 设置页口令
  "proxy": "",                    // 可选出站代理，失败自动回退直连
  "accounts": [
    { "name": "DeepSeek", "type": "deepseek", "key": "sk-xxx" },
    { "name": "智谱", "type": "zhipu", "key": "xxx.yyy" },
    { "name": "ChatGPT", "type": "codex" },
    { "name": "SISCT", "type": "sisct",
      "base_url": "https://api.example.com",
      "key": "eyJ...",
      "auto_login": true,
      "creds": { "email": "a@b.c", "password": "***" } },
    { "name": "任意站", "type": "custom",
      "base_url": "https://example.com",
      "query": { "path": "/api/balance",
                 "balance": { "path": "data.money" } } }
  ]
}
```

</details>

## ❓ FAQ

<details>
<summary><b>Token / Cookie 过期了怎么办？</b></summary>

卡片报错时按字段旁 **？** 的指引重新抓取一次并保存即可（约 30 秒）。
ChatGPT（Codex）与开启「失效自动登录」的平台会自动续期，无需操心。
</details>

<details>
<summary><b>数据安全吗？</b></summary>

所有密钥仅保存在**本机** `config.json`，程序不收集不上传。
服务只监听局域网，公网暴露需自行配置端口映射（不建议）。
建议：勿分享 config.json、勿提交到 git（`.gitignore` 已帮你排除）、电脑设置开机密码。
</details>

<details>
<summary><b>手机怎么看？</b></summary>

手机连同一 WiFi，浏览器打开 `http://电脑IP:8787`（电脑 IP 用 `ipconfig` 查看）。
可「添加到主屏幕」当 App 用。
</details>

<details>
<summary><b>端口被占用了？</b></summary>

修改 `config.json` 的 `port` 字段；托盘程序启动时也会自动检测并直接打开已运行的实例。
</details>

## 🛠 技术实现

- **后端**：Python 标准库 `http.server`，零第三方依赖，单文件即可运行
- **并发探测**：ThreadPoolExecutor 并行查询全部平台，互不阻塞
- **三级容错**：探测失败 → 自动重试 → 上次成功数据兜底（黄点提示），绝不闪错
- **智能网络**：直连优先，失败自动走代理重试，适配各种网络环境
- **前端**：原生 HTML/CSS/JS 单文件，无框架无构建，深浅双主题
- **打包**：PyInstaller 单文件 EXE，托盘常驻（pystray）

```
TokensMonitor/
├── server.py          # 后端服务 + 各平台探针适配器
├── tray_app.py        # 托盘启动器
├── static/            # 前台面板 + 可视化设置页
├── build_exe.bat      # 一键打包 EXE
└── config.json        # 你的配置（首次运行自动生成，已被 .gitignore 排除）
```

## 🤝 贡献

欢迎提交新平台适配器！三步搞定：

1. `server.py` 中实现 `probe_xxx(acc)` 探针函数（参考 `probe_deepseek`）
2. 注册进 `PROBERS` 字典
3. `static/settings.html` 的 `FIELDS` 中添加表单字段定义

Issue / PR 均欢迎 🎉

## 📄 许可证

本项目基于 [GPL-3.0](LICENSE) 开源 —— 自由使用、自由修改、衍生作品同样开源。

---

<div align="center">

**如果对你有帮助，欢迎点个 ⭐ Star**

</div>
