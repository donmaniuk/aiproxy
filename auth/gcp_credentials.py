# auth/gcp_credentials.py
from google.auth import identity_pool
from google.auth.transport.requests import Request
from typing import Dict, Optional
from datetime import datetime, timedelta
import os
from fastapi import HTTPException

class GCPTokenManager:
    def __init__(self):
        self.workload_identity_pool = os.getenv("GCP_WORKLOAD_IDENTITY_POOL")
        self.provider_id = os.getenv("GCP_PROVIDER_ID")
        
        if not all([self.workload_identity_pool, self.provider_id]):
            raise ValueError("Missing required GCP configuration")
        
        self.token_cache: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        self._credentials: Optional[identity_pool.Credentials] = None
        self.refresh_buffer = 300  # 5 minutes

    async def get_token(self) -> str:
        """Get Google Cloud token with caching"""
        if self._is_token_valid():
            return self.token_cache

        try:
            if not self._credentials:
                self._credentials = identity_pool.Credentials(
                    audience=self.provider_id,
                    subject_token_type="urn:ietf:params:oauth:token-type:jwt",
                    token_url=self.workload_identity_pool,
                    service_account_impersonation_url=None,
                    scope=['https://www.googleapis.com/auth/cloud-platform']
                )
            
            self._credentials.refresh(Request())
            
            self.token_cache = self._credentials.token
            self.token_expiry = datetime.now() + timedelta(seconds=3600)  # 1 hour
            
            return self.token_cache
        except Exception as e:
            self.clear_cache()
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get Google Cloud token: {str(e)}"
            )

    def _is_token_valid(self) -> bool:
        """Check if cached token is still valid"""
        if not self.token_cache or not self.token_expiry:
            return False
        
        return datetime.now() < (self.token_expiry - timedelta(seconds=self.refresh_buffer))

    async def get_authorization_headers(self) -> Dict[str, str]:
        """Get headers with valid Google Cloud token"""
        token = await self.get_token()
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

    def clear_cache(self) -> None:
        """Clear token cache"""
        self.token_cache = None
        self.token_expiry = None
        self._credentials = None
