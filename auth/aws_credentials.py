from google.auth import identity_pool
from google.auth.transport.requests import Request
import boto3
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import os
from botocore.config import Config
from fastapi import HTTPException

class AWSCredentialsManager:
    def __init__(self):
        self.aws_role_arn = os.getenv("AWS_ROLE_ARN")
        self.workload_identity_pool = os.getenv("WORKLOAD_IDENTITY_POOL")
        self.provider_id = os.getenv("WORKLOAD_IDENTITY_PROVIDER")
        self.region = os.getenv("AWS_REGION", "us-east-1")
        
        if not all([self.aws_role_arn, self.workload_identity_pool, self.provider_id]):
            raise ValueError("Missing required AWS configuration")
        
        # Cache for credentials
        self._credentials_cache: Optional[Dict[str, Any]] = None
        self._credentials_expiry: Optional[datetime] = None
        self._google_credentials: Optional[identity_pool.Credentials] = None
        
        # Configuration
        self.session_duration = 3600  # 1 hour
        self.refresh_buffer = 300     # 5 minutes

    async def get_credentials(self) -> Dict[str, Any]:
        """Get AWS credentials with caching"""
        try:
            if self._should_refresh_credentials():
                await self._refresh_credentials()
            return self._credentials_cache
        except Exception as e:
            self.clear_cache()
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get AWS credentials: {str(e)}"
            )

    def _should_refresh_credentials(self) -> bool:
        """Check if credentials need to be refreshed"""
        if not self._credentials_cache or not self._credentials_expiry:
            return True
        
        # Refresh if within buffer period of expiry
        return datetime.utcnow() >= (self._credentials_expiry - timedelta(seconds=self.refresh_buffer))

    async def _refresh_credentials(self) -> None:
        """Refresh AWS credentials using Workload Identity Federation"""
        try:
            # Get or refresh Google credentials
            if not self._google_credentials:
                self._google_credentials = identity_pool.Credentials(
                    audience=self.provider_id,
                    subject_token_type="urn:ietf:params:oauth:token-type:jwt",
                    token_url=self.workload_identity_pool,
                    service_account_impersonation_url=None
                )
            
            self._google_credentials.refresh(Request())
            
            # Exchange Google token for AWS credentials
            sts_client = boto3.client('sts', region_name=self.region)
            response = sts_client.assume_role_with_web_identity(
                RoleArn=self.aws_role_arn,
                RoleSessionName=f'bedrock-proxy-{datetime.utcnow().strftime("%Y%m%d-%H%M%S")}',
                WebIdentityToken=self._google_credentials.token,
                DurationSeconds=self.session_duration
            )
            
            # Cache the credentials
            self._credentials_cache = {
                'aws_access_key_id': response['Credentials']['AccessKeyId'],
                'aws_secret_access_key': response['Credentials']['SecretAccessKey'],
                'aws_session_token': response['Credentials']['SessionToken']
            }
            
            # Set expiry time
            self._credentials_expiry = datetime.strptime(
                response['Credentials']['Expiration'].strftime("%Y-%m-%d %H:%M:%S"),
                "%Y-%m-%d %H:%M:%S"
            )
            
        except Exception as e:
            self.clear_cache()
            raise Exception(f"Failed to refresh AWS credentials: {str(e)}")

    async def get_boto3_config(self) -> Config:
        """Get boto3 configuration with current credentials"""
        credentials = await self.get_credentials()
        return Config(
            region_name=self.region,
            credentials=credentials,
            retries={
                'max_attempts': 3,
                'mode': 'standard'
            }
        )

    def clear_cache(self) -> None:
        """Clear credentials cache"""
        self._credentials_cache = None
        self._credentials_expiry = None
        self._google_credentials = None
