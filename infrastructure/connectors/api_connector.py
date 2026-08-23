"""
REST API Connector for DataOS (Rule #36).
Standardized interface for reading data from HTTP/REST APIs.
Supports paginated fetching, authentication, and automatic DataObject wrapping.
"""

from __future__ import annotations
import json
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from core.object.model import DataObject, ObjectType
from ..connectors.base import BaseConnector


class APIConnector(BaseConnector):
    """
    Connects to REST/HTTP APIs and ingests JSON responses as DataObjects.
    Config:
        base_url: str (e.g. "https://api.example.com/v1")
        auth_type: "none" | "bearer" | "api_key" | "basic"
        auth_token: str (token value for bearer/api_key)
        auth_header: str (header name for api_key, default "X-API-Key")
        headers: dict (additional default headers)
        timeout: int (request timeout in seconds, default 30)
        pagination: "none" | "offset" | "cursor" | "link"
        page_size: int (default 100)
        max_pages: int (default 10)
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.base_url = config.get("base_url", "").rstrip("/")
        self.auth_type = config.get("auth_type", "none")
        self.auth_token = config.get("auth_token", "")
        self.auth_header = config.get("auth_header", "X-API-Key")
        self.extra_headers = config.get("headers", {})
        self.timeout = config.get("timeout", 30)
        self.pagination = config.get("pagination", "none")
        self.page_size = config.get("page_size", 100)
        self.max_pages = config.get("max_pages", 10)
        self._session = None

    def _get_headers(self) -> Dict[str, str]:
        """Build request headers with authentication."""
        headers = {"Accept": "application/json", **self.extra_headers}
        if self.auth_type == "bearer" and self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        elif self.auth_type == "api_key" and self.auth_token:
            headers[self.auth_header] = self.auth_token
        elif self.auth_type == "basic" and self.auth_token:
            import base64
            headers["Authorization"] = f"Basic {base64.b64encode(self.auth_token.encode()).decode()}"
        return headers

    def _get_session(self):
        """Get or create HTTP session."""
        if self._session:
            return self._session
        try:
            import requests
            self._session = requests.Session()
            self._session.headers.update(self._get_headers())
            self._session.timeout = self.timeout
        except ImportError:
            raise ImportError("requests library is required for API connectors. Install with: pip install requests")
        return self._session

    def test_connection(self) -> bool:
        """Test API reachability with a GET request to base_url."""
        try:
            session = self._get_session()
            resp = session.get(self.base_url)
            return resp.status_code < 500
        except Exception as e:
            print(f"[APIConnector:{self.name}] Connection test failed: {e}")
            return False

    def list_resources(self) -> List[Dict[str, Any]]:
        """
        List available API endpoints/resources.
        Returns the base URL and configured endpoints as resources.
        """
        return [
            {"id": self.base_url, "type": "api_endpoint", "name": self.base_url, "method": "GET"},
        ]

    def read_resource(self, resource_id: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Fetch data from an API endpoint.
        resource_id is the full URL or path appended to base_url.
        """
        session = self._get_session()
        url = resource_id if resource_id.startswith("http") else f"{self.base_url}/{resource_id.lstrip('/')}"
        all_results = []

        if self.pagination == "none":
            resp = session.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return {"resource_id": resource_id, "data": data, "status_code": resp.status_code}

        # Paginated fetching
        current_url = url
        current_params = dict(params or {})
        page = 0
        while page < self.max_pages:
            if self.pagination == "offset":
                current_params["offset"] = page * self.page_size
                current_params["limit"] = self.page_size
            elif self.pagination == "cursor" and page > 0:
                current_params["cursor"] = next_cursor

            resp = session.get(current_url, params=current_params)
            resp.raise_for_status()
            page_data = resp.json()

            if isinstance(page_data, list):
                all_results.extend(page_data)
            elif isinstance(page_data, dict):
                if "results" in page_data:
                    all_results.extend(page_data["results"])
                    next_cursor = page_data.get("next_cursor") or page_data.get("next")
                    if not next_cursor:
                        break
                    current_url = next_cursor if next_cursor.startswith("http") else f"{self.base_url}/{next_cursor}"
                elif "data" in page_data:
                    all_results.extend(page_data["data"])
                    break
                else:
                    all_results.append(page_data)
                    break
            else:
                all_results.append(page_data)
                break

            if self.pagination == "link":
                next_link = resp.headers.get("Link", "")
                if 'rel="next"' not in next_link:
                    break
                for part in next_link.split(","):
                    if 'rel="next"' in part:
                        current_url = part.split(";")[0].strip("<>")
                        break

            page += 1
            if self.pagination == "offset" and len(page_data) < self.page_size:
                break

        return {"resource_id": resource_id, "data": all_results, "total_fetched": len(all_results)}

    def read_resource_as_object(self, resource_id: str, params: Optional[Dict[str, Any]] = None) -> DataObject:
        """Fetch API data and wrap as a DataObject."""
        result = self.read_resource(resource_id, params=params)
        data = result.get("data", result)

        content_hash = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16]

        return DataObject(
            type=ObjectType.DATASET.value,
            schema="api_response.v1",
            properties={
                "source_connector": self.name,
                "endpoint": resource_id,
                "base_url": self.base_url,
                "total_items": len(data) if isinstance(data, list) else 1,
                "content_hash": content_hash,
            },
            content=data,
            source=f"connector://{self.name}/{resource_id}",
        )

    def fetch_all_pages(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Convenience method to fetch all pages of a paginated endpoint."""
        result = self.read_resource(endpoint, params=params)
        data = result.get("data", [])
        return data if isinstance(data, list) else [data]

    def close(self) -> None:
        """Close the HTTP session."""
        if self._session:
            self._session.close()
            self._session = None
