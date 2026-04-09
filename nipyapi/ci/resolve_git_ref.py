"""
Resolve git refs (tags/branches) to commit SHAs.
"""

import base64
import re
import urllib.parse
from typing import Optional

import requests


def resolve_git_ref(
    ref: Optional[str],
    repo: Optional[str] = None,
    token: Optional[str] = None,
    provider: str = "github",
) -> Optional[str]:
    """
    Resolve a git ref (tag/branch/SHA) to a commit SHA.

    If the ref already looks like a SHA (7-40 hex characters), returns it as-is.
    Otherwise, calls the provider's API to resolve the ref to a SHA.

    Args:
        ref: Tag name, branch name, or commit SHA. If None or empty, returns None.
        repo: Repository path.

            - GitHub: ``owner/repo``
            - GitLab: ``namespace/repo``
            - ADO: ``org/project/repo`` (3 parts required for Azure DevOps REST API)

        token: Personal access token for API access.
            For ADO, provide a PAT (Personal Access Token) stored in
            ``ADO_REGISTRY_TOKEN``.
        provider: Git provider - ``"github"``, ``"gitlab"``, or ``"ado"``
            (default: github).

    Returns:
        Resolved commit SHA, or None if ref was empty.

    Raises:
        ValueError: If the ref cannot be resolved.

    Example::

        >>> resolve_git_ref("v1.0.0", "owner/repo", "ghp_xxx", "github")
        "abc123def456..."
        >>> resolve_git_ref("abc123def456", None, None)  # Already a SHA
        "abc123def456"
        >>> resolve_git_ref("v1.0.0", "myorg/MyProject/myrepo", "pat_xxx", "ado")
        "abc123def456..."
    """
    if not ref:
        return None  # Caller wants latest version

    # Already a SHA (7-40 hex characters) - return as-is
    if re.match(r"^[0-9a-fA-F]{7,40}$", ref):
        return ref

    # Need repo and token to resolve via API
    if not repo:
        raise ValueError(
            f"Cannot resolve git ref '{ref}': repository not specified. "
            "Pass the full SHA or provide repo/token."
        )
    if not token:
        raise ValueError(
            f"Cannot resolve git ref '{ref}': {provider} token not available. "
            "Pass the full SHA or provide a token."
        )

    if provider == "ado":
        return _resolve_ado_ref(ref, repo, token)

    if provider == "gitlab":
        # GitLab API: /projects/:id/repository/commits/:sha
        encoded_repo = urllib.parse.quote(repo, safe="")
        url = f"https://gitlab.com/api/v4/projects/{encoded_repo}/repository/commits/{ref}"
        headers = {"PRIVATE-TOKEN": token}
    else:
        # GitHub API
        url = f"https://api.github.com/repos/{repo}/commits/{ref}"
        headers = {"Authorization": f"Bearer {token}"}

    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code == 404:
        raise ValueError(f"Could not resolve git ref '{ref}' - not found in {repo}")
    resp.raise_for_status()

    sha = resp.json()["id" if provider == "gitlab" else "sha"]
    return sha


def _resolve_ado_ref(ref: str, repo: str, token: str) -> str:
    """
    Resolve a tag or branch ref to a commit SHA using the Azure DevOps REST API.

    Args:
        ref: Tag name or branch name to resolve.
        repo: Repository in ``org/project/repo`` format (3 parts).
        token: PAT (Personal Access Token) for Basic auth.

    Returns:
        Resolved commit SHA.

    Raises:
        ValueError: If repo format is wrong or ref is not found.
    """
    parts = repo.split("/")
    if len(parts) != 3:
        raise ValueError(
            f"For ADO provider, repo must be in 'org/project/repo' format "
            f"(3 parts), got: {repo!r}. "
            "Alternatively, pass a full commit SHA to skip API resolution."
        )
    ado_org, ado_project, ado_repo = parts

    # ADO PAT authentication: Basic base64(":PAT")
    encoded_pat = base64.b64encode(f":{token}".encode()).decode()
    headers = {"Authorization": f"Basic {encoded_pat}"}

    encoded_ref = urllib.parse.quote(ref, safe="")
    base_url = (
        f"https://dev.azure.com/{ado_org}/{ado_project}/_apis/git" f"/repositories/{ado_repo}/refs"
    )

    # Try tags first, then heads (branches)
    for ref_type in ("tags", "heads"):
        url = f"{base_url}?filter={ref_type}/{encoded_ref}&api-version=7.0"
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 404:
            raise ValueError(f"Could not resolve git ref '{ref}' - not found in {repo}")
        resp.raise_for_status()
        items = resp.json().get("value", [])
        if items:
            # peelObjectId is the commit SHA for annotated tags; objectId for lightweight tags
            return items[0].get("peelObjectId") or items[0]["objectId"]

    raise ValueError(f"Could not resolve git ref '{ref}' - not found as tag or branch in {repo}")
