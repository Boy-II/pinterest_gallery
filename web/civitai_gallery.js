import { app } from "/scripts/app.js";

// Clean, non-obfuscated replacement for the previous minified civitai_gallery.js
// bundle, which threw "checkOnLayout is not defined" and never rendered images.
// Talks to the existing /civitai_gallery/images backend route (unchanged) and
// fills the CivitaiGalleryNode's hidden "selection_data" widget with the raw
// Civitai API item the user clicked, exactly as the Python node expects:
//   { item: <civitai item>, download_image: <is "image" output wired up>, download_video: <is "video" output wired up> }

const NSFW_OPTIONS = [
    ["None", "安全 (None)"],
    ["Soft", "一般 (Soft)"],
    ["Mature", "成人 (Mature)"],
    ["X", "限制級 (X)"],
];
const SORT_OPTIONS = [
    ["Most Reactions", "最多反應"],
    ["Most Comments", "最多留言"],
    ["Newest", "最新"],
];
const PERIOD_OPTIONS = [
    ["Day", "今日"],
    ["Week", "本週"],
    ["Month", "本月"],
    ["Year", "今年"],
    ["AllTime", "所有時間"],
];
const BASE_MODEL_OPTIONS = [
    ["", "All Base Models"],
    ["Anima", "Anima"],
    ["MiniMax H3", "MiniMax H3"],
    ["Krea 2", "Krea 2"],
    ["Flux.2 Klein 9B", "Flux.2 Klein 9B"],
];

function el(tag, style, props) {
    const e = document.createElement(tag);
    if (style) Object.assign(e.style, style);
    if (props) Object.assign(e, props);
    return e;
}

function thumbUrl(url, width) {
    if (!url) return url;
    if (/\/width=\d+\//.test(url)) return url.replace(/\/width=\d+\//, `/width=${width}/`);
    if (url.includes("/original=true/")) return url.replace("/original=true/", `/width=${width}/`);
    return url;
}

function isImageOutputConnected(node) {
    const out = node.outputs && node.outputs[2];
    return !!(out && out.links && out.links.length > 0);
}

function isVideoOutputConnected(node) {
    const out = node.outputs && node.outputs[5];
    return !!(out && out.links && out.links.length > 0);
}

function isVideoItem(item) {
    return item.type === "video" || /\.(mp4|webm|mov)(\?|$)/i.test(item.url || "");
}

const selectStyle = {
    background: "#1e1e1e", color: "#ddd", border: "1px solid #555",
    borderRadius: "3px", padding: "2px 4px", fontSize: "11px",
};

function setupCivitaiGallery(node) {
    node.setSize([460, 640]);

    let selectionWidget = node.widgets?.find((w) => w.name === "selection_data");
    if (!selectionWidget) {
        selectionWidget = node.addWidget("text", "selection_data", "{}", () => {}, { serialize: true });
    }
    selectionWidget.computeSize = () => [0, -4];
    selectionWidget.draw = () => {};
    selectionWidget.type = "hidden";

    let selectedItem = null;
    const refreshSelection = () => {
        if (!selectedItem) return;
        selectionWidget.value = JSON.stringify({
            item: selectedItem,
            download_image: isImageOutputConnected(node),
            download_video: isVideoOutputConnected(node),
        });
    };
    node._civitaiRefreshSelection = refreshSelection;

    const root = el("div", {
        display: "flex", flexDirection: "column", gap: "6px", height: "100%", width: "100%",
        boxSizing: "border-box", padding: "4px", fontFamily: "sans-serif", fontSize: "11px", color: "#ddd",
    });

    const filterRow1 = el("div", { display: "flex", gap: "4px", flexWrap: "wrap" });
    const filterRow2 = el("div", { display: "flex", gap: "4px", flexWrap: "wrap" });

    const nsfwSelect = el("select", selectStyle);
    NSFW_OPTIONS.forEach(([v, l]) => nsfwSelect.appendChild(el("option", null, { value: v, textContent: l })));

    const sortSelect = el("select", selectStyle);
    SORT_OPTIONS.forEach(([v, l]) => sortSelect.appendChild(el("option", null, { value: v, textContent: l })));

    const periodSelect = el("select", selectStyle);
    PERIOD_OPTIONS.forEach(([v, l]) => periodSelect.appendChild(el("option", null, { value: v, textContent: l })));
    periodSelect.value = "Month";

    const keywordInput = el("input", { ...selectStyle, flex: "1", minWidth: "70px" }, { type: "text", placeholder: "Keyword" });
    const baseModelSelect = el("select", { ...selectStyle, flex: "1", minWidth: "110px" });
    BASE_MODEL_OPTIONS.forEach(([v, l]) => baseModelSelect.appendChild(el("option", null, { value: v, textContent: l })));

    const refreshBtn = el("button", { ...selectStyle, cursor: "pointer" }, { textContent: "🔄 Refresh" });
    const apiKeyBtn = el("button", { ...selectStyle, cursor: "pointer" }, { textContent: "🔑", title: "Civitai API Key" });

    filterRow1.append(nsfwSelect, sortSelect, periodSelect, refreshBtn, apiKeyBtn);
    filterRow2.append(keywordInput, baseModelSelect);

    const apiKeyRow = el("div", { display: "none", gap: "4px", alignItems: "center", flexWrap: "wrap" });
    const apiKeyInput = el("input", { ...selectStyle, flex: "1", minWidth: "120px" }, { type: "password", placeholder: "Civitai API Key" });
    const apiKeySaveBtn = el("button", { ...selectStyle, cursor: "pointer" }, { textContent: "儲存" });
    const apiKeyStatusEl = el("span", { opacity: "0.7" });
    apiKeyRow.append(apiKeyInput, apiKeySaveBtn, apiKeyStatusEl);

    const statusEl = el("div", { opacity: "0.7", minHeight: "14px" });

    const gridEl = el("div", {
        display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gridAutoRows: "min-content",
        gap: "4px", overflowY: "auto", overflowX: "hidden", flex: "1 1 0", minHeight: "0",
        border: "1px solid #444", borderRadius: "4px", padding: "4px", background: "#161616",
    });

    const loadMoreBtn = el("button", { ...selectStyle, cursor: "pointer", width: "100%", marginTop: "2px", display: "none" }, { textContent: "載入更多" });

    const detailEl = el("div", {
        display: "none", flexDirection: "column", gap: "4px", maxHeight: "45%",
        overflowY: "auto", border: "1px solid #444", borderRadius: "4px", padding: "6px", background: "#1c1c1c", flexShrink: "0",
    });

    root.append(filterRow1, filterRow2, apiKeyRow, statusEl, gridEl, loadMoreBtn, detailEl);

    node.addDOMWidget("civitai_gallery_ui", "div", root, { onDraw: () => {} });
    setTimeout(() => node.onResize?.(node.size), 10);

    let cursor = null;
    let loading = false;
    let allItems = [];

    function renderGrid() {
        gridEl.innerHTML = "";
        allItems.forEach((item) => gridEl.appendChild(buildThumb(item)));
        statusEl.textContent = allItems.length ? `已載入 ${allItems.length} 張圖片` : "沒有找到符合的圖片";
    }

    function buildParams() {
        const p = new URLSearchParams({
            nsfw: nsfwSelect.value,
            sort: sortSelect.value,
            period: periodSelect.value,
            domain: "civitai.red",
        });
        if (keywordInput.value.trim()) p.set("query", keywordInput.value.trim());
        if (baseModelSelect.value) p.set("baseModels", baseModelSelect.value);
        if (cursor) p.set("cursor", cursor);
        return p;
    }

    async function loadImages(reset) {
        if (loading) return;
        loading = true;
        if (reset) {
            cursor = null;
            allItems = [];
        }
        statusEl.textContent = "載入中...";
        loadMoreBtn.disabled = true;
        try {
            const res = await fetch(`/civitai_gallery/images?${buildParams().toString()}`);
            const data = await res.json();
            if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
            const items = data.items || [];
            allItems.push(...items);
            cursor = data.metadata?.nextCursor || null;
            loadMoreBtn.style.display = cursor ? "block" : "none";
            renderGrid();
        } catch (e) {
            statusEl.textContent = "❌ 讀取失敗：" + e.message;
            console.error("CivitaiGallery:", e);
        } finally {
            loading = false;
            loadMoreBtn.disabled = false;
        }
    }

    function buildThumb(item) {
        const wrap = el("div", {
            position: "relative", width: "100%", aspectRatio: "1 / 1",
            overflow: "hidden", borderRadius: "3px",
            cursor: "pointer", border: "2px solid transparent", background: "#111",
            boxSizing: "border-box",
        });
        if (item === selectedItem) wrap.style.borderColor = "#4a7";
        const media = isVideoItem(item)
            ? document.createElement("video")
            : document.createElement("img");
        Object.assign(media.style, { width: "100%", height: "100%", objectFit: "cover", display: "block" });
        if (isVideoItem(item)) {
            media.muted = true;
            media.loop = true;
            media.playsInline = true;
            media.preload = "metadata";
            media.src = item.url;
            wrap.addEventListener("mouseenter", () => media.play?.().catch(() => {}));
            wrap.addEventListener("mouseleave", () => {
                media.pause?.();
                media.currentTime = 0;
            });
        } else {
            media.loading = "lazy";
            media.src = thumbUrl(item.url, 300);
        }
        wrap.appendChild(media);
        wrap.addEventListener("click", () => selectItem(item, wrap));
        return wrap;
    }

    function selectItem(item, wrapEl) {
        selectedItem = item;
        refreshSelection();
        Array.from(gridEl.children).forEach((c) => (c.style.borderColor = "transparent"));
        if (wrapEl) wrapEl.style.borderColor = "#4a7";
        renderDetail(item);
    }

    function buildPromptBox(label, text) {
        const box = el("div", { display: "flex", flexDirection: "column", gap: "2px" });
        const row = el("div", { display: "flex", justifyContent: "space-between", alignItems: "center" });
        row.appendChild(el("div", { fontWeight: "600" }, { textContent: label }));
        const copyBtn = el("button", { ...selectStyle, padding: "1px 6px", cursor: "pointer" }, { textContent: "複製" });
        copyBtn.addEventListener("click", () => {
            navigator.clipboard?.writeText(text || "").then(() => {
                copyBtn.textContent = "已複製";
                setTimeout(() => (copyBtn.textContent = "複製"), 1200);
            }).catch(() => {});
        });
        row.appendChild(copyBtn);
        box.appendChild(row);
        const ta = el("textarea", {
            width: "100%", minHeight: "44px", resize: "vertical", background: "#111", color: "#ccc",
            border: "1px solid #333", borderRadius: "3px", fontSize: "10px", boxSizing: "border-box",
        }, { readOnly: true, value: text || "" });
        box.appendChild(ta);
        return box;
    }

    function renderDetail(item) {
        detailEl.innerHTML = "";
        detailEl.style.display = "flex";
        const meta = item.meta || {};

        detailEl.appendChild(el("div", { opacity: "0.75", fontWeight: "600" }, {
            textContent: `Base Model: ${item.baseModel || ""}`,
        }));
        detailEl.appendChild(buildPromptBox("Positive Prompt", meta.prompt));
        detailEl.appendChild(buildPromptBox("Negative Prompt", meta.negativePrompt));
    }

    async function refreshApiKeyStatus() {
        try {
            const res = await fetch("/civitai_gallery/api_key_status");
            const data = await res.json();
            apiKeyStatusEl.textContent = data.has_key ? "🔑 已設定" : "尚未設定 API Key";
        } catch (e) {
            apiKeyStatusEl.textContent = "";
        }
    }

    apiKeyBtn.addEventListener("click", () => {
        const isOpen = apiKeyRow.style.display === "flex";
        apiKeyRow.style.display = isOpen ? "none" : "flex";
        if (!isOpen) refreshApiKeyStatus();
    });

    apiKeySaveBtn.addEventListener("click", async () => {
        const key = apiKeyInput.value.trim();
        if (!key) {
            apiKeyStatusEl.textContent = "請先輸入 API Key";
            return;
        }
        apiKeyStatusEl.textContent = "儲存中...";
        try {
            const res = await fetch("/civitai_gallery/save_api_key", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ api_key: key }),
            });
            const data = await res.json();
            if (data.status === "success") {
                apiKeyStatusEl.textContent = "✅ 已儲存";
                apiKeyInput.value = "";
            } else {
                apiKeyStatusEl.textContent = "❌ " + (data.message || "儲存失敗");
            }
        } catch (e) {
            apiKeyStatusEl.textContent = "❌ " + e.message;
        }
    });

    refreshBtn.addEventListener("click", () => loadImages(true));
    loadMoreBtn.addEventListener("click", () => loadImages(false));
    [nsfwSelect, sortSelect, periodSelect].forEach((e) => e.addEventListener("change", () => loadImages(true)));
    keywordInput.addEventListener("keydown", (e) => { if (e.key === "Enter") loadImages(true); });
    baseModelSelect.addEventListener("change", () => loadImages(true));

    loadImages(true);
}

app.registerExtension({
    name: "Civitai.GalleryLite",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "CivitaiGalleryNode") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            setupCivitaiGallery(this);
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (...args) {
            onConnectionsChange?.apply(this, args);
            this._civitaiRefreshSelection?.();
        };
    },
});
