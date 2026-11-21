import { imageAspect, imageShape, pinterestImageUrl, pinterestThumbnailUrl } from "./gallery_media.js";

const prefix = "/pinterest_gallery";
const shapes = [["all", "全部画幅"], ["portrait", "竖图"], ["landscape", "横图"], ["square", "方图"]];
const examples = [["杂志封面", "editorial magazine cover"], ["极简壁纸", "minimal wallpaper negative space"],
  ["自然光人像", "natural light portrait"], ["高定穿搭", "couture fashion editorial"]];
const accountChanges = new EventTarget();

export function subscribeAccountChanges(listener) {
  const notify = event => listener(event.detail.status);
  accountChanges.addEventListener("change", notify);
  return () => accountChanges.removeEventListener("change", notify);
}

function element(tag, classes, text) {
  const node = document.createElement(tag);
  if (classes) node.className = classes;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(text, action, classes = "") {
  const node = element("button", classes, text);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}

function jsonPost(data) {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) };
}

function bookmarkPath(path, bookmark) {
  return bookmark ? `${path}?${new URLSearchParams({ bookmark })}` : path;
}

function galleryJson(request) {
  return async (path, options = {}) => {
    const response = await request(prefix + path, { cache: "no-store", ...options });
    if (path === "/account/status" && response.status === 404) {
      return { state: "needs_restart", connected: false, oauth_available: false };
    }
    const value = await response.json().catch(() => ({}));
    if (!response.ok || value?.error) {
      const error = new Error(value?.error || `Pinterest 请求失败（${response.status}）。`);
      error.status = response.status;
      error.code = value?.code;
      throw error;
    }
    return value ?? {};
  };
}

function officialPinId(pin) {
  return typeof pin?.pin_id === "string" && /^\d+$/.test(pin.pin_id) ? pin.pin_id : "";
}

function pinPermalink(pin) {
  const match = /^https:\/\/(?:www\.)?pinterest\.com\/pin\/(\d+)\/?(?:[?#].*)?$/i.exec(pin?.source_url || "");
  const id = officialPinId(pin) || match?.[1];
  return id ? `https://www.pinterest.com/pin/${id}/` : "";
}

function pinTitle(pin) {
  return [pin?.title, pin?.description].find(value => typeof value === "string" && value.trim())?.trim() || "Pinterest 图片";
}

function pinKey(pin) {
  return officialPinId(pin) || pinterestImageUrl(pin?.image_url);
}

function setPressed(node, pressed) {
  node.setAttribute("aria-pressed", String(pressed));
}

function statusCaption(status) {
  if (!status) return "连接状态不可用";
  if (status.state === "needs_restart") return "账号接口待加载";
  if (status.state === "expired") return "凭据已过期";
  if (status.state === "invalid" || status.state === "error") return "连接需要检查";
  if (!status.connected) return "账号未连接";
  const source = { token: "Token", oauth: "OAuth", environment: "环境变量" }[status.method];
  return `${status.mode === "sandbox" ? "已连接沙盒" : "账号已连接"}${source ? `（${source}）` : ""}`;
}

function field(label, name, type = "text") {
  const container = element("label", "pg-field", label);
  const input = element("input");
  input.name = name;
  input.type = type;
  input.required = true;
  input.autocomplete = "off";
  input.spellcheck = false;
  container.append(input);
  return { container, input };
}

function accountSettings({ json, caption, onChange, onDismiss = () => {} }) {
  const dialog = element("dialog", "pg-dialog pg-account");
  dialog.setAttribute("aria-label", "连接 Pinterest");
  const heading = element("header", "pg-account-head");
  const summary = element("p", "pg-muted");
  const title = element("div");
  title.append(element("h2", "", "连接 Pinterest"), summary);
  heading.append(title, button("关闭", () => dialog.close(), "pg-quiet"));

  const modes = element("div", "pg-segments pg-account-modes");
  modes.setAttribute("aria-label", "连接方式");
  const tokenButton = button("已有 Token", () => switchMethod("token"));
  const oauthButton = button("浏览器授权", () => switchMethod("oauth"));
  modes.append(tokenButton, oauthButton);

  const form = element("form", "pg-account-form");
  const setupHelp = element("p", "pg-muted pg-account-note");
  const developerLink = element("a", "pg-auth-link", "Pinterest 开发者后台");
  developerLink.href = "https://developers.pinterest.com/apps/";
  developerLink.target = "_blank";
  developerLink.rel = "noopener noreferrer";
  const setupInstruction = document.createTextNode("");
  setupHelp.append(developerLink, setupInstruction);
  const token = field("Pinterest Access Token", "token", "password");
  const clientId = field("App ID", "client_id");
  const clientSecret = field("App Secret", "client_secret", "password");
  const callback = field("Pinterest 应用回调地址", "callback");
  callback.input.readOnly = true;
  callback.input.required = false;
  callback.input.addEventListener("focus", () => callback.input.select());
  const callbackHelp = element("p", "pg-muted pg-account-note", "把此地址登记到 Pinterest 开发者后台的应用设置，再开始授权。");
  const environment = element("label", "pg-field", "环境");
  const mode = element("select");
  for (const [value, text] of [["production", "正式环境"], ["sandbox", "开发沙盒"]]) {
    const option = element("option", "", text);
    option.value = value;
    mode.append(option);
  }
  environment.append(mode);
  const remember = element("input");
  remember.type = "checkbox";
  const rememberLabel = element("label", "pg-check");
  rememberLabel.append(remember, document.createTextNode("在本机加密保存连接"));
  const actions = element("div", "pg-account-actions");
  const submit = element("button", "pg-primary");
  submit.type = "submit";
  const logout = button("断开连接", disconnect, "pg-quiet");
  actions.append(submit, logout);
  const feedback = element("p", "pg-account-feedback");
  feedback.setAttribute("role", "status");
  const authLink = element("a", "pg-auth-link", "打开 Pinterest 授权页");
  authLink.target = "_blank";
  authLink.rel = "noopener noreferrer";
  authLink.hidden = true;
  form.append(setupHelp, token.container, clientId.container, clientSecret.container, callback.container, callbackHelp,
    environment, rememberLabel, actions, feedback, authLink);
  dialog.append(heading, modes, form);

  let method = "token", status = null, busy = false, disposed = false, pollTimer, pollUntil = 0, writeAccess = false;
  const activeRequest = new AbortController();
  let statusRequest = 0;

  function acceptAccountStatus(next) {
    if (disposed) return;
    statusRequest++;
    status = next;
    render();
    onChange(status, true);
  }

  function receiveAccountChange(event) {
    if (event.detail.sender !== receiveAccountChange) acceptAccountStatus(event.detail.status);
  }

  function announceAccountChange(next) {
    if (disposed) return;
    acceptAccountStatus(next);
    accountChanges.dispatchEvent(new CustomEvent("change", { detail: { status: next, sender: receiveAccountChange } }));
  }

  function switchMethod(value) {
    method = value;
    setPressed(tokenButton, value === "token");
    setPressed(oauthButton, value === "oauth");
    token.container.hidden = token.input.disabled = value !== "token";
    clientId.container.hidden = clientId.input.disabled = value !== "oauth";
    clientSecret.container.hidden = clientSecret.input.disabled = value !== "oauth";
    setupInstruction.textContent = value === "oauth"
      ? writeAccess
        ? "。这次会额外请求画板和 Pin 的写入权限，用于加入画板。"
        : "。先创建获批的应用，再用浏览器里当前登录的 Pinterest 账号授权。"
      : " → My apps → Manage → Configure → Generate Access Token。";
    callback.container.hidden = callbackHelp.hidden = value !== "oauth";
    render();
  }

  function note(message, isError = false) {
    feedback.textContent = message;
    feedback.classList.toggle("pg-error", isError);
  }

  function render() {
    caption.textContent = statusCaption(status);
    caption.dataset.connected = String(Boolean(status?.connected));
    summary.textContent = status?.state === "needs_restart"
      ? "请重启 ComfyUI 服务后，再在这里连接 Pinterest。"
      : statusCaption(status);
    callback.input.value = status?.redirect_uri || "";
    rememberLabel.hidden = status?.can_persist !== true;
    logout.hidden = !status?.connected && status?.state !== "expired" && status?.state !== "invalid";
    logout.disabled = busy;
    submit.disabled = busy || status?.state === "needs_restart" ||
      (method === "oauth" && status?.oauth_available === false);
    submit.textContent = method === "oauth" ? "打开 Pinterest 授权" : "保存并连接";
  }

  function clearSecrets() {
    token.input.value = "";
    clientSecret.input.value = "";
  }

  async function refresh(notify = true) {
    const ticket = ++statusRequest;
    try {
      const next = await json("/account/status", { signal: activeRequest.signal });
      if (disposed || ticket !== statusRequest) return;
      const changed = status?.connected !== next.connected || status?.mode !== next.mode ||
        status?.method !== next.method || status?.pin_write !== next.pin_write;
      status = next;
      render();
      if (changed && notify) onChange(status);
      return status;
    } catch (error) {
      if (!disposed && error.name !== "AbortError" && ticket === statusRequest) {
        summary.textContent = "无法读取连接状态。请刷新 ComfyUI 页面后重试。";
        caption.textContent = statusCaption(status);
      }
    }
  }

  function finishPolling() {
    clearTimeout(pollTimer);
    pollUntil = 0;
    authLink.hidden = true;
    authLink.removeAttribute("href");
  }

  function poll() {
    clearTimeout(pollTimer);
    if (!pollUntil || disposed) return;
    pollTimer = setTimeout(async () => {
      const current = await refresh(false);
      if (disposed || !pollUntil) return;
      if (current && current.oauth_pending === false) {
        finishPolling();
        if (current.oauth_error) note(current.oauth_error, true);
        else if (current.connected && current.method === "oauth") {
          note("Pinterest 授权成功，可以打开我的画板。");
          announceAccountChange(current);
        } else note("授权没有完成，请重试。", true);
      } else if (Date.now() >= pollUntil) {
        finishPolling();
        note("授权已超时，请重新打开授权页。", true);
      } else poll();
    }, 1800);
  }

  async function authorize(settings) {
    const popup = window.open("about:blank", "_blank");
    if (popup) popup.opener = null;
    try {
      const value = await json("/account/oauth/start", { ...jsonPost({ ...settings, write_access: writeAccess, client_id: clientId.input.value.trim(),
        client_secret: clientSecret.input.value.trim() }), signal: activeRequest.signal });
      const url = new URL(value.authorize_url);
      if (url.protocol !== "https:" || !["pinterest.com", "www.pinterest.com"].includes(url.hostname)) throw new Error("授权地址无效。");
      authLink.href = url.href;
      authLink.hidden = false;
      if (popup && !popup.closed) popup.location.replace(url.href);
      note("请在 Pinterest 完成授权，再返回画廊。");
      pollUntil = value.expires_at ? value.expires_at * 1000 : Date.now() + 600000;
      poll();
    } catch (error) {
      if (popup && !popup.closed) popup.close();
      throw error;
    }
  }

  async function disconnect() {
    if (busy) return;
    busy = true;
    render();
    try {
      const current = await json("/account/logout", { ...jsonPost({}), signal: activeRequest.signal });
      finishPolling();
      announceAccountChange(current);
      note(status?.method === "environment" ? "本机凭据已清除，环境变量连接仍可用。" : "Pinterest 连接已断开。");
    } catch (error) { if (error.name !== "AbortError") note(error.message, true); }
    finally { busy = false; render(); }
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy) return;
    busy = true;
    render();
    note("");
    finishPolling();
    const settings = { mode: mode.value, remember: remember.checked && status?.can_persist === true };
    try {
      if (method === "oauth") await authorize(settings);
      else {
        const current = await json("/account/token", { ...jsonPost({ ...settings, token: token.input.value.trim() }), signal: activeRequest.signal });
        note("Pinterest 凭据已更新。");
        announceAccountChange(current);
      }
    } catch (error) { if (error.name !== "AbortError") note(error.message, true); }
    finally { busy = false; clearSecrets(); render(); }
  });

  dialog.addEventListener("close", () => { clearSecrets(); if (!disposed) onDismiss(); });
  dialog.addEventListener("cancel", event => { event.preventDefault(); dialog.close(); });
  accountChanges.addEventListener("change", receiveAccountChange);
  switchMethod("token");
  document.body.append(dialog);
  return {
    get status() { return status; },
    refresh,
    open(forSave = false) {
      if (dialog.open) return;
      writeAccess = forSave === true;
      if (status?.mode) mode.value = status.mode;
      remember.checked = status?.persistent === true;
      switchMethod(writeAccess || status?.method === "oauth" ? "oauth" : "token");
      dialog.showModal();
      refresh();
    },
    close() {
      disposed = true;
      accountChanges.removeEventListener("change", receiveAccountChange);
      activeRequest.abort();
      finishPolling();
      clearSecrets();
      if (dialog.open) dialog.close();
      dialog.remove();
    },
  };
}

export function openGalleryAccount({ request, onChange = () => {}, onClose = () => {} }) {
  let closed = false;
  const account = accountSettings({ json: galleryJson(request), caption: element("span"), onChange, onDismiss: close });
  function close() {
    if (closed) return;
    closed = true;
    account.close();
    onClose();
  }
  account.open();
  return close;
}

export function openBoardSave({ request, pin, onClose = () => {} }) {
  const json = galleryJson(request);
  const id = officialPinId(pin);
  const origin = pinPermalink(pin);
  const previousFocus = document.activeElement;
  const dialog = element("dialog", "pg-dialog pg-account pg-save");
  dialog.setAttribute("aria-label", "加入画板");
  const heading = element("header", "pg-account-head");
  const dismiss = button("关闭", close, "pg-quiet");
  heading.append(element("h2", "", "加入画板"), dismiss);
  const preview = element("div", "pg-save-preview");
  const image = element("img");
  const thumbnail = pinterestThumbnailUrl(pin);
  image.alt = "";
  image.referrerPolicy = "no-referrer";
  if (thumbnail) image.src = thumbnail;
  else image.hidden = true;
  preview.append(image, element("strong", "", pinTitle(pin)));
  const status = element("p", "pg-muted pg-save-status", id ? "正在检查账号连接…" : "这张图片缺少可保存的 Pinterest Pin 编号。");
  status.setAttribute("role", "status");
  const connect = button("授权保存到画板", () => account.open(true), "pg-primary");
  connect.hidden = true;
  const form = element("form", "pg-account-form pg-save-form");
  const label = element("label", "pg-field", "目标画板");
  const select = element("select");
  select.required = true;
  const blank = new Option("选择已有画板", "");
  select.add(blank);
  label.append(select);
  const more = button("加载更多画板", () => loadBoards(true), "pg-quiet");
  const save = element("button", "pg-primary", "加入画板");
  save.type = "submit";
  const actions = element("div", "pg-account-actions");
  actions.append(save, more);
  form.append(label, actions);
  form.hidden = true;
  const link = element("a", "pg-auth-link", origin ? "在 Pinterest 打开原 Pin" : "查看原图");
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  const linkUrl = origin || pinterestImageUrl(pin?.image_url);
  if (linkUrl) link.href = linkUrl;
  else link.hidden = true;
  dialog.append(heading, preview, status, connect, form, link);

  let closed = false, saving = false, loading = false, bookmark = null, loaded = false, boardError = false;
  let needsWrite = false;
  let boardsRequest = new AbortController();
  const boards = new Map(), completedBoards = new Set();
  const account = id ? accountSettings({ json, caption: element("span"), onChange: showAccount }) : null;

  function close() {
    if (closed || saving) return;
    closed = true;
    boardsRequest.abort();
    account?.close();
    dialog.close();
    dialog.remove();
    onClose();
    previousFocus?.focus({ preventScroll: true });
  }

  function paint() {
    dismiss.disabled = saving;
    save.disabled = saving || loading || needsWrite || !select.value || completedBoards.has(select.value);
    save.textContent = saving ? "正在加入…" : completedBoards.has(select.value) ? "已加入画板" : "加入画板";
    more.hidden = !bookmark && !boardError;
    more.disabled = loading || saving;
    more.textContent = boardError ? "重试画板" : "加载更多画板";
  }

  async function showAccount(current, changed) {
    if (closed || !current) return;
    if (changed) {
      boardsRequest.abort();
      boardsRequest = new AbortController();
      loading = false;
      loaded = false;
      boardError = false;
      bookmark = null;
      boards.clear();
      completedBoards.clear();
      select.replaceChildren(blank);
    }
    needsWrite = !current.connected || current.pin_write === "read_only";
    connect.hidden = !needsWrite || current.state === "needs_restart";
    form.hidden = needsWrite;
    if (current.state === "needs_restart") status.textContent = "请重启 ComfyUI 服务后，再试加入画板。";
    else if (needsWrite) status.textContent = "连接账号并授予保存权限，即可选择你的画板。";
    else if (!loaded && !loading) await loadBoards(false);
    paint();
  }

  async function loadBoards(append) {
    if (closed || loading || (append && !bookmark && !boardError)) return;
    loading = true;
    boardError = false;
    const signal = boardsRequest.signal;
    const page = append ? bookmark : null;
    status.textContent = "正在读取画板…";
    paint();
    try {
      const value = await json(bookmarkPath("/boards", page), { signal });
      if (closed || signal.aborted) return;
      for (const board of Array.isArray(value.items) ? value.items : []) {
        if (typeof board?.id !== "string" || boards.has(board.id) ||
            (board.privacy && board.privacy !== "PUBLIC") || board.is_ads_only === true) continue;
        const name = board.name || "未命名画板";
        boards.set(board.id, name);
        select.add(new Option(name, board.id));
      }
      bookmark = value.bookmark && value.bookmark !== page ? value.bookmark : null;
      loaded = true;
      status.textContent = boards.size ? "选择保存此 Pin 的画板。" :
        bookmark ? "本页没有可选画板，可以继续加载。" : "账号下没有可用的普通画板。";
    } catch (error) {
      if (!closed && !signal.aborted) {
        boardError = true;
        status.textContent = error.message || "读取画板失败。";
      }
    } finally {
      if (!closed && !signal.aborted) { loading = false; paint(); }
    }
  }

  select.addEventListener("change", paint);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const board = select.value;
    if (saving || needsWrite || !id || !boards.has(board) || completedBoards.has(board)) return;
    saving = true;
    status.textContent = "正在保存到 Pinterest…";
    paint();
    try {
      await json("/pins/save", jsonPost({ pin_id: id, board_id: board, confirm: true }));
      completedBoards.add(board);
      status.textContent = `已加入「${boards.get(board)}」画板。`;
    } catch (error) {
      if (error.status === 401 || error.code === "write_scope_required") {
        needsWrite = true;
        connect.hidden = false;
      }
      status.textContent = error.message || "Pinterest 保存失败。";
    } finally { saving = false; paint(); }
  });
  dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
  document.body.append(dialog);
  dialog.showModal();
  if (account) account.refresh().then(value => {
    if (!closed && !value && !loading && !loaded) status.textContent = "读取账号状态失败，请重新打开此窗口。";
  });
  return close;
}

export function openGallery({ request, onPick, targetLabel = "当前工作流", mountTarget,
  initialState = {}, previewOnOpen = false, onClose = () => {} }) {
  const previousFocus = document.activeElement;
  const dialog = element("dialog", "pg-dialog pg-gallery");
  dialog.setAttribute("aria-label", "Pinterest 画廊");
  let closed = false, mode = initialState.mode === "boards" ? "boards" : "search";
  let query = initialState.query ?? "", selected = null, board = initialState.board ?? null, bookmark = initialState.bookmark ?? null;
  let activeShape = shapes.some(([value]) => initialState.shape === value) ? initialState.shape : "all";
  let loading = false, pinsLoaded = initialState.loaded === true, loadError = "", sending = false, showPreview = false;
  let pinsRequest = new AbortController(), boardRequest = new AbortController(), boardBookmark = null;
  let boardsLoaded = false, boardsLoading = false, boardError = "";
  const cards = new Map(), boards = new Map();
  const json = galleryJson(request);
  let closeSave;

  const header = element("header", "pg-head");
  const heading = element("h1", "", "Pinterest 画廊");
  const accountCaption = element("span", "pg-account-caption", "读取连接状态…");
  const accountButton = button("连接 Pinterest", () => account.open(), "pg-quiet");
  const closeButton = button("关闭", close, "pg-close");
  const headActions = element("div", "pg-head-actions");
  headActions.append(accountCaption, accountButton, closeButton);
  header.append(heading, headActions);

  const body = element("div", "pg-body");
  const side = element("aside", "pg-sidebar");
  const nav = element("nav", "pg-sources");
  nav.setAttribute("aria-label", "画廊来源");
  const searchSource = button("公开搜索", () => changeSource("search"));
  const boardSource = button("我的画板", () => changeSource("boards"));
  nav.append(searchSource, boardSource);
  const boardList = element("div", "pg-board-list");
  boardList.setAttribute("aria-label", "Pinterest 画板");
  const boardsMessage = element("p", "pg-muted pg-boards-message");
  boardsMessage.setAttribute("role", "status");
  const boardsMore = button("更多画板", () => loadBoards(boardsLoaded), "pg-quiet pg-boards-more");
  side.append(nav, boardsMessage, boardList, boardsMore);

  const main = element("main", "pg-main");
  const toolbar = element("div", "pg-toolbar");
  const search = element("form", "pg-search");
  const phrase = element("input");
  phrase.type = "search";
  phrase.autocomplete = "off";
  phrase.setAttribute("aria-label", "搜索 Pinterest");
  phrase.addEventListener("keydown", event => event.stopPropagation());
  phrase.placeholder = "搜索 Pinterest 上的图片";
  phrase.value = initialState.draftQuery ?? query;
  const searchButton = element("button", "pg-primary", "搜索");
  searchButton.type = "submit";
  search.append(phrase, searchButton);
  search.addEventListener("submit", event => { event.preventDefault(); runSearch(phrase.value); });
  const boardTitle = element("h2", "pg-board-title");
  const controlRow = element("div", "pg-grid-controls");
  const segments = element("div", "pg-segments");
  segments.setAttribute("aria-label", "画幅");
  const shapeButtons = new Map(shapes.map(([shape, label]) => [shape, button(label, () => {
    activeShape = shape;
    for (const row of cards.values()) row.node.hidden = !matchesShape(row);
    render();
  })]));
  segments.append(...shapeButtons.values());
  const count = element("p", "pg-results-count");
  count.setAttribute("aria-live", "polite");
  controlRow.append(segments, count);
  toolbar.append(search, boardTitle, controlRow);

  const results = element("div", "pg-results");
  results.setAttribute("aria-label", "图片结果");
  const empty = element("div", "pg-empty");
  const emptyTitle = element("h2");
  const emptyDescription = element("p", "pg-muted");
  const examplesRow = element("div", "pg-examples");
  for (const [label, term] of examples) examplesRow.append(button(label, () => { phrase.value = term; runSearch(term); }));
  const emptyAction = button("重试", retryPins, "pg-quiet");
  empty.append(emptyTitle, emptyDescription, examplesRow, emptyAction);
  const masonry = element("div", "pg-masonry");
  const pagination = element("div", "pg-pagination");
  const paginationMessage = element("p", "pg-muted");
  const more = button("加载更多", () => loadPins(true), "pg-quiet");
  pagination.append(paginationMessage, more);
  results.append(empty, masonry, pagination);
  main.append(toolbar, results);

  const preview = element("aside", "pg-detail");
  preview.setAttribute("aria-label", "选中图片大图");
  const previewHeader = element("div", "pg-detail-head");
  previewHeader.append(element("h2", "", "图片预览"), button("收起", () => {
    showPreview = false;
    render();
    cards.get(pinKey(selected))?.node.focus({ preventScroll: true });
  }, "pg-quiet"));
  const previewMedia = element("div", "pg-detail-media");
  const previewImage = element("img", "pg-detail-image");
  previewImage.referrerPolicy = "no-referrer";
  const previewMessage = element("p", "pg-muted");
  previewMedia.append(previewImage, previewMessage);
  const previewTitle = element("p", "pg-detail-title");
  const previewSize = element("p", "pg-muted pg-detail-size");
  const previewActions = element("div", "pg-preview-actions");
  const previewLink = element("a", "pg-auth-link", "打开原 Pin");
  previewLink.target = "_blank";
  previewLink.rel = "noopener noreferrer";
  const savePin = button("加入画板", () => {
    if (!selected || closeSave) return;
    closeSave = openBoardSave({ request, pin: selected, onClose: () => { closeSave = null; } });
  }, "pg-quiet");
  previewActions.append(savePin, previewLink);
  preview.append(previewHeader, previewMedia, previewTitle, previewSize, previewActions);
  body.append(side, main, preview);

  const footer = element("footer", "pg-foot");
  const selection = element("div", "pg-selection");
  const selectionThumb = element("img", "pg-selection-thumb");
  selectionThumb.alt = "";
  selectionThumb.referrerPolicy = "no-referrer";
  const selectionTitle = element("span");
  const selectionPreview = button("预览", revealPreview, "pg-quiet");
  selection.append(selectionThumb, selectionTitle, selectionPreview);
  const footerActions = element("div", "pg-foot-actions");
  const targetHost = element("div", "pg-target");
  const send = button("送入工作流", sendToWorkflow, "pg-primary");
  const sendStatus = element("p", "pg-send-status pg-error");
  sendStatus.setAttribute("role", "status");
  footerActions.append(targetHost, send);
  footer.append(selection, footerActions, sendStatus);
  dialog.append(header, body, footer);

  const account = accountSettings({ json, caption: accountCaption, onChange: (status, changedCredential) => {
    if (closed) return;
    if (changedCredential || !status.connected) resetBoards();
    if (mode !== "boards") return;
    if (status.connected) {
      if (!boardsLoaded && !boardsLoading) loadBoards();
      if (board && !cards.size && !pinsLoaded && !loading && !loadError) loadPins();
    }
    render();
  } });

  function close() {
    if (closed) return;
    closed = true;
    pinsRequest.abort();
    boardRequest.abort();
    closeSave?.();
    account.close();
    dialog.close();
    dialog.remove();
    onClose({ mode, query, draftQuery: phrase.value, shape: activeShape, board, selected, bookmark, loaded: pinsLoaded,
      items: Array.from(cards.values(), row => row.pin) });
    previousFocus?.focus({ preventScroll: true });
  }

  function resetPins() {
    pinsRequest.abort();
    pinsRequest = new AbortController();
    bookmark = null;
    loading = false;
    pinsLoaded = false;
    loadError = "";
    selected = null;
    showPreview = false;
    sendStatus.textContent = "";
    cards.clear();
    masonry.replaceChildren();
    results.scrollTop = 0;
  }

  function resetBoards() {
    boardRequest.abort();
    boardRequest = new AbortController();
    boardsLoading = boardsLoaded = false;
    boardError = "";
    boardBookmark = null;
    board = null;
    boards.clear();
    boardList.replaceChildren();
    if (mode === "boards") resetPins();
  }

  function changeSource(next) {
    if (mode === next) return;
    mode = next;
    resetPins();
    if (mode === "search" && query) loadPins();
    if (mode === "boards") {
      if (board) loadPins();
      else if (account.status?.connected && !boardsLoaded && !boardsLoading) loadBoards();
    }
    render();
  }

  function runSearch(value) {
    const term = value.trim();
    if (!term) { phrase.focus(); return; }
    query = term;
    resetPins();
    loadPins();
  }

  function retryPins() {
    if (mode === "boards" && !account.status?.connected) account.open();
    else if (mode === "boards" && !board) loadBoards(false);
    else loadPins(cards.size > 0);
  }

  function matchesShape(row) {
    return activeShape === "all" || row.shape === activeShape;
  }

  function addPin(pin) {
    if (!pin) return;
    const original = pinterestImageUrl(pin.image_url);
    const thumbnail = pinterestThumbnailUrl(pin);
    const id = pinKey(pin);
    if (cards.has(id) || !original) return;
    const card = button("", () => choose(pin), "pg-card");
    card.dataset.pinId = id;
    const title = pinTitle(pin);
    card.setAttribute("aria-label", title === "Pinterest 图片" ? `Pinterest 图片 ${cards.size + 1}` : title);
    setPressed(card, false);
    const img = element("img");
    img.alt = "";
    img.decoding = "async";
    img.referrerPolicy = "no-referrer";
    const ratio = imageAspect(pin);
    const row = { node: card, pin, shape: ratio ? imageShape(ratio) : null };
    if (ratio) {
      img.style.setProperty("--pg-image-ratio", `${pin.width} / ${pin.height}`);
      card.dataset.shape = row.shape;
    }
    const sign = element("span", "pg-card-check", "已选");
    const unavailable = element("span", "pg-card-unavailable", "预览无法加载");
    unavailable.hidden = true;
    img.addEventListener("load", () => {
      const { naturalWidth: width, naturalHeight: height } = img;
      if (!width || !height) return;
      row.shape ||= imageShape(width / height);
      card.dataset.shape = row.shape;
      if (!ratio) img.style.setProperty("--pg-image-ratio", `${width} / ${height}`);
      card.hidden = !matchesShape(row);
      renderResults();
    });
    const noThumbnail = () => {
      row.shape ||= "unavailable";
      img.hidden = true;
      unavailable.hidden = false;
      card.hidden = !matchesShape(row);
      renderResults();
    };
    img.addEventListener("error", noThumbnail);
    card.append(img, unavailable, sign);
    card.hidden = !matchesShape(row);
    cards.set(id, row);
    masonry.append(card);
    if (thumbnail) img.src = thumbnail;
    else noThumbnail();
  }

  async function loadPins(append = false) {
    if (loading || (append && !bookmark) || (mode === "search" ? !query : !board)) return;
    loading = true;
    loadError = "";
    const signal = pinsRequest.signal;
    const currentBookmark = append ? bookmark : null;
    const path = mode === "search" ? "/search" : bookmarkPath(`/boards/${encodeURIComponent(board.id)}/pins`, currentBookmark);
    const options = mode === "search" ? jsonPost({ query, bookmark: currentBookmark }) : {};
    render();
    try {
      const value = await json(path, { ...options, signal });
      if (signal.aborted || closed) return;
      for (const pin of Array.isArray(value.items) ? value.items : []) addPin(pin);
      bookmark = value.bookmark && value.bookmark !== currentBookmark ? value.bookmark : null;
      pinsLoaded = true;
    } catch (error) { if (!signal.aborted && error.name !== "AbortError") loadError = error.message; }
    finally {
      if (!signal.aborted && !closed) { loading = false; render(); }
    }
  }

  async function loadBoards(append = false) {
    if (boardsLoading || (append && !boardBookmark)) return;
    boardsLoading = true;
    boardError = "";
    const signal = boardRequest.signal;
    const currentBookmark = append ? boardBookmark : null;
    render();
    try {
      const value = await json(bookmarkPath("/boards", currentBookmark), { signal });
      if (signal.aborted || closed) return;
      for (const item of Array.isArray(value.items) ? value.items : []) {
        if (item?.id == null || boards.has(String(item.id))) continue;
        const itemButton = button(item.name || `画板 #${item.id}`, () => {
          if (String(board?.id) === String(item.id)) return;
          board = item;
          resetPins();
          loadPins();
        }, "pg-board");
        boards.set(String(item.id), itemButton);
        boardList.append(itemButton);
      }
      boardsLoaded = true;
      boardBookmark = value.bookmark && value.bookmark !== currentBookmark ? value.bookmark : null;
    } catch (error) { if (!signal.aborted && error.name !== "AbortError") boardError = error.message; }
    finally {
      if (!signal.aborted && !closed) { boardsLoading = false; render(); }
    }
  }

  function choose(pin, showImage = true) {
    selected = pin;
    showPreview = false;
    sendStatus.textContent = "";
    const thumbnail = pinterestThumbnailUrl(pin);
    if (thumbnail) selectionThumb.src = thumbnail;
    else selectionThumb.removeAttribute("src");
    if (showImage) revealPreview();
    else render();
  }

  function revealPreview() {
    if (!selected) return;
    const url = pinterestImageUrl(selected.image_url);
    if (!url) return;
    showPreview = true;
    previewTitle.textContent = pinTitle(selected);
    previewImage.alt = pinTitle(selected);
    previewImage.hidden = true;
    previewMessage.textContent = "正在加载大图…";
    previewSize.textContent = "";
    previewImage.src = url;
    render();
  }

  previewImage.addEventListener("load", () => {
    previewImage.hidden = false;
    previewMessage.textContent = "";
    previewSize.textContent = `${previewImage.naturalWidth} × ${previewImage.naturalHeight}`;
  });
  previewImage.addEventListener("error", () => {
    previewImage.hidden = true;
    previewMessage.textContent = "大图无法预览。可以重选图片或在工作流中尝试加载。";
  });

  async function sendToWorkflow() {
    if (!selected || sending) return;
    sending = true;
    sendStatus.textContent = "";
    render();
    try { await onPick(selected); close(); }
    catch (error) {
      if (!closed) sendStatus.textContent = error?.message || "未能送入工作流，请检查目标节点。";
    } finally { sending = false; if (!closed) render(); }
  }

  function renderResults() {
    let visible = 0, pending = 0;
    for (const row of cards.values()) {
      if (matchesShape(row)) visible++;
      if (!row.shape) pending++;
    }
    const summary = activeShape === "all" ? `${cards.size} 张图片` : `显示 ${visible} / ${cards.size} 张`;
    const countText = cards.size ? summary : "";
    if (count.textContent !== countText) count.textContent = countText;
    masonry.hidden = visible === 0;
    empty.hidden = visible > 0;
    examplesRow.hidden = true;
    emptyAction.hidden = true;
    emptyDescription.textContent = "";

    if (!empty.hidden) {
      if (loading || (cards.size && pending)) emptyTitle.textContent = "正在读取图片…";
      else if (loadError) {
        emptyTitle.textContent = "图片加载失败";
        emptyDescription.textContent = loadError;
        emptyAction.textContent = "重试";
        emptyAction.hidden = false;
      } else if (cards.size) {
        emptyTitle.textContent = "当前图片里没有这个画幅";
        emptyDescription.textContent = "可以换个画幅，或加载更多图片。";
      } else if (mode === "search") {
        emptyTitle.textContent = query ? "没有找到符合关键词的图片" : "搜一组视觉参考";
        emptyDescription.textContent = query ? "试试更短的词组，或从下方的方向开始。" : "可以从构图、穿搭、光线或视觉风格开始。";
        examplesRow.hidden = false;
      } else if (!account.status?.connected) {
        emptyTitle.textContent = "连接 Pinterest 后查看我的画板";
        emptyAction.textContent = "连接 Pinterest";
        emptyAction.hidden = false;
      } else if (board) emptyTitle.textContent = "这个画板里暂无图片";
      else if (boardsLoading) emptyTitle.textContent = "正在读取画板…";
      else if (boardError) {
        emptyTitle.textContent = "画板加载失败";
        emptyDescription.textContent = boardError;
        emptyAction.textContent = "重试";
        emptyAction.hidden = false;
      } else emptyTitle.textContent = boards.size ? "从侧栏打开一个画板" : "账号里暂无画板";
    }

    pagination.hidden = !bookmark && !(visible && loadError);
    more.hidden = !bookmark;
    more.disabled = loading;
    more.textContent = loading ? "加载中…" : "加载更多";
    paginationMessage.textContent = visible ? loadError : "";
  }

  function render() {
    const inBoards = mode === "boards";
    const connected = account.status?.connected;
    setPressed(searchSource, !inBoards);
    setPressed(boardSource, inBoards);
    boardList.hidden = !inBoards;
    boardsMessage.hidden = !inBoards;
    boardsMessage.textContent = boardsLoading ? "正在读取画板…" : boardError || (connected ? "" : "连接账号后查看画板");
    boardsMore.hidden = !inBoards || (!boardBookmark && !boardError);
    boardsMore.disabled = boardsLoading;
    boardsMore.textContent = boardError ? "重试画板" : "更多画板";
    for (const [id, item] of boards) setPressed(item, id === String(board?.id));
    search.hidden = inBoards;
    boardTitle.hidden = !inBoards;
    boardTitle.textContent = board?.name || "我的画板";
    for (const [shape, item] of shapeButtons) setPressed(item, shape === activeShape);
    for (const [id, row] of cards) setPressed(row.node, id === pinKey(selected));
    preview.hidden = !selected || !showPreview;
    const originalLink = pinPermalink(selected);
    previewLink.hidden = !originalLink;
    if (originalLink) previewLink.href = originalLink;
    else previewLink.removeAttribute("href");
    body.classList.toggle("pg-has-preview", !preview.hidden);
    selectionThumb.hidden = !selected || !selectionThumb.hasAttribute("src");
    selectionTitle.textContent = selected ? pinTitle(selected) : "未选择图片";
    selectionPreview.hidden = !selected || showPreview;
    if (!mountTarget) targetHost.textContent = typeof targetLabel === "function" ? targetLabel() : targetLabel;
    send.disabled = !selected || sending;
    send.textContent = sending ? "正在送入…" : "送入工作流";
    sendStatus.hidden = !sendStatus.textContent;
    renderResults();
  }

  dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
  if (mountTarget) mountTarget(targetHost);
  for (const item of initialState.items ?? []) addPin(item);
  if (initialState.selected && pinterestImageUrl(initialState.selected.image_url)) choose(initialState.selected, previewOnOpen);
  render();
  document.body.append(dialog);
  dialog.showModal();
  phrase.focus();
  account.refresh();
  if (mode === "search" && query && !cards.size && !pinsLoaded) loadPins();
  return close;
}
