from __future__ import annotations

from edgerunner.env import resolve_env_reference

from google.cloud import secretmanager


def access_secret(secret_version_name: str) -> str:
    if secret_version_name.startswith("env:"):
        return resolve_env_reference(secret_version_name)

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": secret_version_name})
    return response.payload.data.decode("utf-8")
