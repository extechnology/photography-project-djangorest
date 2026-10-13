"""
GoDaddy DNS Service Integration for Photographer Portfolio Subdomains.
Handles verification, pre-conflict checking, and automated DNS A-record provisioning
via GoDaddy v1 REST API.
"""
import logging
import requests
from typing import Optional, Dict, Any, List, Tuple
from django.conf import settings

logger = logging.getLogger(__name__)


class GoDaddyDNSException(Exception):
    """Base exception for GoDaddy DNS operations."""
    def __init__(self, message: str, code: Optional[str] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.code = code or "GODADDY_ERROR"
        self.status_code = status_code


class GoDaddyAuthError(GoDaddyDNSException):
    """401/403 Authentication or authorization failure (non-retriable)."""
    def __init__(self, message: str = "GoDaddy API authentication failed. Verify API credentials."):
        super().__init__(message, code="GODADDY_AUTH_ERROR", status_code=403)


class GoDaddyValidationError(GoDaddyDNSException):
    """400/422 Validation or malformed payload error (non-retriable)."""
    def __init__(self, message: str = "GoDaddy rejected DNS record payload format."):
        super().__init__(message, code="GODADDY_VALIDATION_ERROR", status_code=400)


class GoDaddyConflictError(GoDaddyDNSException):
    """Record name conflicts with pre-existing CNAME or external A record (non-retriable)."""
    def __init__(self, message: str = "Conflicting DNS record already exists."):
        super().__init__(message, code="GODADDY_CONFLICT_ERROR", status_code=409)


class GoDaddyDomainNotFoundError(GoDaddyDNSException):
    """Domain not found in authenticated GoDaddy account (non-retriable)."""
    def __init__(self, domain: str):
        super().__init__(f"Domain '{domain}' is not managed under this GoDaddy account.", code="DOMAIN_NOT_FOUND", status_code=404)


class GoDaddyRateLimitError(GoDaddyDNSException):
    """429 Rate limit exceeded (retriable with exponential backoff)."""
    def __init__(self, message: str = "GoDaddy API rate limit exceeded."):
        super().__init__(message, code="GODADDY_RATE_LIMIT", status_code=429)


class GoDaddyServerError(GoDaddyDNSException):
    """5xx Server or network communication error (retriable)."""
    def __init__(self, message: str = "GoDaddy DNS service is temporarily unavailable."):
        super().__init__(message, code="GODADDY_SERVER_ERROR", status_code=503)


class GoDaddyDNSClient:
    """
    Client for GoDaddy v1 Domains & DNS Records API.
    API Docs: https://developer.godaddy.com/doc/endpoint/domains
    """

    PRODUCTION_BASE_URL = "https://api.godaddy.com"
    OTE_BASE_URL = "https://api.ote-godaddy.com"

    DEFAULT_CONNECT_TIMEOUT = 5.0
    DEFAULT_READ_TIMEOUT = 10.0

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        domain: Optional[str] = None,
        server_ip: Optional[str] = None,
        env: Optional[str] = None,
        session: Optional[requests.Session] = None
    ):
        self.api_key = (api_key or getattr(settings, 'GODADDY_API_KEY', '')).strip()
        self.api_secret = (api_secret or getattr(settings, 'GODADDY_API_SECRET', '')).strip()
        self.domain = (domain or getattr(settings, 'PORTFOLIO_DOMAIN', getattr(settings, 'PORTFOLIO_BASE_DOMAIN', 'exshare.ai'))).strip().lower()
        self.server_ip = (server_ip or getattr(settings, 'PORTFOLIO_SERVER_IP', '31.97.232.245')).strip()

        env_choice = (env or getattr(settings, 'GODADDY_API_ENV', 'production')).strip().lower()
        self.base_url = self.OTE_BASE_URL if env_choice == 'ote' else self.PRODUCTION_BASE_URL

        self.session = session or requests.Session()

    def _get_headers(self) -> Dict[str, str]:
        if not self.api_key or not self.api_secret:
            raise GoDaddyAuthError("GoDaddy API Key and Secret are not configured in environment.")
        return {
            "Authorization": f"sso-key {self.api_key}:{self.api_secret}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        headers = self._get_headers()
        if 'headers' in kwargs:
            headers.update(kwargs.pop('headers'))

        timeout = kwargs.pop('timeout', (self.DEFAULT_CONNECT_TIMEOUT, self.DEFAULT_READ_TIMEOUT))

        try:
            resp = self.session.request(method, url, headers=headers, timeout=timeout, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.warning(f"Network error communicating with GoDaddy API ({method} {path}): {e}")
            raise GoDaddyServerError("Failed to connect to GoDaddy DNS service (network timeout).") from e
        except requests.RequestException as e:
            logger.warning(f"Unexpected request error communicating with GoDaddy API: {e}")
            raise GoDaddyServerError("DNS provider request error.") from e

        # Handle HTTP Status Codes safely without exposing raw tokens/secrets
        status = resp.status_code
        if status in (200, 204):
            return resp

        # Parse safe error message if returned
        error_msg = ""
        try:
            body = resp.json()
            if isinstance(body, dict):
                error_msg = body.get('message') or body.get('code') or ""
        except Exception:
            pass

        if status in (401, 403):
            logger.error(f"GoDaddy API authentication rejected (HTTP {status}) for domain {self.domain}.")
            raise GoDaddyAuthError(f"GoDaddy API access denied: {error_msg or 'Invalid API credentials.'}")

        if status == 404:
            # Note: 404 when querying specific record just means record does not exist
            return resp

        if status == 409:
            raise GoDaddyConflictError(error_msg or "Conflict detected with existing GoDaddy DNS record.")

        if status == 429:
            logger.warning(f"GoDaddy API rate limited (HTTP 429): {error_msg}")
            raise GoDaddyRateLimitError(error_msg or "GoDaddy rate limit reached. Backing off.")

        if 400 <= status < 500:
            raise GoDaddyValidationError(f"GoDaddy rejected record request (HTTP {status}): {error_msg or 'Validation failure.'}")

        if status >= 500:
            logger.error(f"GoDaddy DNS API server error (HTTP {status}): {error_msg}")
            raise GoDaddyServerError(f"GoDaddy upstream error (HTTP {status}).")

        return resp

    def check_domain_status(self) -> Dict[str, Any]:
        """
        Validates that the target domain exists and is active under this GoDaddy account.
        Endpoint: GET /v1/domains/{domain}
        """
        resp = self._request("GET", f"/v1/domains/{self.domain}")
        if resp.status_code == 404:
            raise GoDaddyDomainNotFoundError(self.domain)
        return resp.json()

    def get_dns_record(self, record_type: str, name: str) -> List[Dict[str, Any]]:
        """
        Retrieves DNS records for a specific type and name.
        Endpoint: GET /v1/domains/{domain}/records/{type}/{name}
        Returns list of matching records, or empty list if 404 (does not exist).
        """
        resp = self._request("GET", f"/v1/domains/{self.domain}/records/{record_type}/{name}")
        if resp.status_code == 404:
            return []
        try:
            data = resp.json()
            return data if isinstance(data, list) else [data]
        except Exception:
            return []

    def check_subdomain_conflict(self, subdomain: str) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Pre-checks existing DNS records before provisioning:
        - Rejects conflicting names (CNAME, or A records pointing to different IPs).
        - Allows exact matching A records pointing to our target server IP.

        Returns (is_conflict, reason, existing_matching_record)
        """
        clean_sub = subdomain.strip().lower()

        # 1. Check for conflicting CNAME
        cname_records = self.get_dns_record("CNAME", clean_sub)
        if cname_records:
            return True, f"A conflicting CNAME record already exists for '{clean_sub}'.", None

        # 2. Check for existing A records
        a_records = self.get_dns_record("A", clean_sub)
        if a_records:
            for rec in a_records:
                data_ip = (rec.get('data') or '').strip()
                if data_ip == self.server_ip:
                    # Exact match pointing to our server -> Safe to reuse!
                    return False, "exact_match", rec
                else:
                    # Points to an external or conflicting IP
                    return True, f"An A record for '{clean_sub}' already exists pointing to an external destination ({data_ip}).", None

        # No records found -> clear to provision
        return False, None, None

    def provision_portfolio_a_record(
        self,
        subdomain: str,
        target_ip: Optional[str] = None,
        ttl: int = 600
    ) -> Dict[str, Any]:
        """
        Provisions or re-verifies an A-record for the photographer subdomain:
        1. Checks for conflicts (existing CNAME or conflicting A record).
        2. If exact matching A record exists, returns existing confirmation immediately.
        3. Invokes PATCH /v1/domains/{domain}/records to create the record without wiping the zone.
        """
        clean_sub = subdomain.strip().lower()
        ip_address = (target_ip or self.server_ip).strip()

        # Step 1: Pre-check for conflicts
        is_conflict, reason, exact_match = self.check_subdomain_conflict(clean_sub)
        if is_conflict:
            raise GoDaddyConflictError(reason or f"Conflicting DNS record exists for '{clean_sub}'.")

        if exact_match and exact_match.get('data') == ip_address:
            logger.info(f"GoDaddy exact matching A record already exists for {clean_sub}.{self.domain} -> {ip_address}.")
            return {
                "action": "reused_existing",
                "domain": self.domain,
                "name": clean_sub,
                "type": "A",
                "data": ip_address,
                "ttl": exact_match.get('ttl', ttl),
                "full_domain": f"{clean_sub}.{self.domain}"
            }

        # Step 2: PATCH /v1/domains/{domain}/records
        payload = [
            {
                "type": "A",
                "name": clean_sub,
                "data": ip_address,
                "ttl": ttl
            }
        ]

        logger.info(f"Provisioning GoDaddy A record: {clean_sub}.{self.domain} -> {ip_address}")
        resp = self._request("PATCH", f"/v1/domains/{self.domain}/records", json=payload)

        return {
            "action": "created",
            "domain": self.domain,
            "name": clean_sub,
            "type": "A",
            "data": ip_address,
            "ttl": ttl,
            "full_domain": f"{clean_sub}.{self.domain}",
            "status_code": resp.status_code
        }


# Global singleton instance provider
def get_godaddy_client() -> GoDaddyDNSClient:
    return GoDaddyDNSClient()
