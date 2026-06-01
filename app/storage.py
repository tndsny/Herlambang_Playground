import os
import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

r2_client = boto3.client(
    service_name="s3",
    endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    config=Config(signature_version="s3v4")
)

BUCKET_NAME = os.getenv("R2_BUCKET_NAME")

def dapatkan_url_durasi_terbatas(object_name: str, expires_in: int = 3600):
    return r2_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': BUCKET_NAME, 'Key': object_name},
        ExpiresIn=expires_in
    )

def upload_file_ke_r2(local_path: str, object_name: str):
    print(f"Mengunggah {object_name} balik ke Cloudflare R2...")
    r2_client.upload_file(local_path, BUCKET_NAME, object_name)
    return dapatkan_url_durasi_terbatas(object_name)