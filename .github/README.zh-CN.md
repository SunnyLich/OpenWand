<div align="center">

<img src="../assets/doll/idle.png" width="112" alt="OpenWand 图标" />

# OpenWand

**OpenWand 致力于成为 AI 协作的首选应用。不再来回切换窗口，不再反复复制粘贴。你只需要提出问题。**

OpenWand 让 AI 在你工作时始终触手可及。它可以自动获取上下文，也可以让你一键添加所需内容。OpenWand 完全免费、跨平台、可扩展、采用宽松许可证，并以 Python 为核心，让你决定它如何工作，以及背后运行哪个模型。

[![平台](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-333333?style=flat-square)](#platform-status)
[![Python](https://img.shields.io/badge/python-3.12-3572A5?style=flat-square)](#quick-start)
[![本地优先](https://img.shields.io/badge/local--first-context%20and%20memory-4B8F8C?style=flat-square)](#privacy-and-control)
[![许可证](https://img.shields.io/badge/license-MIT-7C3AED?style=flat-square)](#license)

**语言：** [English](README.md) | 简体中文 | [繁體中文](README.zh-TW.md) | [Français](README.fr.md) | [Español](README.es.md)

**网站：** [OpenWand 文档](https://sunnylich.github.io/OpenWand/)

[快速开始](#quick-start) | [工作原理](#how-openwand-works) | [演示](#demos) | [配置](#configuration) | [免费 API](#free-model-api-sources) | [隐私](#privacy-and-control)

![OpenWand 提示词演示](readme-assets/openwand-prompt-demo.gif)

</div>

---

## 为什么选择 OpenWand

OpenWand 让 AI 提示自然、无缝地融入你的工作方式，帮助你保持高效。

### 提示流程对比

| 普通 AI 聊天——**8 步** | OpenWand——**最快只需 2 步** |
| --- | --- |
| 1. 找到并复制第一段上下文。<br>2. 切换到 AI 聊天窗口。<br>3. 粘贴上下文。<br>4. 重复以上步骤，直到模型获得全部所需内容。<br>5. 输入提示词。<br>6. 发送请求。<br>7. 等待回复。<br>8. 阅读回复，再切回原来的工作。 | 1. 按下快捷键打开 OpenWand。<br>2. 运行预设提示词。 |

你选中的文字和在设置中启用的上下文来源会被自动收集。如有需要，额外启用一个上下文来源也只需一次点击。之后选择预设提示词，或输入自定义提示词即可。

<a id="how-openwand-works"></a>
## OpenWand 如何工作

OpenWand 让你可以从桌面上的任何位置使用 AI。常用提示词随手可用，上下文自动收集，其他来源也能一键加入，让每次请求都少走几步。

### 向 AI 提问

**你：** 按下快捷键 → `（添加上下文）` → 选择可复用提示词或自定义提示词

**OpenWand：** 收集并预览上下文 → `（检查隐私与提示注入）` → 请求你选择的模型 → 显示答案

### 让 AI 就地改写

**你：** 选中文字 → 按下改写快捷键 → `（添加上下文）` → 选择改写方式 → 接受

**OpenWand：** 获取选中内容 → `（检查隐私与提示注入）` → 生成改写 → 显示预览 → 粘贴回原处

*括号中的操作为可选项。*

## 亮点

- **跳过准备，直接提问。** — 从任何位置发起提示，无需操心上下文。
- **更精美的答案呈现** — 每条回复都在本地转换为精致的 HTML 和 CSS，无需额外模型调用或费用。
- **集成 Codex 与 Claude** — 直接通过 OpenWand 运行任一智能体。
- **隐私模式** — 可选的敏感上下文警告与脱敏处理。
- **高度可定制** — 自定义快捷键、提示词、上下文、模型、语音、粘贴回写和界面。
- **强大却易上手** — 轻松控制模型、隐私、记忆和上下文。
- **上下文最多一键掌控** — OpenWand 自动处理上下文，或由你一键添加。
- **输入文字并非必需** — 说出提示词，也可以听取答案。
- **询问屏幕上的任何内容** — 框选一个区域，立即将其变成视觉上下文。
- **就地改写** — 改写选中文字，检查结果，再粘贴回原处。
- **使用任何你想要的模型** — 支持众多主流云端提供商、本地模型及任何兼容 OpenAI 的服务器。
- **由你掌控的记忆** — 可选的短期和长期记忆保存在本地，随时可查看或删除。
- **一切皆可扩展** — 通过插件和 MCP 添加提示词、操作、快捷键、钩子及模型工具。
- **让多智能体协作变简单** — 通过可视化界面和易懂的引导组建团队，跟进进度并检查结果。

<a id="demos"></a>
## 演示

<table>
  <tr><td>
    <img src="readme-assets/openwand-context-demo.gif" alt="OpenWand 跨应用上下文演示" />
    <p><strong>跨应用上下文：</strong> 将当前选中内容与已启用的浏览器和应用上下文组合起来，无需手动复制粘贴，就能把模型所需的信息交给它。</p>
  </td></tr>
  <tr><td>
    <img src="readme-assets/openwand-screen-snip-demo.gif" alt="OpenWand Ctrl+Alt+Q 屏幕截图演示" />
    <p><strong>视觉截图：</strong> 当视觉上下文很重要时，按 <code>Ctrl+Alt+Q</code> 框选区域，只把该部分发送给视觉模型，并直接在浮层中查看答案，无需切换应用。</p>
  </td></tr>
  <tr><td>
    <img src="readme-assets/openwand-rewrite-demo.gif" alt="OpenWand 改写演示" />
    <p><strong>就地改写：</strong> 仅改写选中的文字，检查建议内容，再将接受的结果粘贴回调用 OpenWand 时处于活动状态的输入框。</p>
  </td></tr>
  <tr><td>
    <img src="readme-assets/openwand-app-aware-action-demo.gif" alt="OpenWand 应用感知操作演示" />
    <p><strong>应用感知操作：</strong> 利用当前应用的上下文分析或处理正在进行的工作，并清楚显示结果；如果没有更改任何文档单元格，也会明确确认。</p>
  </td></tr>
  <tr><td>
    <img src="readme-assets/openwand-agent-task-demo.gif" alt="OpenWand 智能体团队演示" />
    <p><strong>智能体团队：</strong> 将较长的工作区任务交给协调者、构建者和审查者。你继续使用 OpenWand 时，团队可以检查项目文件、完成针对性修改、运行检查，并留下最终报告及可供审查的成果。</p>
  </td></tr>
</table>

## 工作流程

| 你的操作 | OpenWand 的处理 |
| --- | --- |
| 高亮文字、选择上下文或框选截图 | 仅获取你选中或启用的上下文 |
| 按下调用快捷键并选择操作或自定义提示词 | 使用你的提示词和所选上下文构建模型请求 |
| 发送请求 | 直接发送给你配置的模型提供商 |
| 等待答案 | 将回复流式显示在气泡中，并可选择自动通过 TTS 朗读 |
| 保存以后有用的信息 | 仅在启用记忆时将其保存在本地 |

### 常用快捷操作

| 当你想要…… | 使用 OpenWand |
| --- | --- |
| **理解选中文字** | 选中文字，打开 OpenWand，然后选择 `What is this?` 或 `Explain simply`。 |
| **无需复制粘贴即可改写** | 选中文字，选择改写方式，检查结果，再将接受的版本粘贴回原处。 |
| **提出自己的问题** | 输入自定义提示词。已启用的上下文会自动附加，其他来源一键即可加入。 |
| **询问屏幕上的任何内容** | 按 `Ctrl+Alt+Q`，框选相关区域，并发送给视觉模型。 |
| **无需打字即可提问** | 按住 `F9` 并说话。OpenWand 会转录你的请求并发送给模型。 |
| **在任何应用中听写** | 按住 `F8` 并说话。你的话会直接出现在当前活动的文本框中。 |

<a id="quick-start"></a>
## 快速开始

### 下载应用

1. 从 [GitHub Releases](https://github.com/SunnyLich/OpenWand/releases) 下载最新版本。
2. 解压并启动 OpenWand。
3. 打开设置并连接你的模型。

你可以先安装 OpenWand，再选择模型连接。如果你还没有模型连接，可以从[超过 20 个免费及试用 API 来源](https://sunnylich.github.io/OpenWand/#free-apis)中选择一个，或连接本地模型。

| Windows | macOS | Linux |
| --- | --- | --- |
| `OpenWand.exe` | `OpenWand.app` | `OpenWand` |

### 从源代码运行

OpenWand 需要 Python 3.12。

```bash
git clone https://github.com/SunnyLich/OpenWand.git
cd OpenWand
```

运行适用于你平台的启动器：

| Windows | macOS | Linux |
| --- | --- | --- |
| `Start OpenWand.bat` | `Start OpenWand.command` | `Start OpenWand.sh` |

首次启动会配置 Python 环境并安装依赖项。之后启动将直接进入应用。

如需自行打包 OpenWand，请参阅[构建 EXE](../docs/BUILDING_EXE.md)。

## 系统要求

| 级别 | 要求 | 适合用途 |
| --- | --- | --- |
| **最低** | Windows 10+、macOS 13+ 或 Linux X11；4 GB 内存；2 GB 可用磁盘空间 | 通过云端或免费 API 使用核心浮层功能 |
| **推荐** | 8 GB 以上内存；6 GB 以上可用磁盘空间；使用语音功能需麦克风 | 本地语音、可选的 2.8 GB 高级隐私过滤器，以及更充足的运行空间 |

本地 AI 模型可能会根据模型大小需要更多内存、显存和存储空间。首次使用屏幕捕获、全局快捷键、粘贴回写和语音功能时，操作系统可能会请求相应权限。

<a id="configuration"></a>
## 配置

常规设置请使用“设置”窗口。`.env.example` 仅作为从源码进行高级配置时的参考。

1. 打开**设置**。
2. 选择对话引擎。
3. 连接提供商或账户。
4. 自定义上下文、快捷键、语音、隐私和记忆。
5. 运行**设置检查**。

### 选择你的执行框架

| 执行框架 | 行为 |
| --- | --- |
| **OpenWand** | 使用 OpenWand 中配置的 LLM 提供商和模型。 |
| **ChatGPT** | 使用已安装的 Codex CLI 和你的 ChatGPT/Codex 账户。 |
| **Claude Agent** | 使用 Claude Agent 和你的 Claude Code 账户。 |

### 智能体控制

- **连续性** — 在 OpenWand 中继续对话，或通过 ChatGPT 或 Claude 恢复对话。
- **实时进度** — 跟进回复、计划、工具活动、文件状态和批准请求。
- **权限** — 更改前询问、允许项目修改，或使用只读计划模式。
- **项目范围** — 智能体只能在选定项目内写入；切换项目会开始新的会话。
- **历史记录** — 导入、选择性同步或导出 ChatGPT/Codex 与 Claude 对话。

### 须知

- 提供商密钥和 OAuth 令牌保存在操作系统钥匙串中，而不是纯文本配置文件。
- 高级来源设置记录在 `.env.example` 中。
- 更多信息请参阅[实时智能体指南](https://sunnylich.github.io/OpenWand/#live-agents)，或浏览[免费模型 API 来源](https://sunnylich.github.io/OpenWand/#free-apis)。

## 默认快捷键

| 快捷键 | 操作 |
| --- | --- |
| Windows 上的 `Ctrl+Q`，macOS/Linux 上的 `Ctrl+Alt+Space` | 打开通用操作选择器 |
| Windows 上的 `Ctrl+Shift+Q`，macOS/Linux 上的 `Ctrl+Alt+Shift+Space` | 打开改写/粘贴操作选择器 |
| `Ctrl+Alt+Q` | 框选屏幕区域供视觉模型使用 |
| `Alt+Q` | 将当前选中内容添加到上下文缓冲区 |
| `Alt+W` | 清空上下文缓冲区 |
| `F7` | 朗读选中文字 |
| 按住 `F9` | 录制语音、转录并提问 |
| 按住 `F8` | 直接听写到当前文本框 |
| `W` / `A` / `D` | 触发内置操作行 |
| `S` | 自定义提示词模式 |
| `Esc` | 取消选择器 |

每个调用器、快捷键、标签、提示词、上下文来源、粘贴回写设置和界面尺寸都可在设置中配置。

## 插件

OpenWand 具有深度扩展能力：插件可以带来新功能、新工作流程和更多可能。每个插件在启用前都会声明作者及所需的 OpenWand 访问能力；只有更新扩大访问范围时才会再次请求确认。插件在独立的 Python 进程中运行，作者声明的软件包则安装在专用虚拟环境中。完整代码插件仍以你的普通用户权限运行，因此请只安装你信任的插件。

在便携打包版本中，如果 `OpenWand.exe` 旁的位置可写，OpenWand 会在那里创建 `addons` 文件夹。如果应用安装在只读位置，请使用 **插件管理器 -> 打开插件文件夹** 打开备用的用户可写插件目录。

插件可以在 OpenWand 的多个环节接入：

- **上下文** - 在发送查询前读取或改写提示词与上下文。
- **工具** - 注册模型可在回答过程中调用的工具。
- **回复** - 观察已完成的回复，以便记录、保存或转发。
- **操作和快捷键** - 添加带有自定义提示词的操作行和全局快捷键。
- **界面** - 添加托盘操作、设置字段和通知。
- **LLM 操作** - 从钩子或快捷键运行有上限的模型调用。

**插件能做什么：**插件可以注入上下文、提供工具并响应回复，因此扩展空间很大。以下是部分示例及其使用的钩子：

| 你想要…… | 钩子 | 清单要求 |
| --- | --- | --- |
| 自动将 git diff、日历或打开的工单加入提示词 | 上下文（`before_query`） | `query = "modify"` |
| 为模型提供搜索内部 Wiki、查询数据库、调用天气或股票 API，或控制智能家居设备的工具 | 工具（`get_tools`） | `tools = true`（任何软件包另需 `[dependencies]`） |
| 在敏感上下文发出前进行脱敏或标记，以满足合规需求 | 上下文（`before_query`） | `query = "modify"` |
| 将每条答案追加到每日日志，或推送到 Notion 或 Slack | 回复（`after_response`） | `response = "read"` |
| 添加一个由自定义提示词支持的一键“按团队风格改写”操作 | 操作和快捷键 | `[[intents]]` / `[[hotkeys]]`、`hotkeys = true` |

只要你能用 Python 编写功能，并且它适合上述某个钩子点，就可以把它接入你已经在使用的快捷键浮层。

## MCP 客户端与服务器

### MCP 客户端：在 OpenWand 内使用外部服务器

OpenWand 自带一个作为 MCP 客户端的 **MCP bridge** 插件（`addons/mcp_bridge`）：在其 `servers.json` 中列出任意 [Model Context Protocol](https://modelcontextprotocol.io) 服务器，OpenWand 就会把这些服务器的完整工具集作为 OpenWand 工具提供给模型。这样无需离开桌面工作流程，浮层便能使用外部 MCP 能力。完整清单与钩子约定请参阅[插件指南](../addons/README.md)，也可查看[插件文档](https://sunnylich.github.io/OpenWand/#addons)。

### MCP 服务器：OpenWand Context Server

OpenWand 还自带一个名为 **OpenWand Context Server** 的本地 **MCP stdio 服务器**。Claude Desktop、Cursor 和 Codex 等可信 MCP 客户端可以启动它来读取实时桌面上下文；OpenWand 应用本身无需保持打开。

#### 工具

OpenWand Context Server 提供五个只读工具：

- `get_selected_text` — 桌面上当前选中的文字。
- `get_clipboard` — 剪贴板文字。
- `get_active_window` — 当前应用、窗口标题，以及可用时的浏览器 URL。
- `read_browser_page` — 当前可见浏览器页面中的文字。
- `take_screen_snip` — 主显示器的屏幕截图。

#### 连接客户端

先启动一次 OpenWand，然后把 `addons/mcp_bridge/claude_config_snippet.json` 中的 `mcpServers` 条目复制到 MCP 客户端配置中。OpenWand 会生成包含其自带 Python 解释器和 `addons/mcp_bridge/context_server.py` 正确本地路径的片段；请勿替换为系统 Python。平台说明和故障排除请参阅 [MCP Bridge 服务器设置指南](../addons/mcp_bridge/README.md)。

只向你信任的客户端注册该服务器：工具结果可能包含桌面上的选中文字、剪贴板内容、浏览器内容和屏幕截图。

<a id="privacy-and-control"></a>
## 隐私与控制

OpenWand 不设托管存储层。

| 范围 | 处理方式 |
| --- | --- |
| 本地数据 | 设置、聊天、记忆、隐私报告和配置均保留在你的设备上。 |
| 模型请求 | 你的提示词和已启用的上下文会直接发送给你选择的提供商或本地服务器。 |
| 凭据 | 提供商密钥和 OAuth 令牌保存在操作系统钥匙串中。 |
| 上下文预览 | 来源和令牌估算在本地检查，不会被发送或保存。 |
| 权限 | 上下文来源与模型工具分别控制；可选功能在完成配置前保持关闭。 |
| 插件 | 每个插件都在隔离进程中运行，并声明其所需访问权限。 |

### 隐私模式

| 模式 | 保护方式 |
| --- | --- |
| **关闭** | 不进行隐私脱敏，直接发送你选择的上下文。 |
| **内置** | 在本地检测凭据、令牌和付款信息等结构化机密内容。 |
| **高级** | 添加可选的本地 [OpenAI Privacy Filter](https://openai.com/index/introducing-openai-privacy-filter/)，检测姓名、地址、私有 URL、账户信息及其他敏感内容。 |

高级模式需要额外下载约 2.8 GB 的内容，并可能需要时间预热。它可以降低意外泄露的风险，但无法保证检测出每一项敏感信息。

### 提示注入防护

启用后，OpenWand 会检查所获取文字中是否存在试图覆盖模型指令的内容，并在发送前让你选择继续或取消。

如需报告安全漏洞，请阅读[安全政策](../SECURITY.md)。请勿在公开 issue 中包含漏洞细节、凭据、捕获的上下文或私密日志。

<a id="platform-status"></a>
## 平台状态

| 平台 | 状态 |
| --- | --- |
| Windows 10+ | 支持 |
| macOS 13+ | 支持* |
| Linux X11 | 支持 |
| Linux Wayland | 进行中——目前正在开发 Wayland 支持 |

*本应用仅在两周的主要开发期间于 macOS 上接受过测试；此后因硬件条件有限，我无法继续测试。如果你在 macOS 上发现错误，请在本仓库提交 issue，我会尽力修复。如果你能提供解决方案，欢迎提交 pull request。

## 帮助与反馈

- [排查常见问题](https://sunnylich.github.io/OpenWand/#common-issues)
- [报告错误](https://github.com/SunnyLich/OpenWand/issues/new?template=bug_report.yml)
- [询问设置或使用问题](https://github.com/SunnyLich/OpenWand/discussions/categories/q-a)
- [建议新功能](https://github.com/SunnyLich/OpenWand/discussions/categories/ideas)

报告错误时，请附上操作系统版本、启动器、日志及触发问题的操作。日志可能包含捕获的文字，请在分享前删除凭据和个人信息。

我们目前正在开发 Linux Wayland 支持，非常欢迎协助测试或改进。也欢迎帮助测试 macOS 支持；这些平台存在最多的原生集成边缘情况，来自不同设备、桌面环境和权限状态的真实反馈能让 OpenWand 更好地服务所有人。

如果你希望支持本项目及其更广泛的愿景，可以直接参与开发，或在[这里](https://buymeacoffee.com/sunnylich)捐助。

<details>
<summary>贡献者文档</summary>

- [开发者 README](../docs/DEVELOPER_README.md) - 设置、运行时入口、检查和调试说明。
- [代码概览](../docs/OVERVIEW.md) - 子系统归属和运行时边界。
- [插件指南](../addons/README.md) - 插件清单、权限、钩子、工具、快捷键和打包。
- [构建 EXE](../docs/BUILDING_EXE.md) - Windows 打包说明。

</details>

<a id="free-model-api-sources"></a>
## 免费模型 API 来源

使用免费 API 或本地托管模型，即可零成本开始使用 OpenWand。我们的指南收录了 20 多个免费和试用 API 来源，以及本地选项。

[浏览免费模型指南 →](https://sunnylich.github.io/OpenWand/#free-apis)

<a id="license"></a>
## 许可证

MIT
