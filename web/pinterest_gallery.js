import { api } from "../../scripts/api.js";
import { app } from "../../scripts/app.js";
import { createInlineGallery } from "./gallery_inline.js?v=4";
import { openBoardSave, openGallery, openGalleryAccount, subscribeAccountChanges } from "./gallery_panel.js?v=4";
import { pinterestImageUrl } from "./gallery_media.js";

const loaderType = "PinterestGalleryLoader";
const openCommand = "pinterest-gallery.open";
const galleryTitle = "Pinterest 画廊";
const widgetHeight = 345;
const galleryByNode = new WeakMap();
const request = (url, options) => api.fetchApi(url, options);
let closeGallery, closeOverlay;

function loadGalleryStyle() {
  for (const stylesheet of ["gallery_panel.css", "gallery_inline.css"]) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = new URL(`./${stylesheet}?v=4`, import.meta.url).href;
    document.head.append(link);
  }
}

function selectedWidget(node) {
  return node?.widgets?.find(widget => widget.name === "selected_pin");
}

function pinUrl(value) {
  const url = pinterestImageUrl(value);
  if (!url) throw new Error("这张图的地址不能用于 Pinterest 加载节点。");
  return url;
}

function readSelection(node) {
  try {
    const pin = JSON.parse(selectedWidget(node)?.value || "null");
    return pinterestImageUrl(pin?.image_url) ? pin : null;
  } catch {
    return null;
  }
}

function addPinMetadata(pin, selection) {
  if (typeof pin.pin_id === "string" && /^\d+$/.test(pin.pin_id)) selection.pin_id = pin.pin_id;
  if (typeof pin.source_url === "string") selection.source_url = pin.source_url;
  try {
    if (pin.thumbnail_url) selection.thumbnail_url = pinUrl(pin.thumbnail_url);
  } catch { /* The original image remains available for browsers without a thumbnail. */ }
  if (Number.isInteger(pin.width) && pin.width > 0) selection.width = pin.width;
  if (Number.isInteger(pin.height) && pin.height > 0) selection.height = pin.height;
  return selection;
}

function outputSelection(node, pin) {
  const widget = selectedWidget(node);
  if (!widget) throw new Error("当前工作流里的画廊节点已移除，请重新选择节点。");
  const selection = addPinMetadata(pin, {
    id: String(pin.id ?? pin.pin_id ?? ""),
    image_url: pinUrl(pin.image_url),
    title: typeof pin.title === "string" ? pin.title.trim().slice(0, 150) : "",
  });
  node.graph?.beforeChange?.();
  try {
    widget.value = JSON.stringify(selection);
    galleryByNode.get(node)?.applySelection(selection);
    node.setDirtyCanvas?.(true, true);
  } finally {
    node.graph?.afterChange?.();
  }
}

function nodeLabel(node) {
  return `${node.title || galleryTitle} #${node.id}`;
}

function openForWorkflow(preferredNode, initialState, previewOnOpen = false) {
  if (closeGallery) return;
  const graph = preferredNode?.graph ?? app.canvas?.graph ?? app.graph;
  const loaders = (graph?._nodes ?? []).filter(node => node.type === loaderType);
  const selectedLoaders = loaders.filter(node => app.canvas?.selected_nodes?.[node.id] === node);
  let selected = preferredNode && loaders.includes(preferredNode) ? preferredNode :
    selectedLoaders.length === 1 ? selectedLoaders[0] : loaders[0];
  const sourceNode = selected;
  const inline = galleryByNode.get(sourceNode);

  closeGallery = openGallery({
    request,
    initialState: initialState ?? inline?.getState(),
    previewOnOpen,
    targetLabel: () => selected ? nodeLabel(selected) : "此工作流还没有 Pinterest 画廊",
    mountTarget: loaders.length > 1 ? host => {
      const select = document.createElement("select");
      select.setAttribute("aria-label", "送入的画廊节点");
      for (const node of loaders) {
        const option = new Option(nodeLabel(node), String(node.id), false, node === selected);
        select.add(option);
      }
      select.addEventListener("change", () => {
        selected = loaders.find(node => String(node.id) === select.value);
      });
      host.replaceChildren(select);
    } : undefined,
    onPick(pin) {
      if (!selected || graph?.getNodeById?.(selected.id) !== selected) {
        throw new Error("请先打开 Pinterest 三节点收藏工作流，再把图片送入其中的画廊节点。");
      }
      outputSelection(selected, pin);
    },
    onClose(state) {
      closeGallery = null;
      inline?.applyState({ ...state, selected: readSelection(sourceNode) });
    },
  });
}

function openOverlay(open, options) {
  if (closeOverlay) return;
  closeOverlay = open({ request, ...options, onClose: () => { closeOverlay = null; } });
}

app.registerExtension({
  name: "pinterest_gallery.widget",
  setup: loadGalleryStyle,
  commands: [{ id: openCommand, label: "Pinterest 画廊", function: () => openForWorkflow() }],
  menuCommands: [{ path: ["Extensions"], commands: [openCommand] }],
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== loaderType) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      const result = onNodeCreated?.apply(this, args);
      const widget = selectedWidget(this);
      if (widget) {
        // Keep selected_pin serialized so workflows saved by the old widget load as before.
        widget.computeSize = () => [0, -4];
        widget.draw = () => {};
      }

      const inline = createInlineGallery({
        request,
        getSelection: () => readSelection(this),
        onPick: pin => outputSelection(this, pin),
        onExpand: state => openForWorkflow(this, state),
        onPreview: (pin, state) => openForWorkflow(this, { ...state, selected: pin }, true),
        onSave: pin => openOverlay(openBoardSave, { pin }),
        onAccount: () => openOverlay(openGalleryAccount),
      });
      const unsubscribeAccount = subscribeAccountChanges(inline.refreshAccount);
      galleryByNode.set(this, inline);
      inline.element.style.setProperty("--pgi-height", "100%");
      this.addDOMWidget("pinterest_inline_gallery", "div", inline.element, {
        serialize: false, hideOnZoom: true, margin: 0, getMinHeight: () => widgetHeight,
        getValue: () => "", setValue: () => {},
      });

      const onConfigure = this.onConfigure;
      this.onConfigure = (...config) => {
        const configured = onConfigure?.apply(this, config);
        if (this.title === "Pinterest Gallery Loader") this.title = galleryTitle;
        this.setSize([Math.max(this.size[0], 300), Math.max(this.size[1], widgetHeight + 40)]);
        inline.applySelection(readSelection(this));
        return configured;
      };

      const onRemoved = this.onRemoved;
      this.onRemoved = (...args) => {
        unsubscribeAccount();
        inline.dispose();
        galleryByNode.delete(this);
        return onRemoved?.apply(this, args);
      };

      this.title = galleryTitle;
      this.setSize([Math.max(this.size[0], 560), Math.max(this.size[1], 460)]);
      return result;
    };
  },
});
