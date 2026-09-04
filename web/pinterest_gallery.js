import { app } from "../../scripts/app.js";

const CSS = `
.pinterest-gallery-wrap { display:flex; flex-direction:column; gap:4px; width:100%; height:100%; box-sizing:border-box; }
.pinterest-gallery-controls { display:flex; gap:4px; width:100%; }
.pinterest-gallery-mode, .pinterest-gallery-board, .pinterest-gallery-search { min-width:0; width:100%; box-sizing:border-box; }
.pinterest-gallery-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:4px; grid-auto-rows:min-content; flex:1 1 auto; min-height:0; max-height:75vh; overflow-y:auto; background:#1a1a1a; padding:4px; border-radius:4px; }
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
        selectedWidget.computeSize = () => [0, -4];
        selectedWidget.draw = () => {};
      }

      const wrap = document.createElement("div");
      wrap.className = "pinterest-gallery-wrap";
      const controls = document.createElement("div");
      controls.className = "pinterest-gallery-controls";
      const modeSelect = document.createElement("select");
      modeSelect.className = "pinterest-gallery-mode";
      modeSelect.innerHTML = '<option value="search">Search</option><option value="boards">My Boards</option>';
      const boardSelect = document.createElement("select");
      boardSelect.className = "pinterest-gallery-board";
      boardSelect.disabled = true;
      boardSelect.innerHTML = '<option value="">Select a board...</option>';
      const input = document.createElement("input");
      input.className = "pinterest-gallery-search";
      input.type = "text";
      input.placeholder = "Search Pinterest...";
      input.addEventListener("keydown", (e) => e.stopPropagation());
      controls.append(modeSelect, input);

      const status = document.createElement("div");
      status.className = "pinterest-gallery-status";
      const grid = document.createElement("div");
      grid.className = "pinterest-gallery-grid";
      const sentinel = document.createElement("div");
      sentinel.style.height = "1px";
      grid.appendChild(sentinel);
      wrap.append(controls, boardSelect, status, grid);

      let mode = "search";
      let currentQuery = "";
      let currentBoard = "";
      let bookmark = null;
      let loading = false;
      let debounceTimer = null;
      let requestGeneration = 0;

      const clearResults = () => {
        grid.querySelectorAll(".pinterest-gallery-thumb").forEach((el) => el.remove());
        bookmark = null;
      };

      const setSelected = (item, imgEl) => {
        grid.querySelectorAll(".pinterest-gallery-thumb.selected").forEach((el) => el.classList.remove("selected"));
        imgEl.classList.add("selected");
        if (selectedWidget) {
          selectedWidget.value = JSON.stringify({ id: item.id, image_url: item.image_url });
          node.setDirtyCanvas?.(true, true);
        }
      };

      const addItems = (items) => {
        for (const item of items) {
          if (!item?.thumbnail_url || !item?.image_url) continue;
          const img = document.createElement("img");
          img.className = "pinterest-gallery-thumb";
          img.src = item.thumbnail_url;
          img.loading = "lazy";
          img.addEventListener("click", () => setSelected(item, img));
          grid.insertBefore(img, sentinel);
        }
      };

      const request = async (url, options) => {
        const resp = await fetch(url, options);
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Pinterest request failed");
        return data;
      };

      const requestItems = async (url, options, generation, emptyMessage) => {
        if (loading) return;
        loading = true;
        status.textContent = "Loading...";
        try {
          const data = await request(url, options);
          if (generation !== requestGeneration) return;
          addItems(data.items || []);
          bookmark = data.bookmark || null;
          status.textContent = data.items?.length ? "" : emptyMessage;
        } catch (err) {
          if (generation === requestGeneration) {
            status.textContent = err.message || "Pinterest request failed";
            bookmark = null;
          }
        } finally {
          loading = false;
        }
      };

      const runSearch = (query, nextBookmark, generation) => requestItems(
        "/pinterest_gallery/search",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query, bookmark: nextBookmark }) },
        generation,
        "No results"
      );

      const runBoardPins = (boardId, nextBookmark, generation) => {
        if (!boardId) return;
        const suffix = nextBookmark ? `?bookmark=${encodeURIComponent(nextBookmark)}` : "";
        return requestItems(`/pinterest_gallery/boards/${encodeURIComponent(boardId)}/pins${suffix}`, undefined, generation, "No pins found");
      };

      const loadBoards = async (generation) => {
        if (loading) return;
        loading = true;
        status.textContent = "Loading boards...";
        boardSelect.disabled = true;
        try {
          const data = await request("/pinterest_gallery/boards");
          if (generation !== requestGeneration) return;
          boardSelect.innerHTML = '<option value="">Select a board...</option>';
          for (const board of data.items || []) {
            const option = document.createElement("option");
            option.value = board.id;
            option.textContent = board.name || board.id;
            boardSelect.appendChild(option);
          }
          boardSelect.disabled = false;
          status.textContent = data.items?.length ? "" : "No boards found";
        } catch (err) {
          if (generation === requestGeneration) status.textContent = err.message || "Unable to load boards";
        } finally {
          loading = false;
        }
      };

      modeSelect.addEventListener("change", () => {
        mode = modeSelect.value;
        requestGeneration += 1;
        currentQuery = "";
        currentBoard = "";
        clearResults();
        status.textContent = "";
        input.value = "";
        input.style.display = mode === "search" ? "block" : "none";
        boardSelect.style.display = mode === "boards" ? "block" : "none";
        if (mode === "boards") loadBoards(requestGeneration);
      });

      boardSelect.addEventListener("change", () => {
        currentBoard = boardSelect.value;
        requestGeneration += 1;
        clearResults();
        status.textContent = "";
        runBoardPins(currentBoard, null, requestGeneration);
      });

      input.addEventListener("input", () => {
        clearTimeout(debounceTimer);
        const query = input.value.trim();
        debounceTimer = setTimeout(() => {
          if (!query || query === currentQuery || mode !== "search") return;
          requestGeneration += 1;
          currentQuery = query;
          clearResults();
          runSearch(query, null, requestGeneration);
        }, 500);
      });

      const observer = new IntersectionObserver((entries) => {
        if (!entries[0].isIntersecting || !bookmark || loading) return;
        if (mode === "search" && currentQuery) runSearch(currentQuery, bookmark, requestGeneration);
        if (mode === "boards" && currentBoard) runBoardPins(currentBoard, bookmark, requestGeneration);
      }, { root: grid });
      observer.observe(sentinel);

      boardSelect.style.display = "none";
      node.addDOMWidget("pinterest_gallery_ui", "div", wrap, { serialize: false });
      requestAnimationFrame(() => {
        let [w, h] = node.size;
        w = Math.max(w, 320);
        if (h < 300 || h > 560) h = 380;
        node.setSize([w, h]);
        node.setDirtyCanvas?.(true, true);
      });
      const onRemoved = node.onRemoved;
      node.onRemoved = function () {
        clearTimeout(debounceTimer);
        observer.disconnect();
        onRemoved?.apply(this, arguments);
      };
    };
  },
});
