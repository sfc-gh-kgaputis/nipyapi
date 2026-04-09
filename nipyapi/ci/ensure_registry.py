# pylint: disable=duplicate-code
"""
ensure_registry - convenience function for Git Flow Registry Client setup.

Wraps nipyapi.versioning.ensure_registry_client with:
- Environment variable support for CI/CD
- Provider abstraction (GitHub/GitLab)
- Sensible defaults
"""

import logging
import os
from typing import Optional

import nipyapi

log = logging.getLogger(__name__)

# Provider configurations
PROVIDERS = {
    "github": {
        "reg_type": "org.apache.nifi.github.GitHubFlowRegistryClient",
        "api_url_key": "GitHub API URL",
        "api_url_default": "https://api.github.com/",
        "owner_key": "Repository Owner",
        "auth_type_key": "Authentication Type",
        "auth_type_value": "PERSONAL_ACCESS_TOKEN",
        "token_key": "Personal Access Token",
    },
    "gitlab": {
        "reg_type": "org.apache.nifi.gitlab.GitLabFlowRegistryClient",
        "api_url_key": "GitLab API URL",
        "api_url_default": "https://gitlab.com/",
        "owner_key": "Repository Namespace",
        "auth_type_key": "Authentication Type",
        "auth_type_value": "ACCESS_TOKEN",
        "token_key": "Access Token",
    },
    "ado": {
        "reg_type": "org.apache.nifi.azure.devops.AzureDevOpsFlowRegistryClient",
        "api_url_key": "Azure DevOps API URL",
        "api_url_default": "https://dev.azure.com",
        "owner_key": "Organization",
        "oauth2_provider_key": "OAuth2 Access Token Provider",
        "web_client_key": "Web Client Service",
    },
}


def ensure_registry(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    token: Optional[str] = None,
    repo: Optional[str] = None,
    client_name: Optional[str] = None,
    provider: Optional[str] = None,
    api_url: Optional[str] = None,
    default_branch: Optional[str] = None,
    repository_path: Optional[str] = None,
    project: Optional[str] = None,
    oauth2_provider_id: Optional[str] = None,
    web_client_id: Optional[str] = None,
) -> dict:
    """
    Ensure a Git Flow Registry Client exists with the desired configuration.

    Args:
        token: Personal Access Token. Env: GH_REGISTRY_TOKEN or GL_REGISTRY_TOKEN.
            Not used for the 'ado' provider (ADO uses OAuth2 controller services).
        repo: Repository in owner/repo format. Env: NIFI_REGISTRY_REPO
        client_name: Registry client name. Env: NIFI_REGISTRY_CLIENT_NAME
        provider: "github", "gitlab", or "ado". Env: NIFI_REGISTRY_PROVIDER
        api_url: API URL override. Env: NIFI_REGISTRY_API_URL
        default_branch: Default branch. Env: NIFI_REGISTRY_BRANCH
        repository_path: Path in repo. Env: NIFI_REPOSITORY_PATH
        project: Azure DevOps project name (ado only). Env: NIFI_REGISTRY_PROJECT
        oauth2_provider_id: ID of a pre-configured StandardOauth2AccessTokenProvider
            controller service (ado only). Env: NIFI_ADO_OAUTH2_PROVIDER_ID
        web_client_id: ID of a pre-configured StandardWebClientServiceProvider
            controller service (ado only, optional). Env: NIFI_ADO_WEB_CLIENT_ID

    Returns:
        dict with registry_client_id and registry_client_name

    Raises:
        ValueError: Missing required parameters
        Exception: NiFi API errors

    Note:
        The 'ado' provider uses AzureDevOpsFlowRegistryClient which authenticates via
        a Service Principal OAuth2 flow. The OAuth2 controller service must be created
        and enabled in NiFi before calling this function. No PAT token is needed.
    """
    # Resolve from env vars with defaults
    # pylint: disable=too-many-locals,too-many-branches
    # Determine provider first so we can select the correct token env var
    provider = (provider or os.environ.get("NIFI_REGISTRY_PROVIDER") or "github").lower()

    # Select token based on provider - check provider-specific env var first
    # ADO does not use a direct token; token is ignored for that provider
    if not token:
        if provider == "gitlab":
            token = os.environ.get("GL_REGISTRY_TOKEN") or os.environ.get("GH_REGISTRY_TOKEN")
        elif provider == "ado":
            token = os.environ.get("ADO_REGISTRY_TOKEN")
        else:
            token = os.environ.get("GH_REGISTRY_TOKEN") or os.environ.get("GL_REGISTRY_TOKEN")

    repo = repo or os.environ.get("NIFI_REGISTRY_REPO")
    client_name = client_name or os.environ.get("NIFI_REGISTRY_CLIENT_NAME")
    api_url = api_url or os.environ.get("NIFI_REGISTRY_API_URL")
    default_branch = default_branch or os.environ.get("NIFI_REGISTRY_BRANCH") or "main"
    repository_path = repository_path or os.environ.get("NIFI_REPOSITORY_PATH") or ""
    project = project or os.environ.get("NIFI_REGISTRY_PROJECT")
    oauth2_provider_id = oauth2_provider_id or os.environ.get("NIFI_ADO_OAUTH2_PROVIDER_ID")
    web_client_id = web_client_id or os.environ.get("NIFI_ADO_WEB_CLIENT_ID")

    # Validate
    if provider not in PROVIDERS:
        raise ValueError(f"Invalid provider '{provider}'. Must be one of: {', '.join(PROVIDERS)}")
    if provider != "ado" and not token:
        raise ValueError("token is required (or set GH_REGISTRY_TOKEN / GL_REGISTRY_TOKEN)")
    if not repo or "/" not in repo:
        raise ValueError("repo must be in owner/repo format (or set NIFI_REGISTRY_REPO)")
    if provider == "ado":
        if not project:
            raise ValueError("project is required for ado provider (or set NIFI_REGISTRY_PROJECT)")
        if not oauth2_provider_id:
            raise ValueError(
                "oauth2_provider_id is required for ado provider"
                " (or set NIFI_ADO_OAUTH2_PROVIDER_ID)"
            )

    # Default client name based on provider
    if not client_name:
        client_name = f"{'AzureDevOps' if provider == 'ado' else provider.title()}-FlowRegistry"

    config = PROVIDERS[provider]
    repo_owner, repo_name = repo.split("/", 1)

    log.info(
        "Ensuring %s registry client '%s' for %s/%s", provider, client_name, repo_owner, repo_name
    )

    # Build properties
    resolved_api_url = api_url or config["api_url_default"]

    if provider == "ado":
        properties = {
            config["api_url_key"]: resolved_api_url,
            config["owner_key"]: repo_owner,
            "Project": project,
            "Repository Name": repo_name,
            "Authentication Strategy": "SERVICE_PRINCIPAL",
            config["oauth2_provider_key"]: oauth2_provider_id,
            "Default Branch": default_branch,
            "Parameter Context Values": "IGNORE_CHANGES",
        }
        if web_client_id:
            properties[config["web_client_key"]] = web_client_id
    else:
        properties = {
            config["api_url_key"]: resolved_api_url,
            config["owner_key"]: repo_owner,
            "Repository Name": repo_name,
            config["auth_type_key"]: config["auth_type_value"],
            config["token_key"]: token,
            "Default Branch": default_branch,
            "Parameter Context Values": "IGNORE_CHANGES",
        }

    if repository_path:
        properties["Repository Path"] = repository_path

    log.debug("API URL: %s", resolved_api_url)
    log.debug("Default branch: %s", default_branch)
    if repository_path:
        log.debug("Repository path: %s", repository_path)

    # Create/update registry client
    log.debug("Calling ensure_registry_client with reg_type=%s", config["reg_type"])
    client = nipyapi.versioning.ensure_registry_client(
        name=client_name,
        reg_type=config["reg_type"],
        description=f"{'Azure DevOps' if provider == 'ado' else provider.title()} Registry Client"
        f" for {repo_owner}/{repo_name}",
        properties=properties,
    )

    log.info("Registry client ready: %s (ID: %s)", client.component.name, client.id)
    log.debug("Validation status: %s", client.component.validation_status)

    return {
        "registry_client_id": client.id,
        "registry_client_name": client.component.name,
    }
