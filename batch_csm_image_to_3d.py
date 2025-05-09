# Instructions: Create a .env file in the same directory as this script with the following content:
# API_KEY=your_csm_api_key
# GITHUB_USER=your_github_username

from dotenv import load_dotenv
import os
import requests
import time
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

API_KEY = os.getenv("API_KEY")
GITHUB_USER = os.getenv("GITHUB_USER")
GITHUB_REPO = "gen3D_test"
GITHUB_BRANCH = "main"
CONCEPTS_DIR = "content/concepts"
PROCESSED_DIR = "content/processed"
RESULT_DIR = "content/result"
API_BASE = "https://api.csm.ai/image-to-3d-sessions"


def get_image_files():
    return [f for f in os.listdir(CONCEPTS_DIR) if f.lower().endswith((".png", ".jpg"))]


def get_github_raw_url(filename):
    return f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{CONCEPTS_DIR}/{filename}"


def prompt_user_settings():
    print("\n--- 3D Generation Settings ---")
    geometry = input("Choose geometry model ([T]urbo/[B]ase, default: Turbo): ").strip().lower()
    if geometry == 'b':
        geometry_model = 'base'
    else:
        geometry_model = 'turbo'

    texture = input("Texture? [N]one/[B]aked/[P]BR (default: None): ").strip().lower()
    if texture == 'b':
        texture_model = 'baked'
    elif texture == 'p':
        texture_model = 'pbr'
    else:
        texture_model = 'none'

    print("Polygon amount? [H]igh (100000) / [M]id (20000) / [L]ow (5000) / [C]ustom (default: High): ", end="")
    resolution = input().strip().lower()
    if resolution == 'l':
        resolution_val = 5000
    elif resolution == 'm':
        resolution_val = 20000
    elif resolution == 'c':
        custom_val = input("Enter custom polygon count (number): ").strip()
        if custom_val.isdigit():
            resolution_val = int(custom_val)
        else:
            print("Invalid number, using 100000 (High).")
            resolution_val = 100000
    else:
        resolution_val = 100000

    print(f"\nSettings: geometry={geometry_model}, texture={texture_model}, resolution={resolution_val}\n")
    return geometry_model, texture_model, resolution_val


def start_session(image_url, geometry_model, texture_model, resolution):
    payload = {
        "image_url": image_url,
        "geometry_model": geometry_model,
        "texture_model": texture_model,
        "resolution": resolution
    }
    headers = {
        'x-api-key': API_KEY,
        'Content-Type': 'application/json'
    }
    resp = requests.post(API_BASE, json=payload, headers=headers)
    if resp.status_code not in (200, 201):
        return None, f"Failed to start session: {resp.text}"
    data = resp.json()
    if not data.get("data") or not data["data"].get("session_code"):
        return None, f"Unexpected response: {data}"
    return data["data"]["session_code"], None


def poll_session(session_code, poll_interval=10, timeout=600):
    url = f"{API_BASE}/{session_code}"
    headers = {
        'x-api-key': API_KEY,
        'Content-Type': 'application/json'
    }
    waited = 0
    last_status = None
    while waited < timeout:
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            return None, f"Failed to get session status: {resp.text}"
        data = resp.json()
        status = data.get("data", {}).get("session_status")
        percent = data.get("data", {}).get("percent_done", 0)
        if status != last_status:
            print(f"  Status: {status}, {percent}% done")
            last_status = status
        if status == "complete":
            return data["data"], None
        if status == "failed":
            return None, "Session failed."
        time.sleep(poll_interval)
        waited += poll_interval
    return None, "Timeout waiting for session to complete."


def download_file(url, out_path):
    resp = requests.get(url, stream=True)
    if resp.status_code != 200:
        return f"Failed to download file: {resp.text}"
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    return None


def move_file(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)


def process_image(img, geometry_model, texture_model, resolution):
    image_url = get_github_raw_url(img)
    session_code, err = start_session(image_url, geometry_model, texture_model, resolution)
    if err:
        print(f"Processing: {img}\n  Error: {err}")
        return (img, None, "error")
    print(f"Processing: {img}\n  Session code: {session_code}\n  Waiting for model to be ready...")
    session_data, err = poll_session(session_code)
    if err:
        print(f"Processing: {img}\n  Error: {err}")
        return (img, None, "error")
    mesh_url = session_data.get("mesh_url_glb")
    if not mesh_url:
        print(f"Processing: {img}\n  No GLB mesh URL found.")
        return (img, None, "no_mesh")
    base_name = os.path.splitext(img)[0]
    out_path = os.path.join(RESULT_DIR, f"{base_name}.glb")
    err = download_file(mesh_url, out_path)
    if err:
        print(f"Processing: {img}\n  Error: {err}")
        return (img, None, "download_error")
    move_file(os.path.join(CONCEPTS_DIR, img), os.path.join(PROCESSED_DIR, img))
    return (img, out_path, "success")


def main():
    os.makedirs(RESULT_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    geometry_model, texture_model, resolution = prompt_user_settings()
    images = get_image_files()
    summary = []
    print(f"Found {len(images)} images to process.")
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(process_image, img, geometry_model, texture_model, resolution): img for img in images}
        for future in as_completed(futures):
            result = future.result()
            summary.append(result)
    print("\nSummary:")
    print(f"{'Image':30} {'Model':40} {'Status':10}")
    for row in summary:
        print(f"{row[0]:30} {str(row[1]):40} {row[2]:10}")

if __name__ == "__main__":
    main() 