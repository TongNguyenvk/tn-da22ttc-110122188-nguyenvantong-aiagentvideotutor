"""
Cloudflare R2 storage client for video and file uploads.

Uses boto3 with S3-compatible API to interact with Cloudflare R2.
Handles video uploads, thumbnail generation, and CDN URL generation.
"""

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
import os
from pathlib import Path
import logging
from typing import Optional

logger = logging.getLogger(__name__)

R2_ENDPOINT = os.getenv("R2_ENDPOINT", "")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY", "")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY", "")
R2_BUCKET = os.getenv("R2_BUCKET", "webreel-videos")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")


class R2Storage:
    """Cloudflare R2 storage client with S3-compatible API."""
    
    def __init__(self):
        """Initialize R2 client with credentials from environment."""
        self.enabled = bool(R2_ENDPOINT and R2_ACCESS_KEY and R2_SECRET_KEY)
        
        if not self.enabled:
            logger.warning("R2 storage not configured (missing credentials)")
            self.client = None
            return
        
        try:
            self.client = boto3.client(
                's3',
                endpoint_url=R2_ENDPOINT,
                aws_access_key_id=R2_ACCESS_KEY,
                aws_secret_access_key=R2_SECRET_KEY,
                config=Config(signature_version='s3v4'),
                region_name='auto'
            )
            self.bucket = R2_BUCKET
            
            # Test connection
            self.client.head_bucket(Bucket=self.bucket)
            logger.info(f"R2 storage connected: {self.bucket}")
            
        except ClientError as e:
            logger.error(f"R2 connection failed: {e}")
            self.client = None
            self.enabled = False
        except Exception as e:
            logger.error(f"R2 initialization failed: {e}")
            self.client = None
            self.enabled = False
    
    def is_enabled(self) -> bool:
        """Check if R2 storage is enabled and connected."""
        return self.enabled and self.client is not None
    
    async def upload_video(self, local_path: Path, job_id: str) -> Optional[dict]:
        """
        Upload video to R2 and return metadata.
        
        Args:
            local_path: Path to local video file
            job_id: Job UUID for organizing files
            
        Returns:
            dict: Metadata with r2_key, cdn_url, file_size_bytes
        """
        if not self.is_enabled():
            logger.warning("R2 storage not enabled, skipping video upload")
            return None
        
        if not local_path.exists():
            logger.error(f"Video file not found: {local_path}")
            return None
        
        try:
            # Generate R2 key
            key = f"videos/{job_id}_{local_path.name}"
            
            # Upload file
            self.client.upload_file(
                str(local_path),
                self.bucket,
                key,
                ExtraArgs={
                    'ContentType': 'video/mp4',
                    'CacheControl': 'public, max-age=31536000',  # 1 year
                }
            )
            
            # Generate CDN URL
            cdn_url = f"{R2_PUBLIC_URL}/{key}" if R2_PUBLIC_URL else f"{R2_ENDPOINT}/{self.bucket}/{key}"
            
            logger.info(f"Video uploaded to R2: {key} ({local_path.stat().st_size} bytes)")
            
            return {
                "r2_key": key,
                "r2_bucket": self.bucket,
                "cdn_url": cdn_url,
                "file_size_bytes": local_path.stat().st_size
            }
            
        except Exception as e:
            logger.error(f"Failed to upload video to R2: {e}")
            return None
    
    async def upload_thumbnail(self, local_path: Path, job_id: str) -> Optional[str]:
        """
        Upload thumbnail to R2.
        
        Args:
            local_path: Path to local thumbnail file
            job_id: Job UUID for organizing files
            
        Returns:
            str: CDN URL or None
        """
        if not self.is_enabled():
            return None
        
        if not local_path.exists():
            logger.error(f"Thumbnail file not found: {local_path}")
            return None
        
        try:
            # Generate R2 key
            key = f"thumbnails/{job_id}_{local_path.name}"
            
            # Upload file
            self.client.upload_file(
                str(local_path),
                self.bucket,
                key,
                ExtraArgs={
                    'ContentType': 'image/jpeg',
                    'CacheControl': 'public, max-age=31536000',
                }
            )
            
            # Generate CDN URL
            cdn_url = f"{R2_PUBLIC_URL}/{key}" if R2_PUBLIC_URL else f"{R2_ENDPOINT}/{self.bucket}/{key}"
            
            logger.info(f"Thumbnail uploaded to R2: {key}")
            
            return cdn_url
            
        except Exception as e:
            logger.error(f"Failed to upload thumbnail to R2: {e}")
            return None
    
    async def upload_file(self, local_path: Path, prefix: str = "uploads") -> Optional[str]:
        """
        Upload arbitrary file to R2.
        
        Args:
            local_path: Path to local file
            prefix: R2 key prefix (folder)
            
        Returns:
            str: CDN URL or None
        """
        if not self.is_enabled():
            return None
        
        if not local_path.exists():
            logger.error(f"File not found: {local_path}")
            return None
        
        try:
            # Generate R2 key
            key = f"{prefix}/{local_path.name}"
            
            # Detect content type
            content_type = self._get_content_type(local_path)
            
            # Upload file
            self.client.upload_file(
                str(local_path),
                self.bucket,
                key,
                ExtraArgs={
                    'ContentType': content_type,
                    'CacheControl': 'public, max-age=86400',  # 1 day
                }
            )
            
            # Generate CDN URL
            cdn_url = f"{R2_PUBLIC_URL}/{key}" if R2_PUBLIC_URL else f"{R2_ENDPOINT}/{self.bucket}/{key}"
            
            logger.info(f"File uploaded to R2: {key}")
            
            return cdn_url
            
        except Exception as e:
            logger.error(f"Failed to upload file to R2: {e}")
            return None
    
    async def delete_file(self, r2_key: str) -> bool:
        """
        Delete file from R2.

        Args:
            r2_key: R2 object key

        Returns:
            bool: Success status
        """
        if not self.is_enabled():
            return False

        try:
            self.client.delete_object(Bucket=self.bucket, Key=r2_key)
            logger.info(f"File deleted from R2: {r2_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file from R2: {e}")
            return False

    @staticmethod
    def derive_r2_key_from_url(url: Optional[str]) -> Optional[str]:
        """Recover the R2 object key from a stored CDN URL.

        Old jobs only have `result.video_url` (the permanent public URL
        we used to write). To sign on demand we need the key — strip
        whichever prefix matches our R2 setup:

          - `<R2_PUBLIC_URL>/<key>`             custom CDN domain
          - `<R2_ENDPOINT>/<bucket>/<key>`      direct S3 endpoint

        Returns None if the URL is empty, relative, or doesn't match
        either prefix (e.g. a local FileResponse path).
        """
        if not url or not url.startswith("http"):
            return None

        if R2_PUBLIC_URL and url.startswith(R2_PUBLIC_URL + "/"):
            return url[len(R2_PUBLIC_URL) + 1 :]

        if R2_ENDPOINT:
            endpoint_bucket = f"{R2_ENDPOINT.rstrip('/')}/{R2_BUCKET}/"
            if url.startswith(endpoint_bucket):
                return url[len(endpoint_bucket) :]

        return None

    def generate_presigned_url(
        self, r2_key: str, expires_in: int = 600, inline: bool = True
    ) -> Optional[str]:
        """Return a short-lived signed GET URL for an R2 object.

        This is what the admin UI / owner Dashboard hits when the user
        clicks "Xem". The URL embeds an HMAC of (bucket, key, expiry)
        signed with R2_SECRET_KEY, so anyone with the link can stream
        the video for `expires_in` seconds — but after expiry the same
        URL returns 403 from R2. This replaces the previous behaviour
        of storing a permanent public CDN URL on the job record.

        Args:
            r2_key: the R2 object key (e.g. "videos/<job_id>_foo.mp4")
            expires_in: TTL in seconds (default 10 min — long enough to
                start playback, short enough that a leaked URL stops
                working before the user finishes a coffee)
            inline: True → Content-Disposition: inline (browser <video>
                streams); False → attachment (force download).
        """
        if not self.is_enabled():
            return None
        try:
            params = {"Bucket": self.bucket, "Key": r2_key}
            if inline:
                # Override the per-object Content-Disposition R2 returns
                # so the browser plays in-place instead of downloading.
                params["ResponseContentDisposition"] = "inline"
            return self.client.generate_presigned_url(
                ClientMethod="get_object",
                Params=params,
                ExpiresIn=expires_in,
            )
        except Exception as e:
            logger.error(f"Failed to sign URL for {r2_key}: {e}")
            return None
    
    @staticmethod
    def _get_content_type(path: Path) -> str:
        """Detect content type from file extension."""
        ext = path.suffix.lower()
        content_types = {
            '.mp4': 'video/mp4',
            '.webm': 'video/webm',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.pdf': 'application/pdf',
            '.json': 'application/json',
        }
        return content_types.get(ext, 'application/octet-stream')
