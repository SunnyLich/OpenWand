<div align="center">

<img src="../assets/doll/idle.png" width="112" alt="OpenWand 圖示" />

# OpenWand

**OpenWand 致力於成為 AI 協作的首選應用程式。不再來回切換視窗，不再反覆複製貼上。你只需要下達提示。**

OpenWand 讓 AI 在你工作時始終觸手可及。它可以自動取得上下文，也可以讓你一鍵加入所需內容。OpenWand 完全免費、跨平台、可擴充、採用寬鬆授權，並以 Python 為核心，讓你決定它如何運作，以及背後執行哪個模型。

[![平台](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-333333?style=flat-square)](#platform-status)
[![Python](https://img.shields.io/badge/python-3.12-3572A5?style=flat-square)](#quick-start)
[![本機優先](https://img.shields.io/badge/local--first-context%20and%20memory-4B8F8C?style=flat-square)](#privacy-and-control)
[![授權](https://img.shields.io/badge/license-MIT-7C3AED?style=flat-square)](#license)

**語言：** [English](README.md) | [简体中文](README.zh-CN.md) | 繁體中文 | [Français](README.fr.md) | [Español](README.es.md)

**網站：** [OpenWand 文件](https://sunnylich.github.io/OpenWand/)

[快速開始](#quick-start) | [運作方式](#how-openwand-works) | [示範](#demos) | [設定](#configuration) | [免費 API](#free-model-api-sources) | [隱私](#privacy-and-control)

![OpenWand 提示示範](readme-assets/openwand-prompt-demo.gif)

</div>

---

## 為什麼選擇 OpenWand

OpenWand 讓 AI 提示自然、無縫地融入你的工作方式，幫助你保持高效率。

### 提示流程並列比較

| 一般 AI 聊天——**8 個步驟** | OpenWand——**最快只需 2 個步驟** |
| --- | --- |
| 1. 找到並複製第一段上下文。<br>2. 切換到 AI 聊天視窗。<br>3. 貼上上下文。<br>4. 重複以上步驟，直到模型取得全部所需內容。<br>5. 輸入提示。<br>6. 傳送要求。<br>7. 等待回覆。<br>8. 閱讀回覆，再切回原來的工作。 | 1. 按下快速鍵開啟 OpenWand。<br>2. 執行預設提示。 |

你選取的文字和在設定中啟用的上下文來源會被自動收集。如有需要，額外啟用一個上下文來源也只需按一下。之後選擇預設提示，或輸入自訂提示即可。

<a id="how-openwand-works"></a>
## OpenWand 如何運作

OpenWand 讓你可以從桌面上的任何位置使用 AI。常用提示隨手可用，上下文自動收集，其他來源也能一鍵加入，讓每次要求都少走幾步。

### 向 AI 提問

**你：** 按下快速鍵 → `（加入上下文）` → 選擇可重複使用的提示或自訂提示

**OpenWand：** 收集並預覽上下文 → `（檢查隱私與提示注入）` → 詢問你選擇的模型 → 顯示答案

### 讓 AI 就地改寫

**你：** 選取文字 → 按下改寫快速鍵 → `（加入上下文）` → 選擇改寫方式 → 接受

**OpenWand：** 取得選取內容 → `（檢查隱私與提示注入）` → 產生改寫 → 顯示預覽 → 貼回原處

*括號中的操作為選用項目。*

## 亮點

- **跳過準備，直接提示。** — 從任何位置發出提示，不必操心上下文。
- **呈現更精美的答案** — 每則回覆都在本機轉換為精緻的 HTML 和 CSS，不需額外模型呼叫或費用。
- **整合 Codex 與 Claude** — 直接透過 OpenWand 執行任一代理程式。
- **隱私模式** — 可選用的敏感上下文警告與遮蔽處理。
- **高度可自訂** — 自訂快速鍵、提示、上下文、模型、語音、貼回和介面。
- **強大卻容易上手** — 輕鬆控制模型、隱私、記憶和上下文。
- **上下文最多一鍵掌控** — OpenWand 自動處理上下文，或由你一鍵加入。
- **打字並非必要** — 說出提示，也可以聆聽答案。
- **詢問畫面上的任何內容** — 框選一個區域，立即將它變成視覺上下文。
- **就地改寫** — 改寫選取文字、檢查結果，再貼回原處。
- **使用任何你想要的模型** — 支援眾多熱門雲端供應商、本機模型及任何與 OpenAI 相容的伺服器。
- **由你掌控的記憶** — 選用的短期和長期記憶保存在本機，隨時可檢視或刪除。
- **一切皆可擴充** — 透過附加元件和 MCP 加入提示、動作、快速鍵、掛鉤及模型工具。
- **讓多代理程式協作變簡單** — 透過視覺化介面和易懂的引導組建團隊，追蹤進度並檢查結果。

<a id="demos"></a>
## 示範

![OpenWand 跨應用程式上下文示範](readme-assets/openwand-context-demo.gif)

**跨應用程式上下文：** 將目前選取內容與已啟用的瀏覽器及應用程式上下文組合起來，不必手動複製貼上，就能把模型所需的資料交給它。

![OpenWand Ctrl+Alt+Q 畫面截圖示範](readme-assets/openwand-screen-snip-demo.gif)

**視覺截圖：** 當視覺上下文很重要時，按 `Ctrl+Alt+Q` 框選區域，只把該部分傳送給視覺模型，並直接在浮層中查看答案，不必切換應用程式。

![OpenWand 改寫示範](readme-assets/openwand-rewrite-demo.gif)

**就地改寫：** 只改寫選取的文字，檢查建議內容，再把接受的結果貼回呼叫 OpenWand 時處於作用中的輸入欄位。

![OpenWand 應用程式感知動作示範](readme-assets/openwand-app-aware-action-demo.gif)

**應用程式感知動作：** 利用目前應用程式的上下文分析或處理正在進行的工作，並清楚顯示結果；若沒有變更任何文件儲存格，也會明確確認。

![OpenWand 代理程式團隊示範](readme-assets/openwand-agent-task-demo.gif)

**代理程式團隊：** 將較長的工作區任務交給協調者、建置者和審查者。你繼續使用 OpenWand 時，團隊可以檢查專案檔案、完成針對性修改、執行檢查，並留下最終報告及可供審查的成果。

## 工作流程

| 你的操作 | OpenWand 的處理 |
| --- | --- |
| 標示文字、選擇上下文或框選截圖 | 只取得你選取或啟用的上下文 |
| 按下呼叫快速鍵並選擇動作或自訂提示 | 使用你的提示和所選上下文建立模型要求 |
| 傳送要求 | 直接傳送給你設定的模型供應商 |
| 等待答案 | 將回覆串流顯示在氣泡中，並可選擇自動透過 TTS 朗讀 |
| 保存日後有用的資訊 | 只在啟用記憶時將它保存在本機 |

### 常用快速操作

| 當你想要…… | 使用 OpenWand |
| --- | --- |
| **理解選取文字** | 選取文字，開啟 OpenWand，然後選擇 `What is this?` 或 `Explain simply`。 |
| **不必複製貼上即可改寫** | 選取文字，選擇改寫方式、檢查結果，再將接受的版本貼回原處。 |
| **提出自己的問題** | 輸入自訂提示。已啟用的上下文會自動附加，其他來源一鍵即可加入。 |
| **詢問畫面上的任何內容** | 按 `Ctrl+Alt+Q`，框選相關區域，並傳送給視覺模型。 |
| **不必打字即可提問** | 按住 `F9` 並說話。OpenWand 會轉錄你的要求並傳送給模型。 |
| **在任何應用程式中聽寫** | 按住 `F8` 並說話。你的話會直接出現在目前作用中的文字欄位。 |

<a id="quick-start"></a>
## 快速開始

### 下載應用程式

1. 從 [GitHub Releases](https://github.com/SunnyLich/OpenWand/releases) 下載最新版本。
2. 解壓縮並啟動 OpenWand。
3. 開啟設定並連接你的模型。

你可以先安裝 OpenWand，再選擇模型連線。如果你還沒有模型連線，可以從[超過 20 個免費及試用 API 來源](https://sunnylich.github.io/OpenWand/#free-apis)中選擇一個，或連接本機模型。

| Windows | macOS | Linux |
| --- | --- | --- |
| `OpenWand.exe` | `OpenWand.app` | `OpenWand` |

### 從原始碼執行

OpenWand 需要 Python 3.12。

```bash
git clone https://github.com/SunnyLich/OpenWand.git
cd OpenWand
```

執行適用於你平台的啟動器：

| Windows | macOS | Linux |
| --- | --- | --- |
| `Start OpenWand.bat` | `Start OpenWand.command` | `Start OpenWand.sh` |

首次啟動會設定 Python 環境並安裝相依套件。之後啟動將直接進入應用程式。

如需自行封裝 OpenWand，請參閱[建置 EXE](../docs/BUILDING_EXE.md)。

## 系統需求

| 等級 | 需求 | 適合用途 |
| --- | --- | --- |
| **最低** | Windows 10+、macOS 13+ 或 Linux X11；4 GB 記憶體；2 GB 可用磁碟空間 | 透過雲端或免費 API 使用核心浮層功能 |
| **建議** | 8 GB 以上記憶體；6 GB 以上可用磁碟空間；使用語音功能需麥克風 | 本機語音、選用的 2.8 GB 進階隱私過濾器，以及更充足的執行空間 |

本機 AI 模型可能會依模型大小需要更多記憶體、顯示記憶體和儲存空間。首次使用螢幕擷取、全域快速鍵、貼回和語音功能時，作業系統可能會要求相應權限。

<a id="configuration"></a>
## 設定

一般設定請使用「設定」視窗。`.env.example` 僅作為從原始碼進行進階設定時的參考。

1. 開啟**設定**。
2. 選擇對話引擎。
3. 連接供應商或帳戶。
4. 自訂上下文、快速鍵、語音、隱私和記憶。
5. 執行**設定檢查**。

### 選擇引擎

| 引擎 | 行為 |
| --- | --- |
| **OpenWand** | 使用 OpenWand 中設定的 LLM 供應商和模型。 |
| **ChatGPT** | 使用已安裝的 Codex CLI 和你的 ChatGPT/Codex 帳戶。 |
| **Claude Agent** | 使用 Claude Agent 和你的 Claude Code 帳戶。 |

### 代理程式控制

- **連續性** — 在 OpenWand 中繼續對話，或透過 ChatGPT 或 Claude 恢復對話。
- **即時進度** — 追蹤回覆、計畫、工具活動、檔案狀態和核准要求。
- **權限** — 變更前詢問、允許專案修改，或使用唯讀計畫模式。
- **專案範圍** — 代理程式只能在選定專案內寫入；切換專案會開始新的工作階段。
- **歷程記錄** — 匯入、選擇性同步或匯出 ChatGPT/Codex 與 Claude 對話。

### 須知

- 供應商金鑰和 OAuth 權杖保存在作業系統鑰匙圈中，而不是純文字設定檔。
- 進階來源設定記錄在 `.env.example` 中。
- 更多資訊請參閱[即時代理程式指南](https://sunnylich.github.io/OpenWand/#live-agents)，或瀏覽[免費模型 API 來源](https://sunnylich.github.io/OpenWand/#free-apis)。

## 預設快速鍵

| 快速鍵 | 動作 |
| --- | --- |
| Windows 上的 `Ctrl+Q`，macOS/Linux 上的 `Ctrl+Alt+Space` | 開啟一般動作選擇器 |
| Windows 上的 `Ctrl+Shift+Q`，macOS/Linux 上的 `Ctrl+Alt+Shift+Space` | 開啟改寫/貼上動作選擇器 |
| `Ctrl+Alt+Q` | 框選畫面區域供視覺模型使用 |
| `Alt+Q` | 將目前選取內容加入上下文緩衝區 |
| `Alt+W` | 清除上下文緩衝區 |
| `F7` | 朗讀選取文字 |
| 按住 `F9` | 錄製語音、轉錄並提問 |
| 按住 `F8` | 直接聽寫到目前文字欄位 |
| `W` / `A` / `D` | 觸發內建動作列 |
| `S` | 自訂提示模式 |
| `Esc` | 取消選擇器 |

每個呼叫器、快速鍵、標籤、提示、上下文來源、貼回設定和介面尺寸都可在設定中調整。

## 附加元件

OpenWand 具備深度擴充能力：附加元件可以帶來新功能、新工作流程和更多可能。每個附加元件在啟用前都會宣告作者及所需的 OpenWand 存取能力；只有更新擴大存取範圍時才會再次要求確認。附加元件在獨立的 Python 處理程序中執行，作者宣告的套件則安裝在專用虛擬環境中。完整程式碼附加元件仍以你的普通使用者權限執行，因此請只安裝你信任的附加元件。

在可攜式封裝版本中，如果 `OpenWand.exe` 旁的位置可寫入，OpenWand 會在該處建立 `addons` 資料夾。如果應用程式安裝在唯讀位置，請使用 **附加元件管理員 -> 開啟附加元件資料夾** 開啟備用的使用者可寫入目錄。

附加元件可以在 OpenWand 的多個環節接入：

- **上下文** - 在傳送查詢前讀取或改寫提示與上下文。
- **工具** - 註冊模型可在回答過程中呼叫的工具。
- **回覆** - 觀察已完成的回覆，以便記錄、儲存或轉送。
- **動作和快速鍵** - 加入帶有自訂提示的動作列和全域快速鍵。
- **介面** - 加入系統匣動作、設定欄位和通知。
- **LLM 動作** - 從掛鉤或快速鍵執行有上限的模型呼叫。

**附加元件能做什麼：**附加元件可以注入上下文、提供工具並回應回覆，因此擴充空間很大。以下是部分範例及其使用的掛鉤：

| 你想要…… | 掛鉤 | 資訊清單要求 |
| --- | --- | --- |
| 自動將 git diff、行事曆或開啟的工單加入提示 | 上下文（`before_query`） | `query = "modify"` |
| 為模型提供搜尋內部 Wiki、查詢資料庫、呼叫天氣或股票 API，或控制智慧家庭裝置的工具 | 工具（`get_tools`） | `tools = true`（任何套件另需 `[dependencies]`） |
| 在敏感上下文送出前進行遮蔽或標記，以符合規範要求 | 上下文（`before_query`） | `query = "modify"` |
| 將每則答案附加到每日日誌，或推送到 Notion 或 Slack | 回覆（`after_response`） | `response = "read"` |
| 加入一個由自訂提示支援的一鍵「依團隊風格改寫」動作 | 動作和快速鍵 | `[[intents]]` / `[[hotkeys]]`、`hotkeys = true` |

只要你能用 Python 編寫功能，而且它適合上述某個掛鉤點，就可以把它接入你已經在使用的快速鍵浮層。

## MCP 用戶端與伺服器

### MCP 用戶端：在 OpenWand 內使用外部伺服器

OpenWand 內附一個作為 MCP 用戶端的 **MCP bridge** 附加元件（`addons/mcp_bridge`）：在其 `servers.json` 中列出任何 [Model Context Protocol](https://modelcontextprotocol.io) 伺服器，OpenWand 就會把這些伺服器的完整工具集作為 OpenWand 工具提供給模型。這樣不必離開桌面工作流程，浮層便能使用外部 MCP 功能。完整資訊清單與掛鉤規範請參閱[附加元件指南](../addons/README.md)，也可查看[附加元件文件](https://sunnylich.github.io/OpenWand/#addons)。

### MCP 伺服器：OpenWand Context Server

OpenWand 也內附一個名為 **OpenWand Context Server** 的本機 **MCP stdio 伺服器**。Claude Desktop、Cursor 和 Codex 等受信任的 MCP 用戶端可以啟動它來讀取即時桌面上下文；OpenWand 應用程式本身不需保持開啟。

#### 工具

OpenWand Context Server 提供五個唯讀工具：

- `get_selected_text` — 桌面上目前選取的文字。
- `get_clipboard` — 剪貼簿文字。
- `get_active_window` — 目前應用程式、視窗標題，以及可用時的瀏覽器 URL。
- `read_browser_page` — 目前可見瀏覽器頁面中的文字。
- `take_screen_snip` — 主要顯示器的螢幕截圖。

#### 連接用戶端

先啟動一次 OpenWand，然後把 `addons/mcp_bridge/claude_config_snippet.json` 中的 `mcpServers` 項目複製到 MCP 用戶端設定中。OpenWand 會產生包含其自帶 Python 解譯器和 `addons/mcp_bridge/context_server.py` 正確本機路徑的片段；請勿替換成系統 Python。平台說明和疑難排解請參閱 [MCP Bridge 伺服器設定指南](../addons/mcp_bridge/README.md)。

只向你信任的用戶端註冊該伺服器：工具結果可能包含桌面上的選取文字、剪貼簿內容、瀏覽器內容和螢幕截圖。

<a id="privacy-and-control"></a>
## 隱私與控制

OpenWand 不設託管儲存層。

| 範圍 | 處理方式 |
| --- | --- |
| 本機資料 | 設定、聊天、記憶、隱私報告和組態都保留在你的裝置上。 |
| 模型要求 | 你的提示和已啟用的上下文會直接傳送給你選擇的供應商或本機伺服器。 |
| 認證資料 | 供應商金鑰和 OAuth 權杖保存在作業系統鑰匙圈中。 |
| 上下文預覽 | 來源和權杖數量估算在本機檢查，不會被傳送或儲存。 |
| 權限 | 上下文來源與模型工具分別控制；選用功能在完成設定前保持關閉。 |
| 附加元件 | 每個附加元件都在隔離處理程序中執行，並宣告其所需存取權。 |

### 隱私模式

| 模式 | 保護方式 |
| --- | --- |
| **關閉** | 不進行隱私遮蔽，直接傳送你選擇的上下文。 |
| **內建** | 在本機偵測認證資料、權杖和付款資訊等結構化機密內容。 |
| **進階** | 加入選用的本機 [OpenAI Privacy Filter](https://openai.com/index/introducing-openai-privacy-filter/)，偵測姓名、地址、私人 URL、帳戶資訊及其他敏感內容。 |

進階模式需要額外下載約 2.8 GB 的內容，並可能需要時間預熱。它可以降低意外洩露的風險，但無法保證偵測出每一項敏感資訊。

### 提示注入防護

啟用後，OpenWand 會檢查所取得文字中是否存在試圖覆寫模型指令的內容，並在傳送前讓你選擇繼續或取消。

如需回報安全漏洞，請閱讀[安全政策](../SECURITY.md)。請勿在公開 issue 中包含漏洞細節、認證資料、擷取的上下文或私密記錄檔。

<a id="platform-status"></a>
## 平台狀態

| 平台 | 狀態 |
| --- | --- |
| Windows 10+ | 支援 |
| macOS 13+ | 支援* |
| Linux X11 | 支援 |
| Linux Wayland | 進行中——目前正在開發 Wayland 支援 |

*本應用程式只在兩週的主要開發期間於 macOS 上接受過測試；之後因硬體資源有限，我無法繼續測試。如果你在 macOS 上發現錯誤，請在本儲存庫提交 issue，我會盡力修正。如果你能提供解決方案，歡迎提交 pull request。

## 說明與意見回饋

- [排解常見問題](https://sunnylich.github.io/OpenWand/#common-issues)
- [回報錯誤](https://github.com/SunnyLich/OpenWand/issues/new?template=bug_report.yml)
- [詢問設定或使用問題](https://github.com/SunnyLich/OpenWand/discussions/categories/q-a)
- [建議新功能](https://github.com/SunnyLich/OpenWand/discussions/categories/ideas)

回報錯誤時，請附上作業系統版本、啟動器、記錄檔及觸發問題的動作。記錄檔可能包含擷取的文字，請在分享前移除認證資料和個人資訊。

我們目前正在開發 Linux Wayland 支援，非常歡迎協助測試或改進。也歡迎協助測試 macOS 支援；這些平台有最多的原生整合邊緣情況，來自不同裝置、桌面環境和權限狀態的實際回報能讓 OpenWand 更好地服務所有人。

如果你希望支持本專案及其更廣泛的願景，可以直接參與開發，或在[這裡](https://buymeacoffee.com/sunnylich)捐助。

<details>
<summary>貢獻者文件</summary>

- [開發者 README](../docs/DEVELOPER_README.md) - 設定、執行階段進入點、檢查和偵錯說明。
- [程式碼概覽](../docs/OVERVIEW.md) - 子系統歸屬和執行階段邊界。
- [附加元件指南](../addons/README.md) - 附加元件資訊清單、權限、掛鉤、工具、快速鍵和封裝。
- [建置 EXE](../docs/BUILDING_EXE.md) - Windows 封裝說明。

</details>

<a id="free-model-api-sources"></a>
## 免費模型 API 來源

使用免費 API 或本機託管模型，即可零成本開始使用 OpenWand。我們的指南收錄了 20 多個免費和試用 API 來源，以及本機選項。

[瀏覽免費模型指南 →](https://sunnylich.github.io/OpenWand/#free-apis)

<a id="license"></a>
## 授權

MIT
