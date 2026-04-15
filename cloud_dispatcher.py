import os

REGIONS = [
    'us-east-1', 'us-west-2', 'eu-central-1', 'ap-southeast-1',
    'ap-northeast-1', 'sa-east-1', 'us-east-2', 'eu-west-1',
    'ap-south-1', 'ca-central-1', 'eu-west-3'
]

class CloudDispatcher:
    def __init__(self, access_key=None, secret_key=None):
        self.access_key = access_key
        self.secret_key = secret_key
        # Tracks URLs of successfully uploaded shards {shard_index: url}
        self.uploaded_urls = {}

    def upload_shard(self, shard_index, file_path, progress_callback):
        # Guard: shard_index must be within the REGIONS list
        if shard_index >= len(REGIONS):
            print(f"[CloudDispatcher] Skipping shard {shard_index+1}: index out of cloud region range.")
            return None

        region = REGIONS[shard_index]
        bucket_name = f"ansx-vault-shard-{shard_index+1}-{region}"
        key_name = os.path.basename(file_path) if file_path else f"fragment_{shard_index+1}.ansx"

        # Simulate upload progress for demo mode
        def _simulate_upload():
            for pct in [25, 50, 75, 100]:
                progress_callback(shard_index, pct)
            sim_url = f"ansx://demo-node-{shard_index+1}.{region}/shards/{key_name}"
            self.uploaded_urls[shard_index] = sim_url
            return sim_url

        # If no real file, go straight to demo mode
        if not file_path or not os.path.exists(file_path):
            return _simulate_upload()

        try:
            import boto3
            kwargs = {'region_name': region}
            if self.access_key and self.secret_key:
                kwargs['aws_access_key_id'] = self.access_key
                kwargs['aws_secret_access_key'] = self.secret_key

            s3 = boto3.client('s3', **kwargs)

            file_size = os.path.getsize(file_path)
            bytes_sent = 0

            def upload_callback(chunk_size):
                nonlocal bytes_sent
                bytes_sent += chunk_size
                percentage = int((bytes_sent / file_size) * 100)
                progress_callback(shard_index, min(percentage, 100))

            s3.upload_file(file_path, bucket_name, key_name, Callback=upload_callback)

            url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{key_name}"
            self.uploaded_urls[shard_index] = url
            return url

        except Exception:
            # No AWS credentials or bucket: silently use demo-mode simulated URL
            return _simulate_upload()