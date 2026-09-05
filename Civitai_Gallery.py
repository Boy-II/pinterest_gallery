import server
from aiohttp import web
import aiohttp
import os
import json
import torch
import numpy as np
from PIL import Image
import io
import urllib.request
import time
import folder_paths
import asyncio
import hashlib
import tempfile

download_tasks = {}

NODE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_STATE_FILE = os.path.join(NODE_DIR, "civitai_ui_state.json")
FAVORITES_FILE = os.path.join(NODE_DIR, "civitai_favorites.json")
CONFIG_FILE = os.path.join(NODE_DIR, "config.json")

def load_config():
    if not os.path.exists(CONFIG_FILE): return {}
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except: return {}

def save_config(data):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e: print(f"CivitaiGallery: Error saving config: {e}")

def load_ui_state():
    if not os.path.exists(UI_STATE_FILE): return {}
    try:
        with open(UI_STATE_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except: return {}

def save_ui_state(data):
    try:
        with open(UI_STATE_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e: print(f"CivitaiGallery: Error saving UI state: {e}")

def load_favorites():
    if not os.path.exists(FAVORITES_FILE): return {}
    try:
        with open(FAVORITES_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except: return {}

def save_favorites(data):
    try:
        with open(FAVORITES_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e: print(f"CivitaiGallery: Error saving favorites: {e}")

ALLOWED_CIVITAI_DOMAINS = {"civitai.com", "civitai.red"}

def resolve_domain(domain, international_version=False):
    if domain in ALLOWED_CIVITAI_DOMAINS:
        return domain
    return "civitai.red"

def get_full_filename_list(folder_key):
    file_list = []
    for folder_path in folder_paths.get_folder_paths(folder_key):
        if os.path.exists(folder_path):
            for root, dirs, files in os.walk(folder_path, followlinks=True):
                for file in files:
                    file_list.append(file)
    return list(set(file_list))

class CivitaiGalleryNode:
    @classmethod
    def IS_CHANGED(cls, selection_data, **kwargs):
        return selection_data

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "selection_data": ("STRING", {"default": "{}", "multiline": True, "forceInput": True}),
                "civitai_gallery_unique_id_widget": ("STRING", {"default": "", "multiline": False}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "IMAGE", "STRING", "STRING", "VIDEO")
    RETURN_NAMES = ("positive_prompt", "negative_prompt", "image", "info", "video_url", "video")
    FUNCTION = "get_selected_data"
    CATEGORY = "📜Asset Gallery/Civitai"

    def get_selected_data(self, unique_id, civitai_gallery_unique_id_widget="", selection_data="{}"):
        try:
            node_selection = json.loads(selection_data)
        except:
            node_selection = {}
        item_data = node_selection.get("item", {})
        should_download = node_selection.get("download_image", False)
        should_download_video = node_selection.get("download_video", False)
        meta = item_data.get("meta", {}) if item_data else {}
        pos_prompt = meta.get("prompt", "") if meta else ""
        neg_prompt = meta.get("negativePrompt", "") if meta else ""
        image_url = item_data.get("url", "") if item_data else ""
        video_url = image_url if item_data.get("type") == "video" else ""
        video = None
        info_string = json.dumps(item_data, indent=4, ensure_ascii=False)
        tensor = torch.zeros(1, 1, 1, 3)
        if should_download and image_url and item_data.get("type") != "video":
            print("CivitaiGalleryNode: Frontend reports image output is connected. Starting download.")
            try:
                req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=30) as response:
                    img_data = response.read()
                img = Image.open(io.BytesIO(img_data)).convert("RGB")
                img_array = np.array(img).astype(np.float32) / 255.0
                tensor = torch.from_numpy(img_array)[None,]
            except Exception as e:
                print(f"CivitaiGallery: Failed to download or process image from {image_url}. Error: {e}")
        elif should_download:
            print("CivitaiGalleryNode: Image output connected, but no URL was selected or found.")
        if should_download_video and video_url:
            try:
                video = _video_from_url(video_url)
            except Exception as e:
                print(f"CivitaiGallery: Failed to download or process video from {video_url}. Error: {e}")
        return (pos_prompt, neg_prompt, tensor, info_string, video_url, video)

prompt_server = server.PromptServer.instance

def _video_from_url(video_url):
    from comfy_api.latest import InputImpl

    ext = os.path.splitext(video_url.split("?", 1)[0])[1] or ".mp4"
    digest = hashlib.sha256(video_url.encode("utf-8")).hexdigest()[:16]
    try:
        temp_dir = folder_paths.get_temp_directory()
    except Exception:
        temp_dir = tempfile.gettempdir()
    os.makedirs(temp_dir, exist_ok=True)
    local_path = os.path.join(temp_dir, f"civitai_gallery_{digest}{ext}")
    if not os.path.exists(local_path):
        req = urllib.request.Request(video_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=60) as response:
            with open(local_path, "wb") as f:
                f.write(response.read())
    return InputImpl.VideoFromFile(local_path)


def _build_image_params(nsfw, sort, period, base_model, cursor, model_id, model_version_id):
    if model_version_id:
        params = {
            'modelVersionId': model_version_id,
            'limit': 50,
            'sort': sort,
            'period': period,
            'nsfw': nsfw,
        }
        if base_model:
            params['baseModels'] = base_model
    elif model_id:
        params = {
            'modelId': model_id,
            'limit': 50,
            'sort': sort,
            'period': period,
            'nsfw': nsfw,
        }
        if base_model:
            params['baseModels'] = base_model
    else:
        params = {
            'limit': 50,
            'nsfw': nsfw,
            'sort': sort,
            'period': period,
        }
        if base_model:
            params['baseModels'] = base_model

    params['withMeta'] = 'true'
    if cursor:
        params['cursor'] = cursor
    return params


def _build_model_search_params(query, base_model, cursor):
    params = {
        'limit': 8,
        'query': query,
    }
    if base_model:
        params['baseModels'] = base_model
    if cursor:
        params['cursor'] = cursor
    return params


async def _fetch_json(session, url, params, headers):
    async with session.get(url, params=params, headers=headers) as response:
        response.raise_for_status()
        return await response.json()


async def _fetch_keyword_images(session, base_domain, headers, query, base_model, nsfw, sort, period, cursor):
    models_url = f"https://{base_domain}/api/v1/models"
    images_url = f"https://{base_domain}/api/v1/images"
    models_data = await _fetch_json(
        session,
        models_url,
        _build_model_search_params(query, base_model, cursor),
        headers,
    )
    items = []
    for model in (models_data.get("items") or [])[:8]:
        model_id = model.get("id")
        if not model_id:
            continue
        image_params = _build_image_params(nsfw, sort, period, base_model, None, model_id, None)
        image_params["limit"] = 8
        image_data = await _fetch_json(session, images_url, image_params, headers)
        items.extend(image_data.get("items") or [])
        if len(items) >= 50:
            items = items[:50]
            break
    return {
        "items": items,
        "metadata": {"nextCursor": (models_data.get("metadata") or {}).get("nextCursor")},
    }


def _retry_delay_from_error(error, default=1.0):
    retry_after = getattr(error, "headers", {}).get("Retry-After") if getattr(error, "headers", None) else None
    try:
        return float(retry_after)
    except (TypeError, ValueError):
        return default


def _error_status_and_message(error):
    status = getattr(error, "status", 500) or 500
    if status == 503:
        return status, "Civitai model search is temporarily overloaded. Please retry."
    return status, str(error)


@prompt_server.routes.get("/civitai_gallery/images")
async def get_civitai_images(request):
    nsfw = request.query.get('nsfw', 'None')
    sort = request.query.get('sort', 'Most Reactions')
    period = request.query.get('period', 'Day')
    query = request.query.get('query', '').strip()
    base_model = request.query.get('baseModels', '').strip()
    international_version = request.query.get('international_version', 'false').lower() in ['true', '1']
    domain = request.query.get('domain', '')
    cursor = request.query.get('cursor', None)
    model_id = request.query.get('modelId', None)
    model_version_id = request.query.get('modelVersionId', None)
    
    base_domain = resolve_domain(domain, international_version)
    api_url = f"https://{base_domain}/api/v1/images"
    
    params = _build_image_params(nsfw, sort, period, base_model, cursor, model_id, model_version_id)

    config = load_config()
    api_key = config.get("civitai_api_key")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    timeout = aiohttp.ClientTimeout(total=60)
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                if query and not model_id and not model_version_id:
                    data = await _fetch_keyword_images(session, base_domain, headers, query, base_model, nsfw, sort, period, cursor)
                    return web.json_response(data)
                else:
                    data = await _fetch_json(session, api_url, params, headers)
                    return web.json_response(data)
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"CivitaiGallery: Failed to fetch images after {max_retries} attempts. Error: {e}")
                status, message = _error_status_and_message(e)
                return web.json_response({"error": message}, status=status)
            await asyncio.sleep(_retry_delay_from_error(e))
            print(f"CivitaiGallery: Connection failed, retrying ({attempt + 1}/{max_retries})...")

@prompt_server.routes.post("/civitai_gallery/set_ui_state")
async def set_civitai_ui_state(request):
    try:
        data = await request.json()
        node_id = str(data.get("node_id"))
        gallery_id = data.get("gallery_id")
        state = data.get("state")
        if not node_id or not gallery_id or state is None:
            return web.json_response({"status": "error", "message": "Missing required data"}, status=400)
        node_key = f"{gallery_id}_{node_id}"
        ui_states = load_ui_state()
        ui_states[node_key] = state
        save_ui_state(ui_states)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.get("/civitai_gallery/get_ui_state")
async def get_civitai_ui_state(request):
    try:
        node_id = request.query.get('node_id')
        gallery_id = request.query.get('gallery_id')
        if not node_id or not gallery_id:
            return web.json_response({})
        node_key = f"{gallery_id}_{node_id}"
        ui_states = load_ui_state()
        return web.json_response(ui_states.get(node_key, {}))
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.get("/civitai_gallery/get_all_favorites_data")
async def get_all_favorites_data(request):
    favorites = load_favorites()
    return web.json_response(favorites)

@prompt_server.routes.post("/civitai_gallery/toggle_favorite")
async def toggle_favorite(request):
    try:
        data = await request.json()
        item = data.get("item")
        if not item or 'id' not in item:
            return web.json_response({"status": "error", "message": "Invalid item data"}, status=400)
        item_id = str(item['id'])
        favorites = load_favorites()
        if item_id in favorites:
            del favorites[item_id]
            status = "removed"
        else:
            if 'meta' not in item or item['meta'] is None:
                item['meta'] = {}
            if 'tags' not in item:
                item['tags'] = []
            item['meta'].pop('prompt_saved', None)
            favorites[item_id] = item
            status = "added"
        save_favorites(favorites)
        return web.json_response({"status": status})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.post("/civitai_gallery/add_or_update_favorite")
async def add_or_update_favorite(request):
    try:
        data = await request.json()
        item = data.get("item")
        if not item or 'id' not in item:
            return web.json_response({"status": "error", "message": "Invalid item data"}, status=400)
        
        item_id = str(item['id'])
        favorites = load_favorites()
        favorites[item_id] = item
        save_favorites(favorites)
        
        return web.json_response({"status": "success", "message": "Favorite updated successfully."})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.get("/civitai_gallery/get_favorites_images")
async def get_favorites_images(request):
    try:
        page = int(request.query.get('page', '1'))
        limit = int(request.query.get('limit', '50'))
        
        favorites = load_favorites()
        items = list(favorites.values())
        
        filter_tags_str = request.query.get('fav_tags', '').strip().lower()
        filter_mode = request.query.get('fav_tag_mode', 'OR').upper()

        if filter_tags_str:
            filter_tags = {tag.strip() for tag in filter_tags_str.split(',') if tag.strip()}
            
            filtered_items = []
            for item in items:
                item_tags = {str(t).lower() for t in item.get('tags', [])}
                if filter_mode == 'AND':
                    if filter_tags.issubset(item_tags):
                        filtered_items.append(item)
                else:
                    if any(ft in item_tags for ft in filter_tags):
                        filtered_items.append(item)
            items = filtered_items

        total_items = len(items)
        start_index = (page - 1) * limit
        end_index = start_index + limit
        
        paginated_items = items[start_index:end_index]
        
        response_data = { 
            "items": paginated_items, 
            "metadata": {
                "totalItems": total_items,
                "currentPage": page,
                "pageSize": limit,
                "totalPages": (total_items + limit - 1) // limit
            }
        }
        
        return web.json_response(response_data)
    except Exception as e:
        print(f"CivitaiGallery: get_favorites_images error: {e}")
        return web.json_response({"error": str(e)}, status=500)

@prompt_server.routes.post("/civitai_gallery/download_model")
async def download_model(request):
    try:
        config = load_config()
        api_key = config.get("civitai_api_key")
        if not api_key:
            return web.json_response({"status": "error", "message": "Civitai API Key not found.", "reason": "API_KEY_MISSING"}, status=401)

        headers = { 
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        }
        data = await request.json()
        model_version_id = data.get("version_id")
        model_type = data.get("type", "").lower()
        international_version = data.get("international_version", False)
        domain = data.get("domain", "")

        if not model_version_id:
            return web.json_response({"status": "error", "message": "Missing model_version_id"}, status=400)

        base_domain = resolve_domain(domain, international_version)
        version_info_url = f"https://{base_domain}/api/v1/model-versions/{model_version_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(version_info_url, headers=headers) as response:
                if response.status != 200:
                    return web.json_response({"status": "error", "message": f"Failed to fetch model version info. Status: {response.status}"}, status=500)
                version_data = await response.json()

        model_file = version_data.get("files", [])[0]
        download_url = model_file.get("downloadUrl")
        filename = model_file.get("name")
        total_size = model_file.get("sizeKB", 0) * 1024

        if not download_url or not filename:
             return web.json_response({"status": "error", "message": "Could not find a valid download URL."}, status=404)

        type_mapping = {
            "checkpoint": "checkpoints", "lora": "loras", "locon": "loras", "dora": "loras",
            "lycoris": "loras", "textualinversion": "embeddings", "hypernetwork": "hypernetworks",
            "aestheticgradient": "embeddings", "controlnet": "controlnet", "motionmodule": "motion_modules",
            "vae": "vae", "upscaler": "upscale_models",
        }
        custom_folder_types = ["workflows", "wildcards", "poses", "detection"]
        primary_folder_path = None
        save_folder_key = type_mapping.get(model_type)
        if save_folder_key:
            primary_folder_path = folder_paths.get_folder_paths(save_folder_key)[0]
            if filename in get_full_filename_list(save_folder_key):
                return web.json_response({"status": "already_exists", "message": f"File already exists: {filename}"})
        elif model_type in custom_folder_types:
            models_dir = os.path.dirname(folder_paths.get_folder_paths('checkpoints')[0])
            primary_folder_path = os.path.join(models_dir, model_type.capitalize())
            if os.path.exists(os.path.join(primary_folder_path, filename)):
                 return web.json_response({"status": "already_exists", "message": f"File already exists: {filename}"})
        elif model_type == "motionmodule":
            primary_folder_path = os.path.join(folder_paths.get_folder_paths("custom_nodes")[0], "ComfyUI-AnimateDiff-Evolved", "models")
            if filename in os.listdir(primary_folder_path):
                return web.json_response({"status": "already_exists", "message": f"File already exists: {filename}"})
        else:
            return web.json_response({"status": "error", "message": f"Unknown model type: {model_type}"}, status=400)

        if not os.path.exists(primary_folder_path):
            os.makedirs(primary_folder_path)

        file_path = os.path.join(primary_folder_path, filename)

        task_id = f"download_{model_version_id}_{int(time.time())}"

        async def do_download():
            temp_file_path = file_path + ".downloading"
            download_tasks[task_id] = {"progress": 0, "total_size": total_size, "status": "downloading", "cancel_requested": False}
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(download_url, headers=headers, timeout=None) as response:
                            if response.status != 200:
                                raise Exception(f"Download failed with status: {response.status}")

                            with open(temp_file_path, 'wb') as f:
                                downloaded = 0
                                while True:
                                    if download_tasks.get(task_id, {}).get("cancel_requested"):
                                        raise Exception("Download cancelled by user.")

                                    chunk = await response.content.read(65536)
                                    if not chunk:
                                        break
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    download_tasks[task_id]["progress"] = downloaded

                            if os.path.exists(file_path):
                                os.remove(file_path)
                            os.rename(temp_file_path, file_path)

                            download_tasks[task_id]["status"] = "completed"
                            print(f"CivitaiGallery: Successfully downloaded '{filename}'")
                            break

                except Exception as e:
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)

                    is_cancelled = "cancelled" in str(e).lower()
                    
                    if is_cancelled or attempt == max_retries - 1:
                        print(f"CivitaiGallery: Download failed or cancelled for task {task_id}: {e}")
                        if download_tasks.get(task_id):
                            if is_cancelled:
                                download_tasks[task_id]["status"] = "cancelled"
                            else:
                                download_tasks[task_id]["status"] = "error"
                    else:
                        print(f"CivitaiGallery: Download connection failed, retrying ({attempt + 1}/{max_retries})...")
                        await asyncio.sleep(2)

        asyncio.create_task(do_download())

        return web.json_response({"status": "starting", "task_id": task_id})

    except Exception as e:
        print(f"CivitaiGallery: Error in download_model setup: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.post("/civitai_gallery/get_resource_info")
async def get_resource_info(request):
    try:
        data = await request.json()
        resources = data.get("resources", [])
        international_version = data.get("international_version", False)
        domain = data.get("domain", "")

        type_mapping = {
            "checkpoint": "checkpoints", "lora": "loras", "locon": "loras", "dora": "loras",
            "lycoris": "loras", "textualinversion": "embeddings", "hypernetwork": "hypernetworks",
            "aestheticgradient": "embeddings", "controlnet": "controlnet", "motionmodule": "motion_modules",
            "vae": "vae", "upscaler": "upscale_models",
        }
        custom_folder_types = ["workflows", "wildcards", "poses", "detection"]

        base_domain = resolve_domain(domain, international_version)

        async def fetch_info(session, resource):
            version_id = resource.get("modelVersionId")
            if version_id:
                url = f"https://{base_domain}/api/v1/model-versions/{version_id}"
            elif resource.get("hash"):
                url = f"https://{base_domain}/api/v1/model-versions/by-hash/{resource.get('hash')}"
            else:
                return resource

            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        version_data = await response.json()
                        model = version_data.get("model", {})
                        resource["modelName"] = model.get("name")
                        
                        model_type = model.get("type", "").lower()
                        resource["modelType"] = model_type
                        
                        if not resource.get("modelVersionId"):
                            resource["modelVersionId"] = version_data.get("id")
                        
                        if version_data.get("files"):
                            filename = version_data["files"][0].get("name")
                            resource["fileName"] = filename
                            resource["publishedAt"] = version_data.get("publishedAt")
                            resource["fileSizeKB"] = version_data["files"][0].get("sizeKB")
                            
                            save_folder_key = type_mapping.get(model_type)
                            if save_folder_key:
                                try:
                                    existing_files = get_full_filename_list(save_folder_key)
                                    resource["exists"] = filename in existing_files
                                except:
                                    resource["exists"] = False
                            
                            elif model_type in custom_folder_types:
                                models_dir = os.path.dirname(folder_paths.get_folder_paths('checkpoints')[0])
                                target_dir_name = model_type.capitalize()
                                target_path = os.path.join(models_dir, target_dir_name, filename)
                                resource["exists"] = os.path.exists(target_path)

                            elif model_type == "motionmodule":
                                motion_module_path = os.path.join(folder_paths.get_folder_paths("custom_nodes")[0], "ComfyUI-AnimateDiff-Evolved", "models")
                                resource["exists"] = os.path.exists(os.path.join(motion_module_path, filename))
                                
                            else:
                                resource["exists"] = False
                        else:
                            resource["fileName"] = None
                            resource["exists"] = False
                    else:
                        resource["exists"] = False
                    return resource
            except Exception:
                resource["exists"] = False
                return resource

        async with aiohttp.ClientSession() as session:
            tasks = [fetch_info(session, res) for res in resources]
            augmented_resources = await asyncio.gather(*tasks)
            return web.json_response(augmented_resources)

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@prompt_server.routes.get("/civitai_gallery/api_key_status")
async def get_api_key_status(request):
    config = load_config()
    return web.json_response({"has_key": bool(config.get("civitai_api_key"))})

@prompt_server.routes.post("/civitai_gallery/save_api_key")
async def save_api_key(request):
    try:
        data = await request.json()
        api_key = data.get("api_key")
        if not api_key:
            return web.json_response({"status": "error", "message": "No API key provided"}, status=400)
        config = load_config()
        config["civitai_api_key"] = api_key
        save_config(config)
        return web.json_response({"status": "success"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.post("/civitai_gallery/update_favorite_tags")
async def update_favorite_tags(request):
    try:
        data = await request.json()
        item_id = str(data.get("id"))
        tags = data.get("tags", [])
        if not item_id:
            return web.json_response({"status": "error", "message": "Missing item id"}, status=400)
            
        favorites = load_favorites()
        if item_id in favorites:
            favorites[item_id]['tags'] = tags
            save_favorites(favorites)
            return web.json_response({"status": "success"})
        else:
            return web.json_response({"status": "error", "message": "Item not in favorites"}, status=404)
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.get("/civitai_gallery/get_all_favorite_tags")
async def get_all_favorite_tags(request):
    try:
        favorites = load_favorites()
        all_tags = set()
        for item in favorites.values():
            tags = item.get("tags")
            if isinstance(tags, list):
                for tag in tags:
                    all_tags.add(tag)
        
        sorted_tags = sorted(list(all_tags), key=lambda s: s.lower())
        return web.json_response({"tags": sorted_tags})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.get("/civitai_gallery/download_progress")
async def get_download_progress(request):
    task_id = request.query.get('task_id')
    if not task_id or task_id not in download_tasks:
        return web.json_response({"status": "not_found"}, status=404)
    
    task = download_tasks[task_id]

    if task["status"] in ["completed", "error", "cancelled"]:
        async def cleanup():
            await asyncio.sleep(5)
            if task_id in download_tasks:
                del download_tasks[task_id]
        asyncio.create_task(cleanup())
        
    return web.json_response(task)

@prompt_server.routes.post("/civitai_gallery/cancel_download")
async def cancel_download(request):
    try:
        data = await request.json()
        task_id = data.get("task_id")
        if task_id and task_id in download_tasks:
            download_tasks[task_id]["cancel_requested"] = True
            download_tasks[task_id]["status"] = "cancelling"
            print(f"CivitaiGallery: Cancellation requested for task {task_id}")
            return web.json_response({"status": "cancellation_requested"})
        return web.json_response({"status": "task_not_found"}, status=404)
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.post("/civitai_gallery/check_video_workflow")
async def check_video_workflow(request):
    data = await request.json()
    video_url = data.get("url")
    if not video_url:
        return web.json_response({"has_workflow": False, "error": "URL is missing"}, status=400)

    try:
        headers = {'Range': 'bytes=0-4194304'} 
        async with aiohttp.ClientSession() as session:
            async with session.get(video_url, headers=headers) as response:
                if response.status >= 400 and response.status != 416:
                     return web.json_response({"has_workflow": False, "error": f"Failed to fetch video chunk, status: {response.status}"})
                
                chunk = await response.content.read()
                has_workflow = b'"workflow":' in chunk or b'"prompt":' in chunk
                
                return web.json_response({"has_workflow": has_workflow})
    except Exception as e:
        return web.json_response({"has_workflow": False, "error": str(e)}, status=500)

@prompt_server.routes.get("/civitai_gallery/get_video_for_workflow")
async def get_video_for_workflow(request):
    video_url = request.query.get('url')
    if not video_url:
        return web.Response(status=400, text="Missing video URL")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(video_url) as response:
                if response.status != 200:
                    return web.Response(status=response.status, text=f"Failed to fetch video from source: {response.reason}")
                
                data = await response.read()
                filename = video_url.split('/')[-1].split('?')[0] or "video_with_workflow.mp4"

                return web.Response(
                    body=data,
                    content_type=response.content_type,
                    headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
                )
    except Exception as e:
        return web.Response(status=500, text=str(e))

NODE_CLASS_MAPPINGS = { "CivitaiGalleryNode": CivitaiGalleryNode }
NODE_DISPLAY_NAME_MAPPINGS = { "CivitaiGalleryNode": "Civitai Images Gallery" }
