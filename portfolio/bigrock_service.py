"""
BigRock DNS Service Integration for Photographer Portfolio Subdomains.
Automates A-record provisioning for subdomains (e.g. mridhul.exshare.ai)
via the BigRock / LogicBoxes / ResellerClub HTTP API (httpapi.com).
"""

import logging
import requests
from typing import Optional, Dict, Any, Tuple, List
from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom Exception Hierarchy
# ---------------------------------------------------------------------------

class BigRockDNSException(Exception):
    """Base exception for BigRock DNS operations."""
    def __init__(self, message: str, code: str = None, status_code: int = None):
        super().__init__(message)
        self.message = message
        self.code = code or "BIGROCK_ERROR"
        self.status_code = status_code


class BigRockAuthError(BigRockDNSException):
    """Authentication failure or IP not whitelisted in BigRock panel (non-retriable)."""
    def __init__(self, message: str = "BigRock API authentication failed. Verify auth-userid, api-key, and IP whitelist."):
        super().__init__(message, code="BIGROCK_AUTH_ERROR", status_code=403)


class BigRockValidationError(BigRockDNSException):
    """Invalid parameter or domain payload format (non-retriable)."""
    def __init__(self, message: str = "BigRock rejected DNS record payload format."):
        super().__init__(message, code="BIGROCK_VALIDATION_ERROR", status_code=400)


class BigRockConflictError(BigRockDNSException):
    """Conflicting DNS record already exists on BigRock (non-retriable)."""
    def __init__(self, message: str = "A conflicting DNS record already exists in BigRock for this subdomain."):
        super().__init__(message, code="BIGROCK_CONFLICT_ERROR", status_code=409)


class BigRockDomainNotFoundError(BigRockDNSException):
    """Domain not found or DNS service not active in BigRock account (non-retriable)."""
    def __init__(self, message: str = "Domain not found in BigRock account or DNS service is inactive."):
        super().__init__(message, code="BIGROCK_DOMAIN_NOT_FOUND", status_code=404)


class BigRockRateLimitError(BigRockDNSException):
    """Rate limit exceeded (retriable with exponential backoff)."""
    def __init__(self, message: str = "BigRock API rate limit exceeded."):
        super().__init__(message, code="BIGROCK_RATE_LIMIT", status_code=429)


class BigRockServerError(BigRockDNSException):
    """Upstream 5xx or network transport error (retriable with backoff)."""
    def __init__(self, message: str = "BigRock API upstream server error."):
        super().__init__(message, code="BIGROCK_SERVER_ERROR", status_code=500)


# Aliases for backward compatibility
GoDaddyDNSException = BigRockDNSException
GoDaddyAuthError = BigRockAuthError
GoDaddyValidationError = BigRockValidationError
GoDaddyConflictError = BigRockConflictError
GoDaddyRateLimitError = BigRockRateLimitError
GoDaddyServerError = BigRockServerError


# ---------------------------------------------------------------------------
# BigRock DNS Client
# ---------------------------------------------------------------------------

class BigRockDNSClient:
    """
    HTTP Client for managing BigRock DNS records.
    API endpoints:
      - Search: GET  https://httpapi.com/api/dns/manage/search-records.json
      - Add:    POST https://httpapi.com/api/dns/manage/add-ipv4-record.json
      - Modify: POST https://httpapi.com/api/dns/manage/modify-ipv4-record.json
      - Delete: POST https://httpapi.com/api/dns/manage/delete-ipv4-record.json
    """

    PRODUCTION_URL = "https://httpapi.com/api/dns/manage"
    TEST_URL = "https://test.httpapi.com/api/dns/manage"

    def __init__(
        self,
        auth_userid: Optional[str] = None,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        server_ip: Optional[str] = None,
        environment: str = "production",
        timeout: int = 15
    ):
        self.auth_userid = str(
            auth_userid
            or getattr(settings, 'BIGROCK_AUTH_USER_ID', '')
            or getattr(settings, 'BIGROCK_USER_ID', '')
        ).strip()
        self.api_key = str(
            api_key
            or getattr(settings, 'BIGROCK_API_KEY', '')
            or getattr(settings, 'GODADDY_API_KEY', '')
        ).strip()
        self.domain = (
            domain
            or getattr(settings, 'PORTFOLIO_DOMAIN', '')
            or getattr(settings, 'PORTFOLIO_BASE_DOMAIN', 'exshare.ai')
        ).strip().lower()
        self.server_ip = (
            server_ip
            or getattr(settings, 'PORTFOLIO_SERVER_IP', '31.97.232.245')
        ).strip()
        self.environment = environment.lower()
        self.timeout = timeout

        self.base_url = self.TEST_URL if self.environment in ('test', 'ote', 'sandbox') else self.PRODUCTION_URL

    def _get_auth_params(self) -> Dict[str, str]:
        """Returns required authentication query/body params for BigRock."""
        if not self.auth_userid or not self.api_key:
            raise BigRockAuthError("Missing BigRock API credentials (BIGROCK_AUTH_USER_ID / BIGROCK_API_KEY).")
        return {
            "auth-userid": self.auth_userid,
            "api-key": self.api_key,
        }

    def _dispatch(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None) -> Any:
        """
        Executes HTTP requests to BigRock API with unified error handling.
        """
        url = f"{self.base_url}/{endpoint}"
        query_params = self._get_auth_params()
        if params:
            query_params.update(params)

        post_data = data or {}

        try:
            resp = requests.request(
                method=method,
                url=url,
                params=query_params if method == 'GET' else None,
                data=query_params if method == 'POST' and not post_data else post_data,
                timeout=self.timeout,
                headers={"Accept": "application/json"}
            )
            # If POST and we had post_data, include auth in post_data
            if method == 'POST':
                all_post_data = {**query_params, **post_data}
                resp = requests.post(
                    url=url,
                    data=all_post_data,
                    timeout=self.timeout,
                    headers={"Accept": "application/json"}
                )
        except requests.exceptions.Timeout:
            logger.warning(f"BigRock API request timed out after {self.timeout}s: {endpoint}")
            raise BigRockServerError(f"BigRock API connection timed out ({self.timeout}s).")
        except requests.exceptions.ConnectionError as ce:
            logger.error(f"BigRock API network transport error: {str(ce)}")
            raise BigRockServerError("Network connection failure communicating with BigRock API.")
        except Exception as e:
            logger.error(f"Unexpected request failure communicating with BigRock: {str(e)}")
            raise BigRockServerError(f"Unexpected communication error: {str(e)}")

        status_code = resp.status_code

        # Attempt to parse response JSON or text
        parsed_body = None
        try:
            parsed_body = resp.json()
        except Exception:
            parsed_body = resp.text.strip()

        # Check for HTTP or API level error responses
        if status_code in (401, 403):
            err_msg = self._extract_error_message(parsed_body) or "Invalid credentials or IP not whitelisted in BigRock panel."
            raise BigRockAuthError(err_msg)

        if status_code == 429:
            raise BigRockRateLimitError("BigRock API rate limit exceeded.")

        if status_code >= 500:
            raise BigRockServerError(f"BigRock API server error (HTTP {status_code}).")

        # BigRock often returns 200 OK with {"status": "ERROR", "message": "..."}
        if isinstance(parsed_body, dict):
            status_val = str(parsed_body.get('status', '')).upper()
            if status_val in ('ERROR', 'FAILED'):
                err_msg = self._extract_error_message(parsed_body)
                err_lower = err_msg.lower()

                if any(w in err_lower for w in ('ip', 'whitelist', 'not allowed', 'authentication failed', 'auth-userid', 'api-key', 'unauthorized', 'permission')):
                    raise BigRockAuthError(f"BigRock access rejected: {err_msg}")
                if 'already exist' in err_lower or 'duplicate' in err_lower:
                    raise BigRockConflictError(f"Record conflict: {err_msg}")
                if 'not found' in err_lower or 'domain does not exist' in err_lower or 'inactive' in err_lower:
                    raise BigRockDomainNotFoundError(f"Domain lookup failed: {err_msg}")
                if 'rate' in err_lower or 'limit' in err_lower:
                    raise BigRockRateLimitError(err_msg)
                
                raise BigRockValidationError(f"BigRock rejected operation: {err_msg}")

        return parsed_body

    def _extract_error_message(self, body: Any) -> str:
        if isinstance(body, dict):
            return body.get('message') or body.get('error') or body.get('error_message') or str(body)
        return str(body or "")

    def search_records(self, host: Optional[str] = None, record_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Searches existing DNS records for the domain via search-records.json.
        Returns a list of record dicts.
        """
        params = {
            "domain-name": self.domain,
            "no-of-records": 50,
            "page-no": 1,
        }
        if host:
            params["host"] = host
        if record_type:
            params["type"] = record_type

        try:
            res = self._dispatch("GET", "search-records.json", params=params)
        except BigRockDomainNotFoundError:
            return []
        except Exception as e:
            logger.warning(f"Failed to query BigRock DNS records for {self.domain}: {str(e)}")
            raise

        records: List[Dict[str, Any]] = []
        if isinstance(res, dict):
            for k, v in res.items():
                if k.isdigit() and isinstance(v, dict):
                    records.append(v)
        elif isinstance(res, list):
            records = res

        return records

    def check_subdomain_conflict(self, subdomain: str) -> Tuple[bool, Optional[str]]:
        """
        Verifies if an existing record conflicts with the requested subdomain.
        Returns:
          (has_conflict, reason)
          - If exact matching A record exists pointing to self.server_ip: (False, "already_configured")
          - If conflicting CNAME or external A record: (True, "conflicting_record_found")
          - If no records exist: (False, None)
        """
        clean_sub = subdomain.strip().lower()

        try:
            existing = self.search_records(host=clean_sub)
        except BigRockDNSException:
            raise
        except Exception as e:
            logger.warning(f"Could not pre-check BigRock records for {clean_sub}: {str(e)}")
            return False, None

        for rec in existing:
            rec_host = str(rec.get('host', '')).strip().lower()
            rec_type = str(rec.get('type', '')).strip().upper()
            rec_val = str(rec.get('value', '')).strip()

            # Exact match check
            if rec_host == clean_sub:
                if rec_type == 'CNAME':
                    return True, f"Conflicting CNAME record pointing to '{rec_val}' already exists."
                if rec_type == 'A':
                    if rec_val == self.server_ip:
                        # Idempotent match: already configured correctly
                        return False, "already_configured"
                    else:
                        return True, f"Conflicting A-record already points to an external IP '{rec_val}'."

        return False, None

    def provision_portfolio_a_record(self, subdomain: str, ttl: int = 14400) -> Dict[str, Any]:
        """
        Provisions an A-record on BigRock pointing {subdomain}.{domain} to self.server_ip.
        - Pre-checks existing records.
        - Reuses matching existing A-records idempotently without duplicate writes.
        - Calls add-ipv4-record.json.
        """
        clean_sub = subdomain.strip().lower()

        # Step 1: Pre-check conflict
        has_conflict, reason = self.check_subdomain_conflict(clean_sub)
        if has_conflict:
            raise BigRockConflictError(reason or f"Conflicting DNS record exists on BigRock for '{clean_sub}'.")

        if reason == "already_configured":
            logger.info(f"BigRock A-record for '{clean_sub}.{self.domain}' -> '{self.server_ip}' already configured. Reusing.")
            return {
                "status": "success",
                "action": "reused",
                "subdomain": clean_sub,
                "domain": self.domain,
                "name": clean_sub,
                "type": "A",
                "data": self.server_ip,
                "ttl": ttl,
            }

        # Step 2: Add IPv4 record
        payload = {
            "domain-name": self.domain,
            "host": clean_sub,
            "value": self.server_ip,
            "ttl": ttl,
        }

        logger.info(f"Adding BigRock A-record: host='{clean_sub}', domain='{self.domain}', value='{self.server_ip}'")
        res = self._dispatch("POST", "add-ipv4-record.json", data=payload)

        # BigRock returns "Success" or boolean true or {"status": "Success"}
        is_success = False
        if res is True or str(res).strip().lower() in ('success', 'true'):
            is_success = True
        elif isinstance(res, dict) and str(res.get('status', '')).lower() in ('success', 'true'):
            is_success = True

        if not is_success and isinstance(res, dict) and 'error' in res:
            raise BigRockValidationError(f"BigRock rejected record creation: {res.get('error')}")

        return {
            "status": "success",
            "action": "created",
            "subdomain": clean_sub,
            "domain": self.domain,
            "name": clean_sub,
            "type": "A",
            "data": self.server_ip,
            "ttl": ttl,
            "response": res
        }


# ---------------------------------------------------------------------------
# Singleton Factory
# ---------------------------------------------------------------------------

_bigrock_client_instance: Optional[BigRockDNSClient] = None


def get_bigrock_client() -> BigRockDNSClient:
    """Returns a configured BigRock DNS client instance."""
    global _bigrock_client_instance
    if _bigrock_client_instance is None:
        _bigrock_client_instance = BigRockDNSClient(
            auth_userid=getattr(settings, 'BIGROCK_AUTH_USER_ID', '') or getattr(settings, 'BIGROCK_USER_ID', ''),
            api_key=getattr(settings, 'BIGROCK_API_KEY', '') or getattr(settings, 'GODADDY_API_KEY', ''),
            domain=getattr(settings, 'PORTFOLIO_DOMAIN', 'exshare.ai'),
            server_ip=getattr(settings, 'PORTFOLIO_SERVER_IP', '31.97.232.245'),
            environment=getattr(settings, 'BIGROCK_API_ENV', 'production')
        )
    return _bigrock_client_instance


def get_dns_client():
    """Generic DNS client provider (defaults to BigRock)."""
    return get_bigrock_client()


# Alias for backward compatibility
get_godaddy_client = get_bigrock_client
GoDaddyDNSClient = BigRockDNSClient
