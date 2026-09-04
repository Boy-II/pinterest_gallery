import os
import json
from PIL import Image, ImageOps
import re
import requests
import base64
import io
import numpy as np
import torch
import boto3
import comfy
import time
import urllib.parse
import random
from PIL import ImageDraw, ImageFont
import server
from aiohttp import web

NODE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(NODE_DIR, "config.json")

def load_config():
    if not os.path.exists(CONFIG_FILE): return {}
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except: return {}

def save_config(data):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e: print(f"Gelbooru: Error saving config: {e}")

prompt_server = server.PromptServer.instance

@prompt_server.routes.get("/gelbooru_gallery/api_key_status")
async def get_gelbooru_api_key_status(request):
    config = load_config()
    return web.json_response({"has_key": bool(config.get("gelbooru_api_key") and config.get("gelbooru_user_id"))})

@prompt_server.routes.post("/gelbooru_gallery/save_api_key")
async def save_gelbooru_api_key(request):
    try:
        data = await request.json()
        credentials = data.get("credentials", "")
        parsed = urllib.parse.parse_qs(credentials.lstrip('&'))
        api_key = parsed.get('api_key', [''])[0]
        user_id = parsed.get('user_id', [''])[0]
        if not api_key or not user_id:
            return web.json_response({"status": "error", "message": "Paste the full &api_key=...&user_id=... string"}, status=400)
        config = load_config()
        config["gelbooru_api_key"] = api_key
        config["gelbooru_user_id"] = user_id
        save_config(config)
        return web.json_response({"status": "success"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)


def not_available_image():
    img = Image.new("RGB", (512, 512), color=(30, 30, 30))
    try:
        draw = ImageDraw.Draw(img)
        text = "gelbooru not available"
        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(((512 - tw) // 2, (512 - th) // 2), text, fill=(200, 200, 200), font=font)
    except Exception:
        pass
    return img


def _resolve_credentials(api_credentials=""):
    """Parse an optional per-run "&api_key=...&user_id=..." override; fall
    back to the key saved via the 🔑 button (config.json) when left blank."""
    if api_credentials and api_credentials.strip():
        parsed = urllib.parse.parse_qs(api_credentials.lstrip('&'))
        return parsed.get('api_key', [''])[0], parsed.get('user_id', [''])[0]
    config = load_config()
    return config.get("gelbooru_api_key", ""), config.get("gelbooru_user_id", "")


def _response_preview(response, limit=500):
    text = getattr(response, "text", "") or ""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _read_api_json(response, site):
    try:
        return response.json()
    except ValueError as exc:
        status = getattr(response, "status_code", "unknown")
        headers = getattr(response, "headers", {}) or {}
        content_type = headers.get("content-type", "unknown")
        preview = _response_preview(response)
        details = f"{site} API returned non-JSON response (HTTP {status}, content-type={content_type})"
        if preview:
            details += f": {preview}"
        raise ValueError(details) from exc


def _posts_from_api_response(response, site):
    data = _read_api_json(response, site)
    if site == "Gelbooru":
        return data.get('post', []) if isinstance(data, dict) else []
    return data if isinstance(data, list) else []


def _api_headers():
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }


def _refresh_file_url(post_id, site="Gelbooru", api_credentials=""):
    if not post_id:
        return ""
    api_key, user_id = _resolve_credentials(api_credentials)
    base = "https://gelbooru.com/index.php" if site == "Gelbooru" else "https://api.rule34.xxx/index.php"
    url = f"{base}?page=dapi&s=post&q=index&id={post_id}&json=1"
    if api_key and user_id:
        url += f"&api_key={api_key}&user_id={user_id}"
    try:
        r = requests.get(url, timeout=10, verify=True, headers=_api_headers())
        posts = _posts_from_api_response(r, site)
        if posts:
            return posts[0].get("file_url", "")
    except Exception:
        pass
    return ""


COLORED_BG = ['black_background', 'aqua_background', 'white_background', 'colored_background', 'gray_background', 'blue_background', 'green_background', 'red_background', 'brown_background', 'purple_background', 'yellow_background', 'orange_background', 'pink_background', 'plain', 'transparent_background', 'simple_background', 'two-tone_background', 'grey_background']
ADD_BG = ['outdoors', 'indoors']
BW_BG = ['monochrome', 'greyscale', 'grayscale']


def load_bad_tags():
    path = os.path.join(os.path.dirname(__file__), 'bad_tags.txt')
    if os.path.exists(path):
        with open(path, 'r') as f:
            return [t.strip() for t in f.read().split(',') if t.strip()]
    return []

def load_good_tags():
    path = os.path.join(os.path.dirname(__file__), 'good_tags.txt')
    if os.path.exists(path):
        with open(path, 'r') as f:
            return [t.strip() for t in f.read().split(',') if t.strip()]
    return []


#urls to image from https://github.com/wmatson/easy-comfy-nodes/blob/main/__init__.py#L140
def loadImageFromUrl(url):
    if url.startswith("data:image/"):
        i = Image.open(io.BytesIO(base64.b64decode(url.split(",")[1])))
    elif url.startswith("s3://"):
        s3 = boto3.client('s3')
        bucket, key = url.split("s3://")[1].split("/", 1)
        obj = s3.get_object(Bucket=bucket, Key=key)
        i = Image.open(io.BytesIO(obj['Body'].read()))
    else:
        time.sleep(0.1)
        response = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://gelbooru.com/",
        })
        if response.status_code != 200:
            raise Exception(response.text)

        # gelbooru serves the post page (200 + text/html) to non-browser clients
        ctype = response.headers.get("content-type", "") or ""
        if "image" not in ctype:
            raise Exception(f"URL did not return an image (content-type={ctype}): {url}")

        i = Image.open(io.BytesIO(response.content))

    i = ImageOps.exif_transpose(i)

    if i.mode != "RGBA":
        i = i.convert("RGBA")

    # recreate image to fix weird RGB image
    alpha = i.split()[-1]
    image = Image.new("RGB", i.size, (0, 0, 0))
    image.paste(i, mask=alpha)

    image = np.array(image).astype(np.float32) / 255.0
    image = torch.from_numpy(image)[None,]
    if "A" in i.getbands():
        mask = np.array(i.getchannel("A")).astype(np.float32) / 255.0
        mask = 1.0 - torch.from_numpy(mask)
    else:
        mask = torch.zeros((64, 64), dtype=torch.float32, device="cpu")

    return (image, mask)

def pil2tensor(image):
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)

class UrlsToImage:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"urls": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False, "tooltip": "Image URLs to load, one per line (supports http://, data:image/, s3://)"})}}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES=("images",)
    OUTPUT_TOOLTIPS = ("Loaded image tensor(s) from the provided URLs",)
    FUNCTION = "execute"
    CATEGORY = "Gelbooru"

    def execute(self, urls):
        url_list = [u.strip() for u in urls.split("\n") if u.strip()]
        print(url_list)
        images = [loadImageFromUrl(u)[0] for u in url_list]
        firstImage = images[0]
        restImages = images[1:]
        if len(restImages) == 0:
            return (firstImage,)
        else:
            image1 = firstImage
            for image2 in restImages:
                if image1.shape[1:] != image2.shape[1:]:
                    image2 = comfy.utils.common_upscale(image2.movedim(-1, 1), image1.shape[2], image1.shape[1], "bilinear", "center").movedim(1, -1)
                image1 = torch.cat((image1, image2), dim=0)
            return (image1,)


class GelbooruRandom:
    _CACHE_KEY = "GelbooruRandom"
    _CACHE_VERSION = 3

    def __init__(self):
        self.last_prompt = ""
        self.previous_prompt = ""
        self.file_url = ""
        self.previous_file_url = ""
        self.post_id = ""
        self.previous_post_id = ""
        self.image = None
        self._load_cache()

    def _cache_path(self):
        return os.path.join(os.path.dirname(__file__), "gelbooru_prompt_cache.json")

    def _load_cache(self):
        path = self._cache_path()
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                cached = data.get(self._CACHE_KEY)
                if cached and cached.get('version') == self._CACHE_VERSION:
                    self.last_prompt = tuple(cached['last_prompt'])
                    self.file_url = cached['file_url']
                    self.previous_prompt = tuple(cached.get('previous_prompt', [])) if cached.get('previous_prompt') else ""
                    self.previous_file_url = cached.get('previous_file_url', "")
            except Exception:
                self.last_prompt = ""
                self.previous_prompt = ""
                self.file_url = ""
                self.previous_file_url = ""

    def _save_cache(self):
        if not self.last_prompt:
            return
        path = self._cache_path()
        try:
            data = {}
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
            data[self._CACHE_KEY] = {
                'version': self._CACHE_VERSION,
                'last_prompt': list(self.last_prompt),
                'previous_prompt': list(self.previous_prompt) if self.previous_prompt else [],
                'file_url': self.file_url,
                'previous_file_url': self.previous_file_url,
            }
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "use_custom_prompt": ("BOOLEAN", {"default": False, "tooltip": "Enable custom prompt override - replaces imgtags entirely with custom_prompt input"}),
                "site":(["Gelbooru", "Rule34"],{"tooltip": "Image board to search: Gelbooru or Rule34"}),
                "OR_tags": ("STRING", {"default": "", "multiline": True, "tooltip": "At least one of these tags must be present (broadens results). Example: blonde, red_hair finds images with EITHER blonde OR red_hair. Use when you want variants (hair colors, poses, outfits) in one search"}),
                "AND_tags": ("STRING", {"default": "", "multiline": True, "tooltip": "All of these tags must be present on the image (narrows results). Example: 1girl, smile finds images with BOTH 1girl AND smile"}),
"exclude_tag": ("STRING", {"default": "animated,", "multiline": True, "tooltip": "Tags to exclude from results (comma-separated)"}),
"remove_tags": ("STRING", {"default": "censored, mosaic_censoring, bar_censor", "multiline": True, "tooltip": "Tags to remove from the output imgtags (comma-separated). Useful for filtering out unwanted tags from the result"}),
"add_good_tags": ("BOOLEAN", {"default": True, "tooltip": "Prepend quality tags (masterpiece, best quality, etc.) from good_tags.txt"}),
"remove_bad_tags": ("BOOLEAN", {"default": True, "tooltip": "Remove known bad tags (watermark, text, censored, etc.) loaded from bad_tags.txt"}),
"convert_underscore": ("BOOLEAN", {"default": False, "tooltip": "Convert underscores to spaces in tags"}),
"change_background": (["Don't Change", "Add Background", "Remove Background", "Remove All"], {"default": "Don't Change", "tooltip": "Add or remove background-related tags from the result"}),
"change_color": (["Don't Change", "Colored", "Limited Palette", "Monochrome"], {"default": "Don't Change", "tooltip": "Add or remove color-related tags from the result"}),
                "Safe": ("BOOLEAN", {"default": True, "tooltip": "Include Safe/General rated posts"}),
                "Questionable": ("BOOLEAN", {"default": True, "tooltip": "Include Questionable/Sensitive rated posts"}),
                "Explicit": ("BOOLEAN", {"default": True, "tooltip": "Include Explicit rated posts"}),
                "score": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "tooltip": "Minimum score threshold (0 = no filter)"}),
                "api_credentials": ("STRING", {"default": "", "tooltip": "Optional per-run override, format: &api_key=YOUR_KEY&user_id=YOUR_ID. Leave blank to use the key saved via the 🔑 button below."}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "count": ("INT", {"default": 1, "min": 1, "max": 100, "tooltip": "Number of posts to fetch per request (max 100)"}),
                "use_last_prompt": (["Disabled", "Last Prompt", "Previous Prompt"], {"default": "Disabled", "tooltip": "Disabled: fetch new results. Last Prompt: reuse previous API response. Previous Prompt: reuse the response before last."}),
                "return_picture": ("BOOLEAN", {"default": False, "tooltip": "Download the first post's image and output as IMAGE tensor"}),
            },
            "optional": {
                "extra_text": ("STRING", {"forceInput": True, "multiline": True, "tooltip": "Generated text from another node, prepended before the final output (connect only, not editable)"}),
                "custom_prompt": ("STRING", {"forceInput": True, "multiline": True, "tooltip": "Completely replaces imgtags output when use_custom_prompt is enabled (connect only)"}),
            },
        }
        
    RETURN_TYPES = ("STRING","STRING","STRING", "INT", "INT", "STRING","STRING","IMAGE")
    RETURN_NAMES = ("imgtags","imgurl","imgid","width", "height", "source", "url","IMAGE")
    OUTPUT_TOOLTIPS = (
        "All tags of the fetched post(s), comma-separated",
        "Direct file URL(s) of the image(s)",
        "Post ID(s) on the image board",
        "Width of the image(s) in pixels",
        "Height of the image(s) in pixels",
        "Source website URL(s) of the post(s)",
        "The full API query URL used for the request",
        "Image tensor (only populated when return_picture is enabled)",
    )
    FUNCTION = "get_value"
    CATEGORY = "Gelbooru"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        if kwargs.get('use_last_prompt', 'Disabled') != "Disabled":
            return False
        return time.time()

    def get_value(self, use_custom_prompt=False, site="Gelbooru", OR_tags="", AND_tags="", exclude_tag="", remove_tags="", add_good_tags=True, remove_bad_tags=True, convert_underscore=False, change_background="Don't Change", change_color="Don't Change", Safe=True, Questionable=True, Explicit=True, score=0, api_credentials="", seed=0, count=1, use_last_prompt="Disabled", return_picture=False, extra_text=None, custom_prompt=None):
        cached = False
        img_url = ""
        if use_last_prompt == "Last Prompt" and self.last_prompt != "":
            cached = True
            imgtags, imgurl, imgid, width, height, source, url = self.last_prompt
            img_url = self.file_url
            if not self.post_id:
                self.post_id = imgid.split('\n')[0] if imgid else ""
        elif use_last_prompt == "Previous Prompt" and self.previous_prompt != "":
            cached = True
            imgtags, imgurl, imgid, width, height, source, url = self.previous_prompt
            img_url = self.previous_file_url
            if not self.previous_post_id:
                self.previous_post_id = imgid.split('\n')[0] if imgid else ""
            self.post_id = self.previous_post_id

        if not cached:
            api_key, user_id = _resolve_credentials(api_credentials)
            if not api_key and not user_id:
                raise ValueError(
                    "API credentials are required.\n"
                    "Click the 🔑 button on this node to save your Gelbooru API key.\n"
                    "Get one at the bottom of:\n"
                    "https://gelbooru.com/index.php?page=account&s=options"
                )
            #AND_tags
            AND_tags = AND_tags.rstrip(',').rstrip(' ')
            AND_tags = AND_tags.split(',')
            AND_tags = [item.strip().replace(' ', '_').replace('\\', '') for item in AND_tags]
            AND_tags = [item for item in AND_tags if item]
            if len(AND_tags) > 1:
                AND_tags = '+'.join(AND_tags)
            else:
                AND_tags = AND_tags[0] if AND_tags else ''
            #OR_tags
            OR_tags = OR_tags.rstrip(',').rstrip(' ')
            OR_tags = OR_tags.split(',')
            OR_tags = [item.strip().replace(' ', '_').replace('\\', '') for item in OR_tags]
            OR_tags = [item for item in OR_tags if item]
            if len(OR_tags) > 1:
                 if site == "Rule34":
                    OR_tags = '( ' + ' ~ '.join(OR_tags) + ' )'
                 else:
                    OR_tags = '{' + ' ~ '.join(OR_tags) + '}'
            else:
                OR_tags = OR_tags[0] if OR_tags else ''

            exclude_tag = '+'.join('-' + item.strip().replace(' ', '_') for item in exclude_tag.split(','))
            
            score, count = str(score), str(count)

            rate_exclusion = ""
            
            if not Safe: 
                if site == "Rule34":
                    rate_exclusion += "+-rating%3asafe"
                elif site == "Gelbooru":
                    rate_exclusion += "+-rating%3ageneral"

            if not Questionable: 
                if site == "Rule34":
                    rate_exclusion += "+-rating%3aquestionable" 
                elif site == "Gelbooru":
                    rate_exclusion += "+-rating%3aquestionable+-rating%3aSensitive"

            if not Explicit: 
                if site == "Rule34":
                    rate_exclusion += "+-rating%3aexplicit" 
                elif site == "Gelbooru":
                    rate_exclusion += "+-rating%3aexplicit" 

            
            if site == "Rule34":
                base_url = "https://api.rule34.xxx/index.php"
            else:
                base_url = "https://gelbooru.com/index.php"
          
            query_params = (
                f"page=dapi&s=post&q=index&tags=sort%3arandom+"
                f"{exclude_tag}+{OR_tags}+{AND_tags}+{rate_exclusion}"
                f"+score%3a>{score}&api_key={api_key}&user_id={user_id}&limit={count}&json=1"
            )
            url = f"{base_url}?{query_params}".replace("-+", "")
            url = re.sub(r"\++", "+", url)
            
            time.sleep(0.1)
            response = requests.get(url, verify=True, headers=_api_headers())

            posts = _posts_from_api_response(response, site)

            imgtags = '\n'.join(post.get("tags", "").replace(" ", ", ") for post in posts)
            imgurl = '\n'.join(post.get("file_url", "") for post in posts)
            imgid = '\n'.join(str(post.get("id", "")) for post in posts)
            width = '\n'.join(str(post.get("width", 0)) for post in posts)
            height = '\n'.join(str(post.get("height", 0)) for post in posts)
            source = '\n'.join(post.get("source", "") for post in posts)

            # Shift current to previous before saving new
            if self.last_prompt:
                self.previous_prompt = self.last_prompt
                self.previous_file_url = self.file_url
                self.previous_post_id = self.post_id
            self.last_prompt = (imgtags, imgurl, imgid, width, height, source, url)
            self.file_url = imgurl.split('\n')[0] if imgurl else ""
            self.post_id = imgid.split('\n')[0] if imgid else ""
            self._save_cache()

        if use_custom_prompt and custom_prompt is not None:
            imgtags = custom_prompt
            # Don't apply any tag processing when custom_prompt overrides
        else:
            if remove_tags.strip():
                to_remove = set(t.strip().lower() for t in remove_tags.split(',') if t.strip())
                cleaned = []
                for line in imgtags.split('\n'):
                    tags = [t.strip() for t in line.split(',')]
                    tags = [t for t in tags if t.lower() not in to_remove]
                    cleaned.append(', '.join(tags))
                imgtags = '\n'.join(cleaned)

            # Remove bad tags from bad_tags.txt
            if remove_bad_tags:
                bad_tags = load_bad_tags()
                if bad_tags:
                    cleaned_lines = []
                    for line in imgtags.split('\n'):
                        tags = [t.strip() for t in line.split(',')]
                        tags = [t for t in tags if t.lower() not in bad_tags]
                        for bad in bad_tags:
                            if '*' in bad:
                                prefix = bad.replace('*', '').lower()
                                tags = [t for t in tags if prefix not in t.lower()]
                        cleaned_lines.append(', '.join(tags))
                    imgtags = '\n'.join(cleaned_lines)

            # Change background
            if change_background != "Don't Change":
                bg_lines = imgtags.split('\n')
                processed_lines = []
                for line in bg_lines:
                    tags = [t.strip() for t in line.split(',')]
                    if change_background == "Add Background":
                        tags = [t for t in tags if t.lower() not in COLORED_BG]
                        addition = 'detailed_background, ' + random.choice(ADD_BG)
                    elif change_background == "Remove Background":
                        tags = [t for t in tags if t.lower() not in ADD_BG]
                        addition = 'plain_background, simple_background, ' + random.choice(COLORED_BG)
                    else:
                        tags = [t for t in tags if t.lower() not in COLORED_BG + ADD_BG]
                        addition = ''
                    if addition:
                        tags.append(addition)
                    processed_lines.append(', '.join(tags))
                imgtags = '\n'.join(processed_lines)

            # Change color
            if change_color != "Don't Change":
                color_lines = imgtags.split('\n')
                processed_lines = []
                for line in color_lines:
                    tags = [t.strip() for t in line.split(',')]
                    if change_color == "Colored":
                        tags = [t for t in tags if t.lower() not in BW_BG]
                    elif change_color == "Limited Palette":
                        tags.append('(limited_palette:1.3)')
                    elif change_color == "Monochrome":
                        tags.append('monochrome, greyscale, grayscale')
                    processed_lines.append(', '.join(tags))
                imgtags = '\n'.join(processed_lines)

            # Convert underscore to spaces
            if convert_underscore:
                imgtags = imgtags.replace('_', ' ')

            # Prepend extra_text to the final output
            if extra_text:
                imgtags = extra_text + '\n' + imgtags

            # Prepend good_tags to the very beginning
            if add_good_tags:
                good_tags = load_good_tags()
                if good_tags:
                    imgtags = ', '.join(good_tags) + '\n' + imgtags

        if return_picture:
            referer = "https://gelbooru.com/" if site == "Gelbooru" else "https://rule34.xxx/"

            def _try_download(url_to_try, store=False):
                if not url_to_try:
                    return None
                try:
                    r = requests.get(url_to_try, timeout=5, headers={"User-Agent": "Mozilla/5.0", "Referer": referer})
                    if r.status_code == 200 and 'image' in (r.headers.get('content-type', '') or ''):
                        try:
                            im = Image.open(io.BytesIO(r.content))
                        except Exception:
                            im = None
                        if im is not None:
                            if im.mode != "RGB":
                                im = im.convert("RGB")
                            if store:
                                self.image = im
                                self.file_url = url_to_try
                            return im
                except Exception:
                    pass
                return None

            def _refresh_and_retry():
                fresh_url = _refresh_file_url(self.post_id, site, api_credentials)
                if fresh_url and fresh_url != img_url:
                    print(f"[INFO] Refreshed cached image URL: {fresh_url}")
                    img = _try_download(fresh_url, store=True)
                    if img is not None:
                        # Update cache with new file_url
                        old = list(self.last_prompt)
                        old[1] = fresh_url  # imgurl
                        self.last_prompt = tuple(old)
                        self.file_url = fresh_url
                        self._save_cache()
                        return img
                return None

            if cached:
                if self.file_url == img_url and self.image is not None:
                    img = self.image
                else:
                    img = _try_download(img_url, store=True)
                    if img is None:
                        img = _refresh_and_retry()
                    if img is None:
                        print(f"[WARN] All download attempts failed for post {self.post_id}")
                        img = not_available_image()
            else:
                img_url = self.file_url
                img = _try_download(img_url, store=True)
                if img is None:
                    img = not_available_image()
            return (imgtags, imgurl, imgid, width, height, source, url, pil2tensor(img))
        else:
            empty_image = not_available_image()
            return (imgtags, imgurl, imgid, width, height, source, url, pil2tensor(empty_image))

class GelbooruID:
    _CACHE_KEY = "GelbooruID"

    def __init__(self):
        self.last_prompt = ""
        self.file_url = ""
        self.post_id = ""
        self.image = None
        self._load_cache()

    def _cache_path(self):
        return os.path.join(os.path.dirname(__file__), "gelbooru_prompt_cache.json")

    def _load_cache(self):
        path = self._cache_path()
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                cached = data.get(self._CACHE_KEY)
                if cached:
                    self.last_prompt = tuple(cached['last_prompt'])
                    self.file_url = cached['file_url']
                    self.post_id = cached.get('post_id', '')
            except Exception:
                self.last_prompt = ""
                self.file_url = ""
                self.post_id = ""

    def _save_cache(self):
        if not self.last_prompt:
            return
        path = self._cache_path()
        try:
            data = {}
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
            data[self._CACHE_KEY] = {
                'last_prompt': list(self.last_prompt),
                'file_url': self.file_url,
                'post_id': self.post_id,
            }
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "post_id": ("STRING", {"default": "", "tooltip": "Numeric ID of the Gelbooru post to fetch"}),
                "use_last_prompt": ("BOOLEAN", {"default": False, "tooltip": "Reuse the previous API response without making a new request"}),
                "return_picture": ("BOOLEAN", {"default": False, "tooltip": "Download the post's image and output as IMAGE tensor"}),
            },
        }
        
    RETURN_TYPES = ("STRING","STRING","STRING", "INT", "INT", "STRING","IMAGE")
    RETURN_NAMES = ("imgtags","imgurl","imgid","width", "height", "source","IMAGE")
    OUTPUT_TOOLTIPS = (
        "All tags of the fetched post, comma-separated",
        "Direct file URL of the image",
        "Post ID on the image board",
        "Width of the image in pixels",
        "Height of the image in pixels",
        "Source website URL of the post",
        "Image tensor (only populated when return_picture is enabled)",
    )
    FUNCTION = "get_value"
    CATEGORY = "Gelbooru"
  
    def get_value(self, post_id, use_last_prompt=False, return_picture=False):
        cached = use_last_prompt and self.last_prompt != ""
        if cached:
            imgtags, imgurl, imgid, width, height, source = self.last_prompt
            img_url = self.file_url
            if not self.post_id:
                self.post_id = imgid.split('\n')[0] if imgid else ""
        else:
            url = "https://gelbooru.com/index.php?page=dapi&s=post&q=index&id="+post_id+"&json=1"
            time.sleep(0.1)
            posts = _posts_from_api_response(requests.get(url, headers=_api_headers()), "Gelbooru")

            imgtags = '\n'.join(post.get("tags", "").replace(" ", ", ") for post in posts)
            imgurl = '\n'.join(post.get("file_url", "") for post in posts)
            imgid = '\n'.join(str(post.get("id", "")) for post in posts)
            width = '\n'.join(str(post.get("width", 0)) for post in posts)
            height = '\n'.join(str(post.get("height", 0)) for post in posts)
            source = '\n'.join(post.get("source", "") for post in posts)

            self.last_prompt = (imgtags, imgurl, imgid, width, height, source)
            self.file_url = imgurl.split('\n')[0] if imgurl else ""
            self.post_id = imgid.split('\n')[0] if imgid else ""
            self._save_cache()

        if return_picture:
            referer = "https://gelbooru.com/"

            def _try_download(url_to_try, store=False):
                if not url_to_try:
                    return None
                try:
                    r = requests.get(url_to_try, timeout=5, headers={"User-Agent": "Mozilla/5.0", "Referer": referer})
                    if r.status_code == 200 and 'image' in (r.headers.get('content-type', '') or ''):
                        try:
                            im = Image.open(io.BytesIO(r.content))
                        except Exception:
                            im = None
                        if im is not None:
                            if im.mode != "RGB":
                                im = im.convert("RGB")
                            if store:
                                self.image = im
                                self.file_url = url_to_try
                            return im
                except Exception:
                    pass
                return None

            def _refresh_and_retry():
                fresh_url = _refresh_file_url(self.post_id, "Gelbooru")
                if fresh_url and fresh_url != img_url:
                    print(f"[INFO] Refreshed cached image URL: {fresh_url}")
                    img = _try_download(fresh_url, store=True)
                    if img is not None:
                        # Update cache with new file_url
                        old = list(self.last_prompt)
                        old[1] = fresh_url  # imgurl
                        self.last_prompt = tuple(old)
                        self.file_url = fresh_url
                        self._save_cache()
                        return img
                return None

            if cached:
                if self.file_url == img_url and self.image is not None:
                    img = self.image
                else:
                    img = _try_download(img_url, store=True)
                    if img is None:
                        img = _refresh_and_retry()
                    if img is None:
                        print(f"[WARN] All download attempts failed for post {self.post_id}")
                        img = not_available_image()
            else:
                img_url = self.file_url
                img = _try_download(img_url, store=True)
                if img is None:
                    img = not_available_image()
            return (imgtags, imgurl, imgid, width, height, source, pil2tensor(img))
        else:
            empty_image = not_available_image()
            return (imgtags, imgurl, imgid, width, height, source, pil2tensor(empty_image))


NODE_DISPLAY_NAME_MAPPINGS = {
    "GelbooruRandom": "Gelbooru (Random)",
    "GelbooruID": "Gelbooru (ID)",
    "UrlsToImage": "UrlsToImage",
}
