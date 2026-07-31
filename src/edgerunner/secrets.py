from __future__ import annotations

from google.cloud import secretmanager


def access_secret(secret_version_name: str) -> str:
    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": secret_version_name})
    return response.payload.data.decode("utf-8")
