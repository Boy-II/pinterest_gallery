export function pinterestImageUrl(value) {
  if (typeof value !== "string" || !value.trim()) return "";
  try {
    const url = new URL(value);
    if (url.protocol === "https:" && !url.username && !url.password && !url.port &&
        (url.hostname === "pinimg.com" || url.hostname.endsWith(".pinimg.com"))) return url.href;
  } catch { /* Keep invalid media out of the gallery. */ }
  return "";
}

export function pinterestThumbnailUrl(pin) {
  const url = pinterestImageUrl(pin?.thumbnail_url);
  return url && url !== pinterestImageUrl(pin?.image_url) ? url : "";
}

export function imageAspect({ width, height }) {
  return Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0 ? width / height : 0;
}

export function imageShape(aspect) {
  return aspect > 1.12 ? "landscape" : aspect < 1 / 1.12 ? "portrait" : "square";
}
