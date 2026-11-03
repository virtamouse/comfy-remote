"""Comfy Remote: a phone- and PC-friendly page (served at /remote and /mobile) that runs saved workflow
sections on this ComfyUI.

The desktop extension (web/comfy_remote.js) captures sections of the open workflow as API prompts and
POSTs them to /mobile/templates. The page fills in its settings and queues them through /prompt.
Until sections are sent from the PC, the ready-made templates.default.json (from the bundled workflow) is used.
"""

import io
import json
import os
import shutil
from collections import OrderedDict

from aiohttp import web
from PIL import Image, ImageOps

import folder_paths
from server import PromptServer

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "templates.json")
DEFAULT_TEMPLATES = os.path.join(HERE, "templates.default.json")
PAGE = os.path.join(HERE, "mobile", "index.html")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
NO_CACHE = {"Cache-Control": "no-store"}

routes = PromptServer.instance.routes


def _base_dir(kind):
    if kind == "input":
        return folder_paths.get_input_directory()
    if kind == "output":
        return folder_paths.get_output_directory()
    raise web.HTTPBadRequest(text="type must be input or output")


def _safe_path(kind, subfolder, filename):
    base = os.path.abspath(_base_dir(kind))
    path = os.path.abspath(os.path.join(base, subfolder or "", filename))
    if os.path.commonpath([base, path]) != base or not os.path.isfile(path):
        raise web.HTTPNotFound()
    return path


@routes.get("/remote")
@routes.get("/remote/")
@routes.get("/mobile")
@routes.get("/mobile/")
async def mobile_page(request):
    return web.FileResponse(PAGE, headers=NO_CACHE)


@routes.get("/mobile/templates")
async def get_templates(request):
    path = TEMPLATES if os.path.isfile(TEMPLATES) else DEFAULT_TEMPLATES
    if not os.path.isfile(path):
        return web.json_response({}, headers=NO_CACHE)
    with open(path, encoding="utf-8") as f:
        return web.json_response(json.load(f), headers=NO_CACHE)


@routes.post("/mobile/templates")
async def save_templates(request):
    data = await request.json()
    if not isinstance(data, dict) or not all(isinstance(v, dict) and "prompt" in v for v in data.values()):
        raise web.HTTPBadRequest(text="expected {section: {prompt, workflow, ...}}")
    tmp = TEMPLATES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, TEMPLATES)
    return web.json_response({"saved": list(data.keys())})


@routes.get("/mobile/images")
async def list_images(request):
    kind = request.query.get("type", "input")
    limit = min(int(request.query.get("limit", 120)), 500)
    offset = int(request.query.get("offset", 0))
    base = _base_dir(kind)
    found = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in ("clipspace", "3d") and not d.startswith(".")]
        for name in files:
            if name.lower().endswith(IMAGE_EXT):
                full = os.path.join(root, name)
                try:
                    found.append((os.path.getmtime(full), full))
                except OSError:
                    pass
    found.sort(reverse=True)
    items = []
    for mtime, full in found[offset:offset + limit]:
        sub = os.path.relpath(os.path.dirname(full), base)
        items.append({"filename": os.path.basename(full), "subfolder": "" if sub == "." else sub.replace("\\", "/"),
                      "type": kind, "mtime": mtime})
    return web.json_response({"items": items, "total": len(found)}, headers=NO_CACHE)


_thumbs = OrderedDict()


@routes.get("/mobile/thumb")
async def thumb(request):
    q = request.query
    path = _safe_path(q.get("type", "input"), q.get("subfolder", ""), q.get("filename", ""))
    size = max(64, min(int(q.get("size", 320)), 1024))
    return web.Response(body=_thumb_bytes(path, size), content_type="image/webp", headers={"Cache-Control": "max-age=3600"})


# ---------- browsing the PC's own folders ----------
# folders.json (created on first use) controls what the phone may browse:
#   {"folders": ["C:\\Users\\me\\Pictures", ...], "drives": false}
# "drives": true also lets the page browse every drive. Only folder names and image files are ever exposed.
FOLDERS = os.path.join(HERE, "folders.json")


def _roots():
    if not os.path.isfile(FOLDERS):
        home = os.path.expanduser("~")
        cfg = {"folders": [p for p in (os.path.join(home, d) for d in ("Pictures", "Desktop", "Downloads")) if os.path.isdir(p)],
               "drives": False}
        with open(FOLDERS, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    with open(FOLDERS, encoding="utf-8") as f:
        cfg = json.load(f)
    roots = [os.path.abspath(p) for p in cfg.get("folders", []) if os.path.isdir(p)]
    if cfg.get("drives") and os.name == "nt":
        roots += [f"{c}:\\" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.isdir(f"{c}:\\")]
    return roots


def _allowed(path):
    path = os.path.realpath(path)
    for root in _roots():
        root = os.path.realpath(root)
        try:
            if os.path.commonpath([root, path]) == root:
                return path
        except ValueError:  # different drives
            continue
    raise web.HTTPForbidden(text="folder not allowed")


@routes.get("/mobile/fs/roots")
async def fs_roots(request):
    return web.json_response([{"name": os.path.basename(r.rstrip("\\/")) or r, "path": r} for r in _roots()], headers=NO_CACHE)


@routes.get("/mobile/fs/list")
async def fs_list(request):
    path = _allowed(request.query.get("path", ""))
    if not os.path.isdir(path):
        raise web.HTTPNotFound()
    limit = min(int(request.query.get("limit", 120)), 500)
    offset = int(request.query.get("offset", 0))
    dirs, images = [], []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.name.startswith((".", "$")):
                        continue
                    if e.is_dir():
                        dirs.append(e.name)
                    elif e.name.lower().endswith(IMAGE_EXT):
                        images.append((e.stat().st_mtime, e.name))
                except OSError:
                    pass
    except PermissionError:
        raise web.HTTPForbidden(text="no access to this folder")
    dirs.sort(key=str.lower)
    images.sort(reverse=True)
    parent = os.path.dirname(path)  # a drive root is its own parent
    try:
        parent = _allowed(parent) if parent and parent != path else None
    except web.HTTPForbidden:
        parent = None
    return web.json_response({"path": path, "parent": parent, "dirs": dirs if offset == 0 else [],
                              "images": [n for _, n in images[offset:offset + limit]], "total": len(images)}, headers=NO_CACHE)


def _image_path(request):
    path = _allowed(request.query.get("path", ""))
    if not path.lower().endswith(IMAGE_EXT) or not os.path.isfile(path):
        raise web.HTTPNotFound()
    return path


def _thumb_bytes(path, size):
    key = (path, os.path.getmtime(path), size)
    data = _thumbs.get(key)
    if data is None:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.save(buf, "WEBP", quality=80)
            data = buf.getvalue()
        _thumbs[key] = data
        while len(_thumbs) > 400:
            _thumbs.popitem(last=False)
    return data


@routes.get("/mobile/fs/thumb")
async def fs_thumb(request):
    path = _image_path(request)
    size = max(64, min(int(request.query.get("size", 320)), 1024))
    return web.Response(body=_thumb_bytes(path, size), content_type="image/webp", headers={"Cache-Control": "max-age=3600"})


@routes.post("/mobile/fs/use")
async def fs_use(request):
    """Copy a PC image into input/mobile so LoadImage can read it."""
    body = await request.json()
    src = _allowed(body.get("path", ""))
    if not src.lower().endswith(IMAGE_EXT) or not os.path.isfile(src):
        raise web.HTTPNotFound()
    dest_dir = os.path.join(folder_paths.get_input_directory(), "mobile")
    os.makedirs(dest_dir, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(src))
    name, i = base + ext, 1
    while os.path.exists(os.path.join(dest_dir, name)):
        if os.path.getsize(os.path.join(dest_dir, name)) == os.path.getsize(src):
            break  # same file picked before
        name, i = f"{base}_{i}{ext}", i + 1
    if not os.path.exists(os.path.join(dest_dir, name)):
        shutil.copy2(src, os.path.join(dest_dir, name))
    return web.json_response({"filename": name, "subfolder": "mobile", "type": "input"})


from .size_preset_picker import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS  # noqa: E402

WEB_DIRECTORY = "./web"
