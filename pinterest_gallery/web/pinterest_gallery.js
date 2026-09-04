import { app } from "../../scripts/app.js";

const CSS = `
.pinterest-gallery-wrap { display:flex; flex-direction:column; gap:4px; width:100%; }
.pinterest-gallery-search { width:100%; box-sizing:border-box; }
.pinterest-gallery-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:4px; max-height:260px; overflow-y:auto; background:#1a1a1a; padding:4px; border-radius:4px; }
.pinterest-gallery-thumb { width:100%; aspect-ratio:1/1; object-fit:cover; cursor:pointer; border:2px solid transparent; border-radius:3px; display:block; }
.pinterest-gallery-thumb.selected { border-color:#4caf50; }
.pinterest-gallery-status { font-size:11px; color:#aaa; min-height:14px; }
`;

function injectCss() {
  if (document.getElementById("pinterest-gallery-css")) return;
  const style = document.createElement("style");
  style.id = "pinterest-gallery-css";
  style.textContent = CSS;
  document.head.appendChild(style);
}

app.registerExtension({
  name: "pinterest_gallery.widget",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "PinterestGalleryLoader") return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);
      injectCss();

      const node = this;
      const selectedWidget = node.widgets.find((w) => w.name === "selected_pin");
      if (selectedWidget) {
        // Keep it as a real serialized widget (so its value ships with the
        // prompt) but stop LiteGraph from drawing/sizing it.
        selectedWidget.computeSize = () => [0, -4];
        selectedWidget.draw = () => {};
      }

      const wrap = document.createElement("div");
      wrap.className = "pinterest-gallery-wrap";

      const input = document.createElement("input");
      input.className = "pinterest-gallery-search";
      input.type = "text";
      input.placeholder = "Search Pinterest...";

      const status = document.createElement("div");
      status.className = "pinterest-gallery-status";

      const grid = document.createElement("div");
      grid.className = "pinterest-gallery-grid";

      const sentinel = document.createElement("div");
      sentinel.style.height = "1px";
      grid.appendChild(sentinel);

      wrap.appendChild(input);
      wrap.appendChild(status);
      wrap.appendChild(grid);

      let currentQuery = "";
      let bookmark = null;
      let loading = false;
      let debounceTimer = null;

      const setSelected = (item, imgEl) => {
        grid
          .querySelectorAll(".pinterest-gallery-thumb.selected")
          .forEach((el) => el.classList.remove("selected"));
        imgEl.classList.add("selected");
        if (selectedWidget) {
          selectedWidget.value = JSON.stringify({
            id: item.id,
            image_url: item.image_url,
          });
        }
      };

      const addItems = (items) => {
        for (const item of items) {
          const img = document.createElement("img");
          img.className = "pinterest-gallery-thumb";
          img.src = item.thumbnail_url;
          img.loading = "lazy";
          img.addEventListener("click", () => setSelected(item, img));
          grid.insertBefore(img, sentinel);
        }
      };

      const runSearch = async (query, nextBookmark) => {
        if (loading) return;
        loading = true;
        status.textContent = "Loading...";
        try {
          const resp = await fetch("/pinterest_gallery/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query, bookmark: nextBookmark }),
          });
          const data = await resp.json();
          if (!resp.ok) {
            status.textContent = data.error || "Search failed";
            bookmark = null;
            return;
          }
          addItems(data.items || []);
          bookmark = data.bookmark || null;
          status.textContent = data.items && data.items.length ? "" : "No results";
        } catch (err) {
          status.textContent = "Search failed: " + err.message;
          bookmark = null;
        } finally {
          loading = false;
        }
      };

      input.addEventListener("input", () => {
        clearTimeout(debounceTimer);
        const query = input.value.trim();
        debounceTimer = setTimeout(() => {
          if (!query || query === currentQuery) return;
          currentQuery = query;
          bookmark = null;
          grid.querySelectorAll(".pinterest-gallery-thumb").forEach((el) => el.remove());
          runSearch(query, null);
        }, 500);
      });

      const observer = new IntersectionObserver(
        (entries) => {
          if (entries[0].isIntersecting && bookmark && !loading && currentQuery) {
            runSearch(currentQuery, bookmark);
          }
        },
        { root: grid }
      );
      observer.observe(sentinel);

      node.addDOMWidget("pinterest_gallery_ui", "div", wrap, { serialize: false });

      const onRemoved = node.onRemoved;
      node.onRemoved = function () {
        observer.disconnect();
        onRemoved?.apply(this, arguments);
      };
    };
  },
});
