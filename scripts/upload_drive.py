import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth import default

def upload_files(folder_id, local_path):
    # 自动获取 GitHub Action 环境中的临时凭据
    creds, _ = default()
    service = build('drive', 'v3', credentials=creds)

    for filename in os.listdir(local_path):
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaFileUpload(f'{local_path}/{filename}')
        service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        print(f"Uploaded: {filename}")

if __name__ == "__main__":
    upload_files(os.environ['GDRIVE_FOLDER_ID'], './output')