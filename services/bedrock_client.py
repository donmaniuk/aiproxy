from botocore.config import Config
import boto3
from typing import Dict, Any
from auth.aws_credentials import AWSCredentialsManager

class BedrockClientManager:
    _instances = {}

    def __init__(self, credentials_manager: AWSCredentialsManager):
        self.credentials_manager = credentials_manager
        self.aws_region = os.getenv("AWS_REGION", "us-east-1")
        self.bedrock_services = {
            "runtime": "bedrock-runtime",
            "agent": "bedrock-agent",
            "default": "bedrock"
        }

    async def get_client(self, operation: str):
        """Get the appropriate Bedrock client based on the operation"""
        service = self._determine_service(operation)
        credentials = await self.credentials_manager.get_credentials()
        
        config = Config(
            region_name=self.aws_region,
            credentials={
                'aws_access_key_id': credentials['AccessKeyId'],
                'aws_secret_access_key': credentials['SecretAccessKey'],
                'aws_session_token': credentials['SessionToken']
            }
        )
        
        self._instances[service] = boto3.client(
            service,
            config=config
        )
        return self._instances[service]

    def _determine_service(self, operation: str) -> str:
        operation_lower = operation.lower()
        if operation_lower.startswith(("invoke", "stream")):
            return self.bedrock_services["runtime"]
        elif operation_lower.startswith("agent"):
            return self.bedrock_services["agent"]
        return self.bedrock_services["default"]
