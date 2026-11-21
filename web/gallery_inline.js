import { imageAspect, imageShape, pinterestImageUrl, pinterestThumbnailUrl } from "./gallery_media.js";

const prefix = "/pinterest_gallery";
const shapes = [["all", "全部画幅"], ["portrait", "竖图"], ["landscape", "横图"], ["square", "方图"]];

function element(tag, classes, text) {
  const node = document.createElement(tag);
  if (classes) node.className = classes;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(text, action, classes) {
  const node = element("button", classes, text);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}

function option(value, label) {
  const node = element("option", "", label);
  node.value = value;
  return node;
}

function titleFor(pin) {
  return [pin.title, pin.description].find(value => typeof value === "string" && value.trim())?.trim() || "Pinterest 图片";
}

function withBookmark(path, bookmark) {
  return bookmark ? `${path}?${new URLSearchParams({ bookmark })}` : path;
}

function readSelection(value) {
  if (typeof value === "string") {
    try { value = JSON.parse(value); }
    catch { return null; }
  }
  return value && typeof value === "object" && value.id != null && pinterestImageUrl(value.image_url) ? value : null;
}

export function createInlineGallery({ request, getSelection, onPick, onExpand, onPreview, onSave, onAccount, initialState = {} }) {
  const host = element("section", "pgi-gallery");
  host.setAttribute("aria-label", "Pinterest 画廊");
  host.addEventListener("wheel", event => event.stopPropagation(), { passive: true });

  let mode = "search", board = null, query = "", shape = "all", selected = null;
  let bookmark = null, boardBookmark = null, pinsLoaded = false, boardsLoaded = false;
  let loadingPins = false, loadingBoards = false, picking = false, disposed = false;
  let pinError = "", boardError = "", actionError = "";
  let pinsRequest = new AbortController(), boardsRequest = new AbortController();
  const rows = new Map(), boards = new Map();

  const top = element("div", "pgi-top");
  const sources = element("nav", "pgi-sources");
  sources.setAttribute("aria-label", "画廊来源");
  const searchSource = button("公开搜索", () => changeMode("search"));
  const boardSource = button("我的画板", () => changeMode("boards"));
  sources.append(searchSource, boardSource);
  const topActions = element("div", "pgi-top-actions");
  if (onAccount) {
    const settings = button("设置", () => runAction(onAccount), "pgi-secondary");
    settings.setAttribute("aria-label", "连接 Pinterest");
    topActions.append(settings);
  }
  if (onExpand) topActions.append(button("展开画廊", () => runAction(onExpand), "pgi-secondary"));
  top.append(sources, topActions);

  const controls = element("div", "pgi-controls");
  const searchForm = element("form", "pgi-search");
  const searchBox = element("input");
  searchBox.type = "search";
  searchBox.placeholder = "关键词或画面描述";
  searchBox.autocomplete = "off";
  searchBox.setAttribute("aria-label", "搜索 Pinterest");
  searchBox.addEventListener("keydown", event => event.stopPropagation());
  const searchButton = element("button", "pgi-primary", "搜索");
  searchButton.type = "submit";
  searchForm.append(searchBox, searchButton);
  searchForm.addEventListener("submit", event => {
    event.preventDefault();
    const term = searchBox.value.trim();
    if (!term) { searchBox.focus(); return; }
    query = term;
    clearPins();
    loadPins();
  });

  const boardControls = element("div", "pgi-board-controls");
  const boardSelect = element("select");
  boardSelect.setAttribute("aria-label", "选择画板");
  boardSelect.addEventListener("change", () => {
    board = boards.get(boardSelect.value) || null;
    clearPins();
    if (board) loadPins();
    else render();
  });
  const loadBoardButton = button("读取画板", () => {
    if (board && !pinsLoaded) loadPins();
    if (!boardsLoaded || boardBookmark || boardError) loadBoards(Boolean(boardsLoaded && boardBookmark));
  }, "pgi-secondary");
  boardControls.append(boardSelect, loadBoardButton);

  const filters = element("div", "pgi-filter-row");
  const shapeSelect = element("select");
  shapeSelect.setAttribute("aria-label", "画幅");
  shapeSelect.append(...shapes.map(([value, label]) => option(value, label)));
  shapeSelect.addEventListener("change", () => { shape = shapeSelect.value; renderPins(); });
  const resultCount = element("span", "pgi-count");
  resultCount.setAttribute("aria-live", "polite");
  filters.append(shapeSelect, resultCount);
  controls.append(searchForm, boardControls, filters);

  const scroll = element("div", "pgi-scroll");
  const empty = element("p", "pgi-empty");
  empty.setAttribute("role", "status");
  const grid = element("div", "pgi-grid");
  grid.setAttribute("aria-label", "图片结果");
  const pagination = element("div", "pgi-pagination");
  const more = button("加载更多", () => loadPins(true), "pgi-secondary");
  pagination.append(more);
  scroll.append(empty, grid, pagination);

  const footer = element("footer", "pgi-footer");
  const selectionText = element("span", "pgi-selected");
  selectionText.setAttribute("aria-live", "polite");
  const feedback = element("p", "pgi-feedback");
  feedback.setAttribute("role", "status");
  footer.append(selectionText, feedback);
  host.append(top, controls, scroll, footer);

  async function fetchJson(path, options = {}) {
    const response = await request(prefix + path, { cache: "no-store", ...options });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data?.error) throw new Error(data?.error || `Pinterest 请求失败（${response.status}）。`);
    return data ?? {};
  }

  function clearPins() {
    pinsRequest.abort();
    pinsRequest = new AbortController();
    loadingPins = pinsLoaded = false;
    pinError = actionError = "";
    bookmark = null;
    rows.clear();
    grid.replaceChildren();
    scroll.scrollTop = 0;
  }

  function changeMode(next) {
    if (mode !== next) {
      mode = next;
      clearPins();
      if ((mode === "search" && query) || (mode === "boards" && board)) loadPins();
    }
    if (mode === "boards" && !boardsLoaded) loadBoards();
    render();
  }

  async function loadBoards(append = false) {
    if (disposed || loadingBoards || (append && !boardBookmark)) return;
    const signal = boardsRequest.signal;
    const cursor = append ? boardBookmark : null;
    loadingBoards = true;
    boardError = "";
    render();
    try {
      const data = await fetchJson(withBookmark("/boards", cursor), { signal });
      if (signal.aborted) return;
      if (!append) boards.clear();
      for (const item of Array.isArray(data.items) ? data.items : []) {
        if (item?.id != null) boards.set(String(item.id), item);
      }
      boardBookmark = data.bookmark && data.bookmark !== cursor ? data.bookmark : null;
      boardsLoaded = true;
    } catch (error) {
      if (!signal.aborted && error.name !== "AbortError") boardError = error.message;
    } finally {
      if (!signal.aborted) { loadingBoards = false; render(); }
    }
  }

  async function loadPins(append = false) {
    if (disposed || loadingPins || (append && !bookmark) || (mode === "search" ? !query : !board)) return;
    const signal = pinsRequest.signal;
    const cursor = append ? bookmark : null;
    const path = mode === "search" ? "/search" : withBookmark(`/boards/${encodeURIComponent(board.id)}/pins`, cursor);
    const options = mode === "search" ? { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, bookmark: cursor }) } : {};
    loadingPins = true;
    pinError = "";
    render();
    try {
      const data = await fetchJson(path, { ...options, signal });
      if (signal.aborted) return;
      for (const pin of Array.isArray(data.items) ? data.items : []) addPin(pin);
      bookmark = data.bookmark && data.bookmark !== cursor ? data.bookmark : null;
      pinsLoaded = true;
    } catch (error) {
      if (!signal.aborted && error.name !== "AbortError") pinError = error.message;
    } finally {
      if (!signal.aborted) { loadingPins = false; render(); }
    }
  }

  function addPin(pin) {
    pin = readSelection(pin);
    if (!pin) return;
    const id = String(pin.id);
    if (rows.has(id)) return;
    const title = titleFor(pin);
    const item = element("article", "pgi-card");
    const pick = button("", () => pickPin(pin), "pgi-pick");
    pick.dataset.pinId = id;
    pick.setAttribute("aria-label", `选择${title === "Pinterest 图片" ? ` Pinterest 图片 ${rows.size + 1}` : title}`);
    pick.title = title;
    const img = element("img");
    img.alt = "";
    img.decoding = "async";
    img.referrerPolicy = "no-referrer";
    const noThumb = element("span", "pgi-no-thumb", "缩略图不可用");
    noThumb.hidden = true;
    const aspect = imageAspect(pin);
    const row = { pin, item, pick, shape: aspect ? imageShape(aspect) : null };
    if (row.shape) item.dataset.shape = row.shape;
    rows.set(id, row);
    const unavailable = () => {
      row.shape ||= "unavailable";
      img.hidden = true;
      noThumb.hidden = false;
      renderPins();
    };
    img.addEventListener("load", () => {
      row.shape ||= imageShape(img.naturalWidth / img.naturalHeight);
      item.dataset.shape = row.shape;
      renderPins();
    });
    img.addEventListener("error", unavailable);
    pick.append(img, noThumb);
    const actions = element("div", "pgi-card-actions");
    if (onPreview) {
      const preview = button("预览", () => runAction(onPreview, pin));
      preview.setAttribute("aria-label", "预览图片");
      actions.append(preview);
    }
    if (onSave) {
      const save = button("加入画板", () => runAction(onSave, pin));
      save.setAttribute("aria-label", "加入画板");
      actions.append(save);
    }
    item.append(pick);
    if (actions.childElementCount) item.append(actions);
    grid.append(item);
    const source = pinterestThumbnailUrl(pin);
    if (source) img.src = source;
    else unavailable();
  }

  async function pickPin(pin) {
    if (disposed || picking || !onPick) return;
    picking = true;
    actionError = "";
    render();
    try {
      await onPick(pin, getState());
      applySelection(getSelection ? getSelection() : pin);
    } catch (error) { actionError = error?.message || "未能选中图片。"; }
    finally { picking = false; if (!disposed) render(); }
  }

  async function runAction(callback, pin) {
    actionError = "";
    render();
    try {
      if (pin) await callback(pin, getState());
      else await callback(getState());
    } catch (error) {
      actionError = error?.message || "操作失败，请重试。";
      if (!disposed) render();
    }
  }

  function renderPins() {
    if (disposed) return;
    let visible = 0, pending = 0;
    for (const row of rows.values()) {
      row.item.hidden = shape !== "all" && row.shape !== shape;
      row.pick.disabled = picking;
      row.pick.setAttribute("aria-pressed", String(selected !== null && String(row.pin.id) === String(selected.id)));
      if (!row.item.hidden) visible++;
      if (!row.shape) pending++;
    }
    resultCount.textContent = rows.size ? `${visible} / ${rows.size} 张` : "";
    grid.hidden = visible === 0;
    empty.hidden = visible > 0;
    if (loadingPins) empty.textContent = "正在读取图片…";
    else if (pinError) empty.textContent = pinError;
    else if (rows.size && pending) empty.textContent = "正在识别画幅…";
    else if (rows.size) empty.textContent = "已载入图片里没有这个画幅。";
    else if (pinsLoaded) empty.textContent = "没有找到图片。";
    else if (mode === "search") empty.textContent = "输入关键词开始找图。";
    else if (loadingBoards) empty.textContent = "正在读取画板…";
    else if (boardError) empty.textContent = boardError;
    else if (boardsLoaded && !boards.size) empty.textContent = "账号里暂无画板。";
    else if (board) empty.textContent = "读取当前画板可继续浏览。";
    else empty.textContent = "读取我的画板后选择一个。";
    pagination.hidden = !bookmark;
    more.disabled = loadingPins;
    more.textContent = loadingPins ? "加载中…" : "加载更多";
    selectionText.textContent = selected ? `已选 ${titleFor(selected)}` : "未选择图片";
    selectionText.title = selectionText.textContent;
    feedback.textContent = actionError || (visible ? pinError || boardError : "");
    feedback.hidden = !feedback.textContent;
  }

  function render() {
    if (disposed) return;
    const showBoards = mode === "boards";
    searchSource.setAttribute("aria-pressed", String(!showBoards));
    boardSource.setAttribute("aria-pressed", String(showBoards));
    searchForm.hidden = showBoards;
    boardControls.hidden = !showBoards;
    if (showBoards) {
      const choices = new Map(boards);
      if (board && !choices.has(String(board.id))) choices.set(String(board.id), board);
      boardSelect.replaceChildren(option("", "选择画板"), ...Array.from(choices,
        ([id, item]) => option(id, item.name || "Pinterest 画板")));
      boardSelect.value = String(board?.id ?? "");
      boardSelect.disabled = !choices.size;
      loadBoardButton.hidden = boardsLoaded && !boardBookmark && !boardError && (!board || pinsLoaded);
      loadBoardButton.disabled = loadingBoards || loadingPins;
      loadBoardButton.textContent = loadingBoards ? "读取中…" : board && !pinsLoaded && boardsLoaded ? "读取图片" :
        boardBookmark ? "更多画板" : boardError ? "重试画板" : "读取画板";
    }
    shapeSelect.value = shape;
    renderPins();
  }

  function applySelection(pin) {
    selected = readSelection(pin);
    renderPins();
  }

  function getState() {
    const draftQuery = searchBox.value.trim();
    return { query: query || draftQuery, draftQuery, shape, mode, board: board ? { ...board } : null,
      items: Array.from(rows.values(), row => row.pin), bookmark, selected, loaded: pinsLoaded };
  }

  function applyState(state = {}) {
    if (disposed) return;
    const nextMode = state.mode === "boards" ? "boards" : state.mode === "search" ? "search" : mode;
    const nextQuery = typeof state.query === "string" ? state.query.trim() : query;
    const nextBoard = Object.hasOwn(state, "board") ? state.board?.id != null ? state.board : null : board;
    if (mode !== nextMode || query !== nextQuery || String(board?.id) !== String(nextBoard?.id)) clearPins();
    mode = nextMode;
    query = nextQuery;
    board = nextBoard;
    if (shapes.some(([value]) => value === state.shape)) shape = state.shape;
    if (Object.hasOwn(state, "query") || Object.hasOwn(state, "draftQuery")) searchBox.value = state.draftQuery ?? query;
    if (Array.isArray(state.items)) {
      const incoming = state.items.map(readSelection).filter(Boolean);
      const previous = [...rows.values()];
      if (incoming.length !== previous.length || incoming.some((pin, index) => JSON.stringify(pin) !== JSON.stringify(previous[index].pin))) {
        clearPins();
        for (const pin of incoming) addPin(pin);
      }
      if (incoming.length || state.loaded === true) pinsLoaded = true;
    }
    if (Object.hasOwn(state, "bookmark")) bookmark = state.bookmark || null;
    if (getSelection || Object.hasOwn(state, "selected")) selected = readSelection(getSelection ? getSelection() : state.selected);
    render();
  }

  function dispose() {
    disposed = true;
    pinsRequest.abort();
    boardsRequest.abort();
    host.remove();
  }

  function refreshAccount(status) {
    if (disposed) return;
    boardsRequest.abort();
    boardsRequest = new AbortController();
    board = null;
    boardBookmark = null;
    boardError = "";
    loadingBoards = boardsLoaded = false;
    boards.clear();
    if (mode !== "boards") return;
    clearPins();
    if (status?.connected && host.isConnected) loadBoards();
    else render();
  }

  applyState(initialState);
  return { element: host, applySelection, applyState, getState, refreshAccount, dispose };
}
