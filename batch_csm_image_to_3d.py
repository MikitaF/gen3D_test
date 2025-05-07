# Instructions: Create a .env file in the same directory as this script with the following content:
# API_KEY=your_csm_api_key
# GITHUB_USER=your_github_username

from dotenv import load_dotenv
import os
import requests
import time
import shutil

load_dotenv()

API_KEY = os.getenv("API_KEY")
GITHUB_USER = os.getenv("GITHUB_USER")
GITHUB_REPO = "gen3D_test"
GITHUB_BRANCH = "main"
CONCEPTS_DIR = "content/gen3D/concepts"
PROCESSED_DIR = "content/gen3D/processed"
RESULT_DIR = "content/gen3D/result"
API_BASE = "https://api.csm.ai/image-to-3d-sessions"


def get_image_files():
    return [f for f in os.listdir(CONCEPTS_DIR) if f.lower().endswith((".png", ".jpg"))]


def get_github_raw_url(filename):
    return f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{CONCEPTS_DIR}/{filename}"


def start_session(image_url):
    payload = {
        "image_url": image_url,
        "geometry_model": "turbo"
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


def main():
    os.makedirs(RESULT_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    images = get_image_files()
    summary = []
    print(f"Found {len(images)} images to process.")
    for img in images:
        print(f"Processing: {img}")
        image_url = get_github_raw_url(img)
        session_code, err = start_session(image_url)
        if err:
            print(f"  Error: {err}")
            summary.append((img, None, "error", err))
            continue
        print(f"  Session code: {session_code}")
        print(f"  Waiting for model to be ready...")
        session_data, err = poll_session(session_code)
        if err:
            print(f"  Error: {err}")
            summary.append((img, None, "error", err))
            continue
        mesh_url = session_data.get("mesh_url_glb")
        credits = session_data.get("credits", "?")
        if not mesh_url:
            print("  No GLB mesh URL found.")
            summary.append((img, None, "no_mesh", credits))
            continue
        out_path = os.path.join(RESULT_DIR, f"{session_code}.glb")
        err = download_file(mesh_url, out_path)
        if err:
            print(f"  Error: {err}")
            summary.append((img, None, "download_error", credits))
            continue
        move_file(os.path.join(CONCEPTS_DIR, img), os.path.join(PROCESSED_DIR, img))
        summary.append((img, out_path, "success", credits))
    print("\nSummary:")
    print(f"{'Image':30} {'Model':40} {'Status':10} {'Credits'}")
    for row in summary:
        print(f"{row[0]:30} {str(row[1]):40} {row[2]:10} {row[3]}")

if __name__ == "__main__":
    main() 