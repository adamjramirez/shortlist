"""AWW client — fetch published slices from the AWW cloud server.

Used by the pipeline to pull a user's networking slice as fit_context
when an aww_node_id is configured in their profile.
"""
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

AWW_SERVER_URL = "https://aww-server.fly.dev"
TIMEOUT = 10  # seconds


def pull_networking_slice(node_id: str, base_url: str = AWW_SERVER_URL) -> Optional[str]:
    """Fetch the networking slice for a node from the AWW server.

    Returns the markdown content, or None if not found / error.
    Never raises — pipeline should fall back to stored fit_context.
    """
    if not node_id:
        return None

    url = f"{base_url}/api/nodes/{node_id}/slices/networking"
    try:
        resp = httpx.get(url, timeout=TIMEOUT)
        if resp.status_code == 200:
            content = resp.text.strip()
            if len(content) > 100:  # sanity check — reject empty/tiny responses
                logger.info(f"AWW: pulled networking slice for {node_id} ({len(content)} chars)")
                return content
            logger.warning(f"AWW: networking slice too small ({len(content)} chars), ignoring")
            return None
        elif resp.status_code == 404:
            logger.info(f"AWW: no networking slice for node {node_id}")
            return None
        else:
            logger.warning(f"AWW: unexpected status {resp.status_code} for {node_id}")
            return None
    except Exception as e:
        logger.warning(f"AWW: failed to pull slice for {node_id}: {e}")
        return None
