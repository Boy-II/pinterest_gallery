# Pinterest Gallery ComfyUI Custom Node — 設計文件

日期:2026-09-04

## 目標

開發一個 ComfyUI custom node 套件,讓使用者能在節點上直接輸入關鍵字搜尋 Pinterest,
以圖片格點瀏覽搜尋結果,點選其中一張後,節點在執行時下載該圖片的原始高畫質版本並
輸出為標準 `IMAGE` tensor(行為與內建 `LoadImage` 一致),可直接接到後續的工作流程。

## 非目標(YAGNI)

- 不支援登入 Pinterest / 存取私人 board 或個人化推薦
- 不支援一次選取多張圖片組成 batch(先做單選版本)
- 不做本地縮圖/搜尋結果的持久化快取資料庫(僅節點執行期間的記憶體暫存)
- 不使用 headless browser(Playwright/Selenium),不打包瀏覽器二進位檔
- 不做分頁按鈕,改用滾動載入更多

## 使用情境

1. 使用者在節點的搜尋框輸入關鍵字(例如「cyberpunk city」)
2. 節點下方立即顯示 Pinterest 搜尋結果的縮圖格點
3. 使用者滾動格點,接近底部時自動載入下一批結果(infinite scroll)
4. 使用者點選一張縮圖,該圖被標記為「已選中」(高亮外框)
5. Workflow 執行時,節點下載選中圖片的原始高畫質版本,輸出 `IMAGE`

## 整體架構

因為互動需要「節點內嵌圖片格點」,前端 JS 無法直接對 `pinterest.com` 發送請求
(會被 CORS 擋下,且 Pinterest 內部 API 需要特定 headers/cookie 處理),架構分兩層:

- **後端(Python)**:custom node 載入時,向 ComfyUI 的 aiohttp server(`PromptServer.instance.routes`)
  掛載兩個自訂路由:
  - `POST /pinterest_gallery/search` — 關鍵字(+ 可選的分頁 cursor)→ 回傳縮圖清單 JSON
  - `POST /pinterest_gallery/select` — 選中的圖片辨識資訊 → 回傳原始高畫質圖片下載結果(節點執行時呼叫,非 UI 呼叫;實際下載邏輯與 search 共用同一個 Pinterest client)
  這兩個路由內部用 `requests` session 模擬瀏覽器呼叫 Pinterest 的內部搜尋 API(`BaseSearchResource`)。

- **前端(JS widget)**:custom node 的 `web/` 目錄放一個 widget 腳本,在節點畫布上
  畫出「搜尋框 + 縮圖格點」,呼叫後端 search route 取得縮圖並渲染,監聽滾動事件做
  infinite scroll,使用者點選後把選中的 pin 資訊寫入節點的隱藏 widget 值(進入 workflow prompt)。

- **節點執行(Python)**:`PinterestGalleryLoader.load()` 讀取隱藏 widget 存的選中 pin
  的原始圖片 URL,下載圖片、轉成 torch tensor,輸出 `IMAGE`(與 `LoadImage` 相同的
  tensor 格式:`float32`, `[1, H, W, 3]`, 範圍 `0-1`)。

## 主要元件與檔案結構

```
pinterest_gallery/
├── __init__.py                 # NODE_CLASS_MAPPINGS、掛載 web 目錄、import server routes
├── pinterest_gallery/
│   ├── pinterest_api.py        # PinterestClient:session 初始化、search()、resolve_original_url()
│   ├── server.py                # aiohttp route handlers,註冊到 PromptServer
│   └── nodes.py                 # PinterestGalleryLoader node class
├── web/
│   └── pinterest_gallery.js     # 前端 widget:搜尋框、格點渲染、infinite scroll、選取狀態
└── pyproject.toml / requirements.txt   # 依賴:requests(Pillow/numpy/torch 由 ComfyUI 環境提供)
```

## 資料流

1. 使用者輸入關鍵字,前端 debounce 後呼叫 `POST /pinterest_gallery/search`
   body: `{ "query": "cyberpunk city", "bookmark": null }`
2. 後端 `PinterestClient.search(query, bookmark)`:
   - 若 session 尚無有效 cookie,先 GET `https://www.pinterest.com/` 取得初始 cookie(含 csrftoken)
   - 呼叫 Pinterest 內部搜尋 resource 端點,帶上必要 headers(`X-Requested-With`,
     `X-CSRFToken`,`User-Agent`,`Referer` 等)
   - 解析回傳 JSON,取出每個 pin 的 `id`、`thumbnail_url`(縮圖)、`image_url`(原始高畫質)
   - 回傳 `{ "items": [...], "bookmark": "<下一頁 cursor 或 null>" }`
3. 前端把 `items` 轉成格點內的 `<img>` 元素 append 到容器,記住回傳的 `bookmark`
4. 格點容器用 `IntersectionObserver` 監控最後一個縮圖元素,當它進入可視範圍且
   `bookmark` 不是 `null` 時,自動再呼叫一次 search(帶上該 `bookmark`),結果 append
   到尾端;呼叫期間有 loading 狀態避免重複觸發
5. 使用者點選某張縮圖:JS 把該項目的 `id` + `image_url` 存進節點的隱藏 widget
   (`selected_pin` widget,序列化成 JSON 字串,隨 workflow prompt 一起送出)
6. Workflow 執行時,`PinterestGalleryLoader.load(selected_pin)`:
   - 解析 `selected_pin` JSON 取得 `image_url`
   - 用 `requests` 下載該圖片 bytes
   - 用 `PIL.Image` 開啟、轉 RGB、轉 numpy → torch tensor,回傳 `(image,)`

## API 契約

`POST /pinterest_gallery/search`
```json
// request
{ "query": "string", "bookmark": "string | null" }
// response 200
{ "items": [ { "id": "string", "thumbnail_url": "string", "image_url": "string" } ], "bookmark": "string | null" }
// response 4xx/5xx
{ "error": "human readable message" }
```

節點的「選中原圖下載」不透過 HTTP route,而是節點 `load()` 方法內直接用
`PinterestClient`/`requests` 下載,因為此步驟只發生在 workflow 執行階段(後端),
不需要 UI 呼叫。

## 錯誤處理

- **搜尋失敗**(Pinterest 改版導致端點格式不符 / 觸發 429 / 需要登入才能看到結果):
  route 回傳 4xx/5xx + `error` 訊息,前端 widget 在格點區顯示紅字錯誤,不讓整個
  ComfyUI 前端噴錯
- **節點執行時圖片下載失敗**(選中的 URL 過期、網路錯誤):在 `load()` 內丟出
  帶清楚訊息的 exception,讓 ComfyUI 用標準的紅框節點錯誤呈現,不靜默輸出黑圖或空白圖
- 已知風險:Pinterest 內部 API 端點/參數格式可能隨時改版而失效,這不是 bug 而是
  外部相依服務的維護風險,需要之後視情況更新 `pinterest_api.py` 的請求邏輯

## 測試 / 部署

- 開發在本機(`/Volumes/Data/Hub/pinterest_gallery`,Mac,非 git repo → 需先 `git init`)
- 部署到遠端 Windows 主機 `192.168.1.180` 的 ComfyUI(`E:\ComfyUI-aki-v2\ComfyUI`,
  aki 整合包、內嵌自己的 Python)的 `custom_nodes` 目錄,透過 SSH scp/rsync 同步
- 部署前需透過 SSH 確認:
  - `custom_nodes` 的確切路徑
  - 該內嵌 Python 是否已有 `requests`(若無需另外安裝到該 embedded python 環境)
- 部署後用 `starting-comfyui-over-windows-ssh` skill 重啟 ComfyUI,實際在瀏覽器
  操作節點驗證:搜尋 → 格點顯示 → 滾動載入更多 → 選圖 → 執行 workflow 拿到 IMAGE

## 風險與限制

- Pinterest 未提供公開的第三方抓取 API,此作法屬於解析網頁內部端點,穩定性
  依賴 Pinterest 未改版;若 Pinterest 加強反爬蟲機制(如需要更嚴格的 headers、
  驗證碼),可能需要之後改用其他抓取策略
- 圖片下載/顯示需遵守 Pinterest 服務條款與著作權規範,此工具僅供個人研究/
  創作參考用途,不做商業化重新散佈
