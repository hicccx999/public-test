import os
import sys
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth import default


def get_drive_service():
    """通过 Workload Identity Federation 获取 Google Drive 服务"""
    scopes = ['https://www.googleapis.com/auth/drive.file']
    creds, project = default(scopes=scopes)
    print(f"Authenticated with project: {project}")
    return build('drive', 'v3', credentials=creds)


def upload_files(folder_id, local_path):
    """上传指定目录下的所有文件到 Google Drive 文件夹"""
    if not os.path.isdir(local_path):
        print(f"Error: Directory '{local_path}' does not exist")
        sys.exit(1)

    files = [f for f in os.listdir(local_path) if os.path.isfile(os.path.join(local_path, f))]
    if not files:
        print(f"No files found in '{local_path}'")
        return

    service = get_drive_service()
    print(f"Uploading {len(files)} file(s) to Drive folder: {folder_id}")

    success_count = 0
    for filename in files:
        filepath = os.path.join(local_path, filename)
        file_metadata = {
            'name': filename,
            'parents': [folder_id],
        }
        media = MediaFileUpload(filepath, resumable=True)
        try:
            result = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink'
            ).execute()
            print(f"  ✓ Uploaded: {filename} (id: {result.get('id')})")
            if result.get('webViewLink'):
                print(f"    Link: {result.get('webViewLink')}")
            success_count += 1
        except Exception as e:
            print(f"  ✗ Failed to upload {filename}: {e}")

    print(f"\nDone: {success_count}/{len(files)} files uploaded successfully")
    if success_count < len(files):
        sys.exit(1)


if __name__ == "__main__":
    folder_id = os.environ.get('GDRIVE_FOLDER_ID')
    if not folder_id:
        print("Error: GDRIVE_FOLDER_ID environment variable is not set")
        sys.exit(1)

    local_path = sys.argv[1] if len(sys.argv) > 1 else './output'
    upload_files(folder_id, local_path)