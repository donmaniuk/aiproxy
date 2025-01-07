from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List, Union
import httpx
import boto3
import json
import os
from datetime import datetime

# Models
class RequestMetadata(BaseModel):
    requestId: Optional[str] = None
    timestamp: Optional[datetime] = None
    sourceIp: Optional[str] = None
    userAgent: Optional[str] = None

class BedrockAPI(BaseModel):
    operation: str  # Now accepts any Bedrock operation
    request_payload: Dict[str, Any]
    metadata: Optional[RequestMetadata] = None

class ProxyRequest(BaseModel):
    bedrock_api: BedrockAPI

# Application Configuration
class Config:
    GCP_GATEWAY_URL = os.getenv("GCP_GATEWAY_URL", "https://your-gateway-url.com")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    TIMEOUT_SECONDS = 30
    # List of allowed Bedrock services
    BEDROCK_SERVICES = {
        "runtime": "bedrock-runtime",  # For model inference
        "agent": "bedrock-agent",      # For agents
        "default": "bedrock"           # For knowledge bases and other operations
    }

# Initialize FastAPI app
app = FastAPI(
    title="Bedrock Proxy Application",
    description="Generic proxy service for Amazon Bedrock API calls via GCP Gateway",
    version="0.1.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class BedrockClientManager:
    """Manages different Bedrock service clients"""
    _instances = {}

    @classmethod
    def get_client(cls, operation: str):
        """Get the appropriate Bedrock client based on the operation"""
        service = cls._determine_service(operation)
        if service not in cls._instances:
            cls._instances[service] = boto3.client(
                service,
                region_name=Config.AWS_REGION
            )
        return cls._instances[service]

    @staticmethod
    def _determine_service(operation: str) -> str:
        """Determine which Bedrock service to use based on the operation"""
        operation_lower = operation.lower()
        if operation_lower.startswith(("invoke", "stream")):
            return Config.BEDROCK_SERVICES["runtime"]
        elif operation_lower.startswith("agent"):
            return Config.BEDROCK_SERVICES["agent"]
        return Config.BEDROCK_SERVICES["default"]

# Initialize HTTP client
http_client = httpx.AsyncClient(timeout=Config.TIMEOUT_SECONDS)

@app.get("/")
async def root():
    return {"status": "ok", "message": "Bedrock Generic Proxy Service"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/ready")
async def readiness_check():
    return {"status": "ready"}

@app.post("/predict")
async def predict(request: ProxyRequest):
    try:
        # 1. Validate and prepare the request for GCP Gateway
        gcp_payload = prepare_gcp_request(request)
        
        # 2. Send request to GCP Gateway
        gateway_response = await forward_to_gcp(gcp_payload)
        
        # 3. If gateway approves, forward to appropriate Bedrock service
        if gateway_response.get("status") == "approved":
            bedrock_response = await call_bedrock_service(request.bedrock_api)
            return bedrock_response
        else:
            raise HTTPException(
                status_code=403,
                detail="Request not approved by GCP Gateway"
            )
            
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing request: {str(e)}"
        )

def prepare_gcp_request(request: ProxyRequest) -> Dict[str, Any]:
    """Prepare the request payload for GCP Gateway"""
    return {
        "operation": request.bedrock_api.operation,
        "payload": request.bedrock_api.request_payload,
        "metadata": request.bedrock_api.metadata.dict() if request.bedrock_api.metadata else {}
    }

async def forward_to_gcp(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Forward the request to GCP Gateway"""
    try:
        async with http_client as client:
            response = await client.post(
                Config.GCP_GATEWAY_URL,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Error communicating with GCP Gateway: {str(e)}"
        )

async def call_bedrock_service(bedrock_api: BedrockAPI) -> Dict[str, Any]:
    """Dynamically call any Bedrock service operation"""
    try:
        # Get the appropriate client for the operation
        client = BedrockClientManager.get_client(bedrock_api.operation)
        
        # Convert operation name from PascalCase to snake_case
        operation_name = ''.join(['_' + c.lower() if c.isupper() else c.lower() 
                                for c in bedrock_api.operation]).lstrip('_')
        
        # Get the operation method
        operation_method = getattr(client, operation_name)
        
        # Call the operation with the provided payload
        response = operation_method(**bedrock_api.request_payload)
        
        # Clean and return the response
        return {
            "status": "success",
            "operation": bedrock_api.operation,
            "response": clean_response(response)
        }
    except AttributeError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid Bedrock operation: {bedrock_api.operation}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error calling Bedrock service: {str(e)}"
        )

def clean_response(response: Dict[str, Any]) -> Dict[str, Any]:
    """Clean the Bedrock response for JSON serialization"""
    if isinstance(response, (bytes, bytearray)):
        return {"body": response.decode('utf-8')}
    
    # Convert boto3 response to dictionary
    if hasattr(response, 'get'):
        response_dict = {}
        for key in response.keys():
            value = response[key]
            if isinstance(value, (bytes, bytearray)):
                response_dict[key] = value.decode('utf-8')
            else:
                response_dict[key] = value
        return response_dict
    
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)