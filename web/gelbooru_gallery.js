import { app } from "/scripts/app.js";

// Adds a Civitai-Gallery-style "save API key" row to the Gelbooru (Random)
// node: a 🔑 toggle button reveals a single credentials field (the raw
// "&api_key=...&user_id=..." string Gelbooru's account page gives you) and
// a save button, backed by /gelbooru_gallery/api_key_status and
// /gelbooru_gallery/save_api_key (config.json on the backend). The node's
// own api_credentials widget stays as an optional per-run override (and
// keeps existing saved workflows' widget order intact) — leave it blank to
// use whatever is saved here.

const rowStyle = {
    background: "#1e1e1e", color: "#ddd", border: "1px solid #555",
    borderRadius: "3px", padding: "2px 4px", fontSize: "11px",
};

function el(tag, style, props) {
    const e = document.createElement(tag);
    if (style) Object.assign(e.style, style);
    if (props) Object.assign(e, props);
    return e;
}

function setupGelbooruApiKeyUi(node) {
    const root = el("div", {
        display: "flex", flexDirection: "column", gap: "4px", width: "100%",
        boxSizing: "border-box", padding: "2px 0", fontFamily: "sans-serif", fontSize: "11px", color: "#ddd",
    });

    const toggleBtn = el("button", { ...rowStyle, cursor: "pointer", width: "100%" }, {
        textContent: "🔑 Gelbooru API Key", title: "Save your Gelbooru/Rule34 API key",
    });

    const row = el("div", { display: "none", gap: "4px", alignItems: "center", flexWrap: "wrap" });
    const credentialsInput = el("input", { ...rowStyle, flex: "1", minWidth: "180px" }, {
        type: "password", placeholder: "&api_key=...&user_id=...",
    });
    const saveBtn = el("button", { ...rowStyle, cursor: "pointer" }, { textContent: "儲存" });
    const statusEl = el("span", { opacity: "0.7" });
    row.append(credentialsInput, saveBtn, statusEl);

    root.append(toggleBtn, row);
    node.addDOMWidget("gelbooru_api_key_ui", "div", root, { onDraw: () => {} });

    async function refreshStatus() {
        try {
            const res = await fetch("/gelbooru_gallery/api_key_status");
            const data = await res.json();
            statusEl.textContent = data.has_key ? "🔑 已設定" : "尚未設定 API Key";
        } catch (e) {
            statusEl.textContent = "";
        }
    }

    toggleBtn.addEventListener("click", () => {
        const isOpen = row.style.display === "flex";
        row.style.display = isOpen ? "none" : "flex";
        if (!isOpen) refreshStatus();
    });

    saveBtn.addEventListener("click", async () => {
        const credentials = credentialsInput.value.trim();
        if (!credentials) {
            statusEl.textContent = "請貼上 &api_key=...&user_id=... 字串";
            return;
        }
        statusEl.textContent = "儲存中...";
        try {
            const res = await fetch("/gelbooru_gallery/save_api_key", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ credentials }),
            });
            const data = await res.json();
            if (data.status === "success") {
                statusEl.textContent = "✅ 已儲存";
                credentialsInput.value = "";
            } else {
                statusEl.textContent = "❌ " + (data.message || "儲存失敗");
            }
        } catch (e) {
            statusEl.textContent = "❌ " + e.message;
        }
    });
}

app.registerExtension({
    name: "Gelbooru.ApiKeyUi",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "Gelbooru (Random)") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            setupGelbooruApiKeyUi(this);
        };
    },
});
