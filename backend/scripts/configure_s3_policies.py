"""Configure MinIO bucket policies for public read access on avatar/asset prefixes.

Usage:
    python -m scripts.configure_s3_policies

Requires S3 env vars (S3_ACCESS_KEY, S3_SECRET_KEY, S3_ENDPOINT_URL, S3_BUCKET_NAME)
to be set in the environment or in backend/env/common.env.
"""

import asyncio
import json

from aiobotocore.session import get_session
from loguru import logger

# Load settings – works when executed from backend/ with PYTHONPATH including shared/
from shared.core.config import BaseServiceSettings

settings = BaseServiceSettings()

BUCKET_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PublicReadAvatarsAndAssets",
            "Effect": "Allow",
            "Principal": {"AWS": ["*"]},
            "Action": ["s3:GetObject"],
            "Resource": [
                f"arn:aws:s3:::{settings.s3_bucket_name}/avatars/*",
                f"arn:aws:s3:::{settings.s3_bucket_name}/assets/*",
            ],
        }
    ],
}


async def main() -> None:
    session = get_session()
    config = {
        "aws_access_key_id": settings.s3_access_key,
        "aws_secret_access_key": settings.s3_secret_key,
        "endpoint_url": settings.s3_endpoint_url,
    }

    async with session.create_client("s3", **config) as client:
        policy_json = json.dumps(BUCKET_POLICY)
        await client.put_bucket_policy(
            Bucket=settings.s3_bucket_name,
            Policy=policy_json,
        )
        logger.info(
            f"Bucket policy applied to '{settings.s3_bucket_name}': "
            f"public read on avatars/* and assets/*"
        )

        # Verify
        response = await client.get_bucket_policy(Bucket=settings.s3_bucket_name)
        current = json.loads(response["Policy"])
        logger.info(f"Current policy: {json.dumps(current, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
