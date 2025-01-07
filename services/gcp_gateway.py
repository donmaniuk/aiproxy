# services/gcp_gateway.py
from auth.gcp_credentials import GCPTokenManager
import httpx
from typing import Dict, Any
import os
from fastapi import HTTPException

class GCPGatewayClient:
    def __init__(self):
        self.token_manager = GCPTokenManager()
        self.gateway_url = os.getenv("GCP_GATEWAY_URL")
        self.timeout = int(os.getenv("GATEWAY_TIMEOUT", "30"))
        
        if not self.gateway_url:
            raise ValueError("Missing GCP_GATEWAY_URL configuration")

    async def validate_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate the request through GCP API Gateway
        """
        try:
            headers = await self.token_manager.get_authorization_headers()
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.gateway_url,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                
                validation_response = response.json()
                if validation_response.get("status") != "approved":
                    raise HTTPException(
                        status_code=403,
                        detail="Request not approved by GCP Gateway"
                    )
                    
                return validation_response
                
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=500,
                detail=f"GCP Gateway request failed: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Validation error: {str(e)}"
            )
