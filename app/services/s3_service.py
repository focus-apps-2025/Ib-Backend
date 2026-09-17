import uuid
import asyncio
from typing import Optional, Dict
from loguru import logger
from app.config.settings import settings

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.warning("boto3 is not installed. S3 upload will be unavailable.")


class S3Service:
    def __init__(self):
        self.bucket = settings.AWS_S3_BUCKET
        self.region = settings.AWS_S3_REGION
        self.cloudfront_domain = settings.AWS_CLOUDFRONT_DOMAIN.strip()
        
        if BOTO3_AVAILABLE and settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            self.client = boto3.client(
                "s3",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=self.region,
            )
            logger.info(f"S3Service initialized for bucket: {self.bucket}")
        else:
            self.client = None
            logger.warning("S3Service client not initialized (missing AWS credentials or boto3).")

    def _get_public_url(self, key: str) -> str:
        clean_key = key.lstrip("/")
        # Remove any duplicate market_feedback/ prefixes
        while "market_feedback/market_feedback/" in clean_key:
            clean_key = clean_key.replace("market_feedback/market_feedback/", "market_feedback/")
        
        # CloudFront has Origin Path set to /market_feedback, so URL path must be /<filename>
        url_filename = clean_key[len("market_feedback/"):] if clean_key.startswith("market_feedback/") else clean_key

        if self.cloudfront_domain:
            domain = self.cloudfront_domain.replace("https://", "").replace("http://", "").rstrip("/")
            return f"https://{domain}/{url_filename}"
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/market_feedback/{url_filename}"

    def upload_file_sync(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str = "image/jpeg",
        folder: str = "market_feedback",
    ) -> Dict[str, str]:
        if not self.client:
            raise RuntimeError("AWS S3 client is not configured. Please check AWS credentials in .env")

        clean_filename = filename.replace(" ", "_")
        unique_id = uuid.uuid4().hex[:10]
        clean_folder = (folder or "market_feedback").strip("/")
        s3_key = f"{clean_folder}/{unique_id}_{clean_filename}"

        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=file_bytes,
                ContentType=content_type,
            )
            url = self._get_public_url(s3_key)
            logger.info(f"Successfully uploaded file to S3: {s3_key}")
            return {
                "url": url,
                "s3_key": s3_key,
            }
        except (BotoCoreError, ClientError) as e:
            logger.error(f"S3 Upload failed for key {s3_key}: {e}")
            raise RuntimeError(f"Failed to upload image to S3: {str(e)}")

    async def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str = "image/jpeg",
        folder: str = "market_feedback",
    ) -> Dict[str, str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.upload_file_sync, file_bytes, filename, content_type, folder
        )

    def delete_file_sync(self, s3_key: str) -> bool:
        if not self.client or not s3_key:
            return False
        try:
            self.client.delete_object(Bucket=self.bucket, Key=s3_key)
            logger.info(f"Successfully deleted S3 key: {s3_key}")
            return True
        except (BotoCoreError, ClientError) as e:
            logger.error(f"Failed to delete S3 key {s3_key}: {e}")
            return False

    async def delete_file(self, s3_key: str) -> bool:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.delete_file_sync, s3_key)


s3_service = S3Service()
