import boto3
import os

REGIONS = [
    'us-east-1', 'us-west-2', 'eu-central-1', 'ap-southeast-1', 
    'ap-northeast-1', 'sa-east-1', 'us-east-2', 'eu-west-1', 
    'ap-south-1', 'ca-central-1', 'eu-west-3'
]

class CloudDispatcher:
    def __init__(self, access_key, secret_key):
        self.access_key = access_key
        self.secret_key = secret_key

    def upload_shard(self, shard_index, file_path, progress_callback):
        region = REGIONS[shard_index]
        bucket_name = f"ansx-vault-shard-{shard_index+1}-{region}"
        
        try:
            s3 = boto3.client('s3', region_name=region, 
                              aws_access_key_id=self.access_key, 
                              aws_secret_access_key=self.secret_key)
            
            file_size = os.path.getsize(file_path)
            # FIX: Local variable so threads don't fight
            bytes_sent = 0 

            def upload_callback(chunk_size):
                nonlocal bytes_sent
                bytes_sent += chunk_size
                percentage = int((bytes_sent / file_size) * 100)
                # Cap it at 100 to prevent UI flicker
                progress_callback(shard_index, min(percentage, 100))

            s3.upload_file(
                file_path, 
                bucket_name, 
                os.path.basename(file_path), 
                Callback=upload_callback
            )
            return True
        except Exception as e:
            print(f"CRITICAL ERROR Node {shard_index+1} ({region}): {e}")
            return False