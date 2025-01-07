from fastapi import FastAPI, HTTPException
from auth.aws_credentials import AWSCredentialsManager
from services.bedrock_client import BedrockClientManager
from services.gcp_gateway import GCPGatewayClient
from models.request_models import ProxyRequest
from models.response_models import ProxyResponse

app = FastAPI()

# Initialize services
credentials_manager = AWSCredentialsManager()
bedrock_client_manager = BedrockClientManager(credentials_manager)
gcp_gateway = GCPGatewayClient()

@app.post("/predict")
async def predict(request: ProxyRequest) -> ProxyResponse:
    try:
        # Validate with GCP Gateway
        gateway_response = await gcp_gateway.validate_request(request.dict())
        
        if gateway_response.get("status") != "approved":
            raise HTTPException(
                status_code=403,
                detail="Request not approved by GCP Gateway"
            )

        # Get Bedrock client and make request
        client = await bedrock_client_manager.get_client(request.bedrock_api.operation)
        operation_method = getattr(client, request.bedrock_api.operation.lower())
        response = operation_method(**request.bedrock_api.request_payload)

        return ProxyResponse(
            status="success",
            operation=request.bedrock_api.operation,
            response=response
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing request: {str(e)}"
        )