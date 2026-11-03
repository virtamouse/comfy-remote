"""Comfy Remote installer for ComfyUI Windows portable.

Run by Install-ComfyRemote.bat with ComfyUI portable's own Python. It:
  1. checks ComfyUI is new enough for MOSS Image,
  2. installs the node packs the workflow needs (and their Python requirements, without touching torch),
  3. copies the Comfy Remote workflow and its example image into ComfyUI,
  4. checks for the models (including folders from extra_model_paths.yaml) and offers to download missing ones,
  5. copies launchers that open ComfyUI to your phone (Wi-Fi or Tailscale).

Options: --yes (no questions)  --skip-nodes  --skip-models  --update (update node packs)  --dry-run
"""

import argparse
import filecmp
import glob
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
HF = "https://huggingface.co/Aitrepreneur/FLX/resolve/main/"

# (models folder, file name, size in bytes) - all downloaded from HF + file name
MODELS = [
    ("diffusion_models", "moss_image_base_int8_convrot.safetensors", 5413698958),
    ("text_encoders", "Qwen3.5-9B-abliterated_int8_convrot.safetensors", 9471076556),
    ("vae", "flux2-vae_small.safetensors", 249521340),
    ("loras", "8-steps-dmd2-lora.safetensors", 1189176800),
    ("loras", "moss_image_sft.safetensors", 285329336),
    ("loras", "moss-control.safetensors", 313063368),
]
# Depth Anything V2 (depth_anything_v2_vits.pth) is downloaded by comfyui_controlnet_aux on its first run.

# (folder name, git URL, branch)
NODE_PACKS = [
    ("rgthree-comfy", "https://github.com/rgthree/rgthree-comfy", "main"),
    ("ComfyUI-KJNodes", "https://github.com/kijai/ComfyUI-KJNodes", "main"),
    ("comfyui_controlnet_aux", "https://github.com/Fannovel16/comfyui_controlnet_aux", "main"),
]
# Earlier, unpackaged versions of this project. They register the same routes/nodes, so they are switched off.
OLD_PACKS = ["ComfyUI-MobileRemote", "ComfyUI-SizePresetPicker"]
# Other names a models folder may go by (ComfyUI treats them as the same folder).
ALIASES = {"text_encoders": ["text_encoders", "clip"], "diffusion_models": ["diffusion_models", "unet"]}
WORKFLOWS = os.path.join(HERE, "example_workflows")
EXAMPLE_IMAGE = os.path.join(HERE, "assets", "comfy_remote_example.png")

args = None


def say(text=""):
    print(text, flush=True)


def head(text):
    say()
    say(f"---- {text} " + "-" * max(0, 60 - len(text)))


def ask(question, default=True):
    if args.yes:
        return default
    hint = "Y/n" if default else "y/N"
    while True:
        try:
            a = input(f"{question} [{hint}] ").strip().lower()
        except EOFError:  # no keyboard (run from a script)
            say()
            return default
        if not a:
            return default
        if a in ("y", "yes"):
            return True
        if a in ("n", "no"):
            return False


def gb(n):
    return f"{n / 1024 ** 3:.1f} GB" if n >= 1024 ** 3 else f"{n / 1024 ** 2:.0f} MB"


def run(cmd, **kw):
    say("  > " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    if args.dry_run:
        return 0
    return subprocess.call(cmd, **kw)


# ---------- ComfyUI ----------

def find_root():
    if args.root:
        return os.path.abspath(args.root)
    # Normally this file lives in ComfyUI_windows_portable/ComfyUI/custom_nodes/comfy-remote
    return os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def check_comfy(comfy):
    head("ComfyUI")
    if not os.path.isfile(os.path.join(comfy, "main.py")):
        say(f"[ERROR] ComfyUI not found at {comfy}")
        return False
    version = "unknown"
    vf = os.path.join(comfy, "comfyui_version.py")
    if os.path.isfile(vf):
        for line in open(vf, encoding="utf-8"):
            if line.startswith("__version__"):
                version = line.split("=")[1].strip().strip("\"'")
    say(f"  ComfyUI {version} at {comfy}")
    if not os.path.isfile(os.path.join(comfy, "comfy_extras", "nodes_moss_image.py")):
        say("[ERROR] This ComfyUI is too old for MOSS Image.")
        say("        Update it first: run update\\update_comfyui.bat in the ComfyUI_windows_portable folder.")
        return False
    return True


# ---------- node packs ----------

def installed_name(nodes_dir, name):
    """Folder a pack is installed under (any letter case; ComfyUI-Manager often uses lower case), or None."""
    want = name.lower()
    for entry in os.listdir(nodes_dir):
        low = entry.lower()
        if low == want or low == want + ".disabled":
            return entry
    return None


def have_git():
    try:
        return subprocess.call(["git", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    except OSError:
        return False


def download_zip(url, branch, dest):
    zip_url = f"{url}/archive/refs/heads/{branch}.zip"
    say(f"  downloading {zip_url}")
    if args.dry_run:
        return True
    tmp = tempfile.mkdtemp(prefix="comfyremote_")
    try:
        zpath = os.path.join(tmp, "pack.zip")
        urllib.request.urlretrieve(zip_url, zpath)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
        top = [d for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))][0]
        shutil.move(os.path.join(tmp, top), dest)
        return True
    except Exception as e:  # noqa: BLE001 - report and carry on with the other packs
        say(f"  [!] download failed: {e}")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def torch_constraints():
    """Pin the installed torch family so node requirements can't replace the CUDA build."""
    out = subprocess.run([sys.executable, "-s", "-m", "pip", "freeze"], capture_output=True, text=True).stdout
    keep = [l for l in out.splitlines() if l.split("==")[0].lower() in ("torch", "torchvision", "torchaudio", "xformers")]
    fd, path = tempfile.mkstemp(prefix="comfyremote_constraints_", suffix=".txt")
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(keep) + "\n")
    return path


def install_requirements(pack_dir, constraints):
    req = os.path.join(pack_dir, "requirements.txt")
    if not os.path.isfile(req):
        return
    code = run([sys.executable, "-s", "-m", "pip", "install", "--disable-pip-version-check", "-r", req, "-c", constraints])
    if code:
        say("  [!] pip reported a problem (often harmless if ComfyUI still starts). Check the messages above.")


def install_nodes(comfy):
    head("Node packs")
    nodes_dir = os.path.join(comfy, "custom_nodes")
    git = have_git()
    if not git:
        say("  Git not found - packs are downloaded as zip files (they won't update with git pull).")
    constraints = torch_constraints() if not args.dry_run else ""
    for name, url, branch in NODE_PACKS:
        found = installed_name(nodes_dir, name)
        if found and found.lower().endswith(".disabled"):
            say(f"  [!] {found} is disabled. Enable it in ComfyUI-Manager (or remove .disabled from the folder name).")
            continue
        if found:
            path = os.path.join(nodes_dir, found)
            if args.update and os.path.isdir(os.path.join(path, ".git")) and git:
                say(f"  updating {found}")
                run(["git", "-C", path, "pull", "--ff-only"])
            else:
                say(f"  {found}: already installed")
                continue  # its requirements were installed when it was
        else:
            path = os.path.join(nodes_dir, name)
            say(f"  installing {name}")
            ok = run(["git", "clone", "--depth", "1", url, path]) == 0 if git else download_zip(url, branch, path)
            if not ok:
                say(f"  [!] could not install {name}")
                continue
        install_requirements(path, constraints)

    # Switch off the earlier unpackaged copies; keep their saved phone setup.
    for old in OLD_PACKS:
        path = os.path.join(nodes_dir, old)
        if not os.path.isdir(path) or os.path.abspath(path) == HERE:
            continue
        for keep in ("templates.json", "folders.json"):
            src = os.path.join(path, keep)
            if os.path.isfile(src) and not os.path.isfile(os.path.join(HERE, keep)):
                say(f"  keeping your {keep} from {old}")
                if not args.dry_run:
                    shutil.copy2(src, HERE)
        dest = path + ".disabled"
        i = 1
        while os.path.exists(dest):
            dest, i = f"{path}.disabled{i}", i + 1
        say(f"  switching off old {old} (now part of Comfy Remote) -> {os.path.basename(dest)}")
        if not args.dry_run:
            os.rename(path, dest)


# ---------- workflow + example image ----------

def install_files(comfy):
    head("Workflow")
    wf_dir = os.path.join(comfy, "user", "default", "workflows")
    for src in glob.glob(os.path.join(WORKFLOWS, "*.json")):
        dest = os.path.join(wf_dir, os.path.basename(src))
        if os.path.isfile(dest) and filecmp.cmp(src, dest, shallow=False):
            say(f"  {os.path.basename(dest)}: up to date")
            continue
        if os.path.isfile(dest):
            say(f"  backing up your copy to {os.path.basename(dest)[:-5]}.bak.json")
            if not args.dry_run:
                shutil.copy2(dest, dest[:-5] + ".bak.json")
        say(f"  copying {os.path.basename(src)} -> {wf_dir}")
        if not args.dry_run:
            os.makedirs(wf_dir, exist_ok=True)
            shutil.copy2(src, dest)
    dest = os.path.join(comfy, "input", os.path.basename(EXAMPLE_IMAGE))
    if not os.path.isfile(dest):
        say(f"  copying example image -> {dest}")
        if not args.dry_run:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(EXAMPLE_IMAGE, dest)


# ---------- models ----------

def model_dirs(comfy):
    """Every folder ComfyUI searches per model type, plus where new downloads should go."""
    dirs = {folder: [os.path.join(comfy, "models", a) for a in ALIASES.get(folder, [folder])] for folder, _, _ in MODELS}
    default = {folder: os.path.join(comfy, "models", folder) for folder in dirs}
    cfg_path = os.path.join(comfy, "extra_model_paths.yaml")
    if not os.path.isfile(cfg_path):
        return dirs, default
    try:
        import yaml
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:  # noqa: BLE001
        say(f"  [!] could not read extra_model_paths.yaml ({e}); only checking ComfyUI/models")
        return dirs, default
    for section in cfg.values():
        if not isinstance(section, dict):
            continue
        base = os.path.expandvars(os.path.expanduser(str(section.get("base_path", ""))))
        if base and not os.path.isabs(base):
            base = os.path.join(os.path.dirname(cfg_path), base)
        for folder in dirs:
            for key in ALIASES.get(folder, [folder]):
                for p in str(section.get(key) or "").splitlines():
                    p = p.strip()
                    if not p:
                        continue
                    full = os.path.normpath(os.path.join(base, p))
                    dirs[folder].append(full)
                    if section.get("is_default") and default[folder].startswith(os.path.join(comfy, "models")):
                        default[folder] = full
    return dirs, default


def find_model(dirs, name, size):
    """Path of the model if present with the right size; (path, False) if present but incomplete."""
    for d in dirs:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p, os.path.getsize(p) == size
    return None, False


def download(url, dest, size):
    part = dest + ".part"
    done = os.path.getsize(part) if os.path.isfile(part) else 0
    if done >= size:
        os.replace(part, dest)
        return True
    req = urllib.request.Request(url, headers={"User-Agent": "comfy-remote-installer"})
    if done:
        req.add_header("Range", f"bytes={done}-")
        say(f"  resuming at {gb(done)}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    start, last = time.time(), 0
    with urllib.request.urlopen(req, timeout=60) as r:
        if done and r.status != 206:  # server ignored the range: start over
            done = 0
        first = done
        with open(part, "ab" if done else "wb") as f:
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last > 0.5:
                    speed = (done - first) / max(now - start, 0.001)
                    sys.stdout.write(f"\r  {gb(done)} / {gb(size)}  ({done * 100 // size}%)  {speed / 1024 ** 2:.1f} MB/s   ")
                    sys.stdout.flush()
                    last = now
    say()
    if os.path.getsize(part) != size:
        say(f"  [!] size mismatch ({os.path.getsize(part)} bytes, expected {size}). Run the installer again to resume.")
        return False
    os.replace(part, dest)
    return True


def check_models(comfy):
    head("Models")
    dirs, default = model_dirs(comfy)
    missing = []
    for folder, name, size in MODELS:
        path, ok = find_model(dirs[folder], name, size)
        if path and ok:
            say(f"  OK       {name}")
        elif path:
            say(f"  BROKEN   {name}  (wrong size, probably an unfinished download: {path})")
            missing.append((folder, name, size, path))
        else:
            say(f"  MISSING  {name}  ({gb(size)})")
            missing.append((folder, name, size, os.path.join(default[folder], name)))
    if not missing:
        say("  All models are present.")
        return True
    total = sum(m[2] for m in missing)
    say()
    say(f"  {len(missing)} model(s) to download, {gb(total)} in total:")
    for folder, name, size, dest in missing:
        say(f"    {name}  ->  {os.path.dirname(dest)}")
    if args.skip_models or not ask("Download them now?", True):
        say("  Skipped. Run this installer again any time to download them.")
        return False
    ok_all = True
    for folder, name, size, dest in missing:
        say(f"  downloading {name}")
        if args.dry_run:
            continue
        if os.path.isfile(dest) and os.path.getsize(dest) != size:
            os.replace(dest, dest + ".part")  # resume a broken file instead of starting over
        try:
            ok_all &= download(HF + name + "?download=true", dest, size)
        except Exception as e:  # noqa: BLE001
            say(f"\n  [!] {name} failed: {e}. Run the installer again to resume.")
            ok_all = False
    return ok_all


# ---------- launchers + summary ----------

def install_launchers(root):
    head("Launchers")
    for src in glob.glob(os.path.join(HERE, "launchers", "*.bat")):
        dest = os.path.join(root, os.path.basename(src))
        if os.path.isfile(dest) and filecmp.cmp(src, dest, shallow=False):
            say(f"  {os.path.basename(dest)}: up to date")
            continue
        say(f"  {os.path.basename(src)} -> {root}")
        if not args.dry_run:
            shutil.copy2(src, dest)


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # no traffic is sent; this just picks the network card
        return s.getsockname()[0]
    except OSError:
        return None


def main():
    global args
    ap = argparse.ArgumentParser(description="Install Comfy Remote into ComfyUI Windows portable.")
    ap.add_argument("--root", help="ComfyUI_windows_portable folder (found automatically)")
    ap.add_argument("--yes", action="store_true", help="answer yes to every question")
    ap.add_argument("--skip-nodes", action="store_true")
    ap.add_argument("--skip-models", action="store_true")
    ap.add_argument("--update", action="store_true", help="also update node packs that are already installed")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen without changing anything")
    args = ap.parse_args()

    root = find_root()
    comfy = os.path.join(root, "ComfyUI")
    say("Comfy Remote installer" + ("  (dry run - nothing will be changed)" if args.dry_run else ""))
    if not check_comfy(comfy):
        return 1
    if not args.skip_nodes:
        install_nodes(comfy)
    install_files(comfy)
    models_ok = check_models(comfy)
    install_launchers(root)

    head("Done")
    say("  Start ComfyUI with one of:")
    say("    run_comfy_remote_LAN.bat        phone on the same Wi-Fi")
    say("    run_comfy_remote_TAILSCALE.bat  phone anywhere, through Tailscale")
    say("    run_nvidia_gpu.bat              this PC only")
    say()
    say("  Then open Comfy Remote:")
    say("    on this PC:   http://127.0.0.1:8188/remote")
    ip = lan_ip()
    if ip:
        say(f"    on a phone:   http://{ip}:8188/remote   (needs run_comfy_remote_LAN.bat)")
    say()
    say("  The workflow is in ComfyUI's Workflows list as \"Comfy Remote - MOSS Turbo\".")
    if not models_ok:
        say("  [!] Some models are still missing - run this installer again to finish downloading them.")
    if not args.skip_nodes and not args.dry_run:
        say("  If ComfyUI is already running, restart it so the new nodes load.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
