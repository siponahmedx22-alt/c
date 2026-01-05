import os
import re
import requests
import random
import string
import time
from pathlib import Path
from datetime import datetime

# Configuration
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
REPO_NAME = os.environ.get('REPO_NAME')  # format: username/repo
DRIVE_FILE = 'drive.txt'

def generate_random_suffix(length=6):
    """Generate random suffix for uniqueness"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def extract_drive_file_id(url):
    """Extract file ID from Google Drive URL"""
    patterns = [
        r'/file/d/([a-zA-Z0-9_-]+)',
        r'id=([a-zA-Z0-9_-]+)',
        r'/d/([a-zA-Z0-9_-]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_drive_file_info(file_id):
    """Get file information from Google Drive"""
    try:
        # Try to get file metadata
        api_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=name,size"
        response = requests.get(api_url)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('name', f'video_{file_id[:8]}.mp4')
        else:
            return f'video_{file_id[:8]}.mp4'
    except:
        return f'video_{file_id[:8]}.mp4'

def download_large_file_from_drive(file_id, output_path):
    """Download large files from Google Drive (supports 100MB+)"""
    print(f"Downloading file ID: {file_id}")
    
    # Use direct download with session to handle large files
    url = "https://drive.google.com/uc?export=download"
    
    session = requests.Session()
    
    try:
        # First request
        response = session.get(url, params={'id': file_id}, stream=True)
        
        # Handle virus scan warning for large files
        token = None
        for key, value in response.cookies.items():
            if key.startswith('download_warning'):
                token = value
                break
        
        if token:
            params = {'id': file_id, 'confirm': token}
            response = session.get(url, params=params, stream=True)
        
        # Check for Google Drive confirmation page
        if 'text/html' in response.headers.get('Content-Type', ''):
            # Extract confirmation token from HTML
            for line in response.iter_lines():
                if b'download' in line and b'confirm' in line:
                    match = re.search(b'confirm=([^&"]+)', line)
                    if match:
                        confirm_token = match.group(1).decode()
                        params = {'id': file_id, 'confirm': confirm_token}
                        response = session.get(url, params=params, stream=True)
                        break
        
        # Download file
        total_size = int(response.headers.get('content-length', 0))
        
        print(f"File size: {total_size / (1024*1024):.2f} MB")
        
        with open(output_path, 'wb') as f:
            downloaded = 0
            chunk_size = 32768  # 32KB chunks for better speed
            
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        print(f"\rDownload progress: {progress:.1f}% ({downloaded/(1024*1024):.1f}/{total_size/(1024*1024):.1f} MB)", end='')
        
        print(f"\n✓ Download completed: {output_path}")
        return True
        
    except Exception as e:
        print(f"✗ Error downloading: {e}")
        return False

def get_all_releases(repo_name, token):
    """Get all existing releases"""
    url = f"https://api.github.com/repos/{repo_name}/releases"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        return []
    except:
        return []

def create_unique_release(repo_name, base_name, token):
    """Create release with unique name"""
    existing_releases = get_all_releases(repo_name, token)
    existing_tags = [r['tag_name'] for r in existing_releases]
    
    # Generate unique tag
    tag_name = base_name
    counter = 1
    
    while tag_name in existing_tags:
        suffix = generate_random_suffix()
        tag_name = f"{base_name}-{suffix}"
        counter += 1
        
        if counter > 10:  # Safety check
            tag_name = f"{base_name}-{int(time.time())}"
            break
    
    url = f"https://api.github.com/repos/{repo_name}/releases"
    
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    data = {
        "tag_name": tag_name,
        "name": tag_name,
        "body": f"Auto-uploaded video - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "draft": False,
        "prerelease": False
    }
    
    response = requests.post(url, json=data, headers=headers)
    
    if response.status_code == 201:
        print(f"✓ Created release: {tag_name}")
        return response.json()
    else:
        print(f"✗ Error creating release: {response.status_code}")
        print(response.text)
        return None

def upload_to_release(repo_name, release_id, file_path, token):
    """Upload file to GitHub release"""
    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    
    print(f"Uploading: {file_name} ({file_size / (1024*1024):.2f} MB)")
    
    url = f"https://uploads.github.com/repos/{repo_name}/releases/{release_id}/assets?name={file_name}"
    
    headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/octet-stream"
    }
    
    try:
        with open(file_path, 'rb') as f:
            response = requests.post(url, data=f, headers=headers, timeout=600)
        
        if response.status_code == 201:
            asset_data = response.json()
            download_url = asset_data['browser_download_url']
            print(f"✓ Upload successful!")
            print(f"Download URL: {download_url}")
            return download_url
        else:
            print(f"✗ Upload failed: {response.status_code}")
            print(response.text)
            return None
            
    except Exception as e:
        print(f"✗ Error uploading: {e}")
        return None

def process_drive_file():
    """Main processing function - Only keeps GitHub links"""
    print("=" * 80)
    print("GitHub Actions - Drive to Release Uploader")
    print("=" * 80)
    
    if not os.path.exists(DRIVE_FILE):
        print(f"✗ {DRIVE_FILE} not found!")
        return
    
    # Read drive.txt
    with open(DRIVE_FILE, 'r') as f:
        lines = f.readlines()
    
    github_links = []  # Only store GitHub links
    temp_folder = "temp_videos"
    os.makedirs(temp_folder, exist_ok=True)
    
    for idx, line in enumerate(lines, 1):
        line = line.strip()
        
        # Skip empty lines
        if not line:
            continue
        
        # If already a GitHub link, keep it
        if 'github.com' in line:
            print(f"\n[{idx}/{len(lines)}] Already GitHub link - keeping it")
            github_links.append(line)
            continue
        
        # Check if it's a Drive URL
        if 'drive.google.com' not in line:
            print(f"\n[{idx}/{len(lines)}] Not a Drive URL - skipping")
            continue
        
        print(f"\n[{idx}/{len(lines)}] Processing Drive URL...")
        print(f"URL: {line[:60]}...")
        
        # Extract file ID
        file_id = extract_drive_file_id(line)
        if not file_id:
            print("✗ Could not extract file ID - skipping")
            continue
        
        # Get original filename
        original_name = get_drive_file_info(file_id)
        base_name = Path(original_name).stem
        extension = Path(original_name).suffix or '.mp4'
        
        # Generate filename
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', base_name)[:50]
        filename = f"{safe_name}{extension}"
        temp_path = os.path.join(temp_folder, filename)
        
        # Download from Drive
        if not download_large_file_from_drive(file_id, temp_path):
            print("✗ Download failed - skipping this video")
            continue
        
        # Create release
        release_tag = f"video-{safe_name}"
        release = create_unique_release(REPO_NAME, release_tag, GITHUB_TOKEN)
        
        if not release:
            print("✗ Failed to create release")
            os.remove(temp_path)
            continue
        
        # Upload to release
        github_url = upload_to_release(REPO_NAME, release['id'], temp_path, GITHUB_TOKEN)
        
        if github_url:
            # Add GitHub URL to list
            github_links.append(github_url)
            print(f"✓ Successfully processed!")
        else:
            print("✗ Upload failed - video not added")
        
        # Cleanup
        try:
            os.remove(temp_path)
        except:
            pass
        
        print("-" * 80)
    
    # Write ONLY GitHub links to drive.txt
    with open(DRIVE_FILE, 'w') as f:
        for link in github_links:
            f.write(link + '\n')
    
    print("\n" + "=" * 80)
    print("✓ Processing completed!")
    print(f"✓ {DRIVE_FILE} updated - contains {len(github_links)} GitHub links")
    print(f"✓ All old Drive links removed")
    print("=" * 80)

if __name__ == "__main__":
    process_drive_file()
