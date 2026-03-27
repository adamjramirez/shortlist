"""AWW client — fetch published slices from the AWW cloud server.

Used by the pipeline to pull a user's networking slice as fit_context
when an aww_node_id is configured in their profile.

Supports both public slices (anonymous GET) and permissioned slices
(authenticated pull with grant credentials + client-side decryption).
"""
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

AWW_SERVER_URL = "https://aww.addslift.com"
TIMEOUT = 10  # seconds


def pull_networking_slice(node_id: str, base_url: str = AWW_SERVER_URL) -> Optional[str]:
    """Fetch the networking slice for a node from the AWW server.

    Tries anonymous pull first. If 403 (permissioned), attempts authenticated
    pull using grant credentials from env vars.

    Fallback chain:
      1. Anonymous GET (public slices)
      2. Authenticated GET + decrypt (permissioned slices, if grant available)
      3. None (caller falls back to stored fit_context)

    Returns the markdown content, or None if not found / error.
    Never raises — pipeline should fall back to stored fit_context.
    """
    if not node_id:
        return None

    url = f"{base_url}/api/nodes/{node_id}/slices/networking"

    try:
        # Try anonymous pull first
        resp = httpx.get(url, timeout=TIMEOUT)

        if resp.status_code == 200:
            # Check if it's JSON (permissioned response that slipped through)
            # or plain markdown (public)
            content_type = resp.headers.get("content-type", "")
            if "text/markdown" in content_type:
                content = resp.text.strip()
                if len(content) > 100:
                    logger.info(f"AWW: pulled public networking slice for {node_id} ({len(content)} chars)")
                    return content
                logger.warning(f"AWW: networking slice too small ({len(content)} chars), ignoring")
                return None

        if resp.status_code == 403:
            # Permissioned — try authenticated pull
            return _pull_permissioned(node_id, base_url)

        if resp.status_code == 404:
            logger.info(f"AWW: no networking slice for node {node_id}")
            return None

        logger.warning(f"AWW: unexpected status {resp.status_code} for {node_id}")
        return None

    except Exception as e:
        logger.warning(f"AWW: failed to pull slice for {node_id}: {e}")
        return None


def _pull_permissioned(node_id: str, base_url: str) -> Optional[str]:
    """Attempt authenticated pull of a permissioned slice.

    Loads grant credentials from AWW_GRANT_JSON or AWW_GRANT_FILE env vars,
    signs the request, decrypts the response, and verifies the signature.

    Returns plaintext content or None.
    """
    try:
        from shortlist.aww_crypto import load_grant, sign_pull_request, decrypt_slice, verify_signature

        grant = load_grant()
        if not grant:
            logger.info("AWW: permissioned slice but no grant credentials available")
            return None

        # Verify grant is for the right node/slice
        if grant["node_id"] != node_id:
            logger.warning(f"AWW: grant node_id mismatch ({grant['node_id']} != {node_id})")
            return None
        if grant["slice_name"] != "networking":
            logger.warning(f"AWW: grant slice_name mismatch ({grant['slice_name']} != networking)")
            return None

        # Sign request
        pub_b64, sig_b64, timestamp = sign_pull_request(
            grant["private_key"], node_id, "networking"
        )

        # Authenticated pull
        url = f"{base_url}/api/nodes/{node_id}/slices/networking"
        headers = {
            "X-AWW-Public-Key": pub_b64,
            "X-AWW-Signature": sig_b64,
            "X-AWW-Timestamp": timestamp,
        }
        resp = httpx.get(url, headers=headers, timeout=TIMEOUT)

        if resp.status_code != 200:
            logger.warning(f"AWW: authenticated pull failed with {resp.status_code}")
            return None

        data = resp.json()

        # Decrypt
        plaintext = decrypt_slice(
            encrypted_content_b64=data["encrypted_content"],
            key_wrap_b64=data["key_wrap"],
            consumer_private_key_b64=grant["private_key"],
            owner_public_key_pinned_b64=grant["owner_public_key"],
            owner_public_key_from_server_b64=data["owner_public_key"],
        )

        # Verify signature
        if data.get("signature"):
            if not verify_signature(plaintext, data["signature"], grant["owner_public_key"]):
                logger.warning("AWW: signature verification failed — content may be tampered")
                return None

        if len(plaintext) > 100:
            logger.info(f"AWW: decrypted permissioned networking slice for {node_id} ({len(plaintext)} chars)")
            return plaintext

        logger.warning(f"AWW: decrypted slice too small ({len(plaintext)} chars), ignoring")
        return None

    except ValueError as e:
        logger.error(f"AWW: crypto error — {e}")
        return None
    except Exception as e:
        logger.warning(f"AWW: permissioned pull failed: {e}")
        return None
