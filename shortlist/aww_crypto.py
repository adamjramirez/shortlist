"""AWW crypto — decrypt permissioned slices from AWW server.

Uses PyNaCl for nacl/secretbox (content decryption) and nacl/box (key unwrapping),
matching the Go server's encryption. Ed25519 signing for authenticated pull requests.

Grant credentials come from either:
  - AWW_GRANT_JSON env var (Fly.io secrets — JSON string)
  - AWW_GRANT_FILE env var (local — path to grant .key file)
"""
import base64
import json
import os
import time
from typing import Optional, Tuple

import nacl.public
import nacl.secret
import nacl.signing
import nacl.utils


def load_grant(source: Optional[str] = None) -> Optional[dict]:
    """Load grant credentials from env or explicit source.

    Tries in order:
      1. source argument (JSON string or file path)
      2. AWW_GRANT_JSON env var (JSON string)
      3. AWW_GRANT_FILE env var (file path)

    Returns dict with: private_key, owner_public_key, node_id, slice_name, server_url
    Or None if no grant is available.
    """
    raw = None

    if source:
        if os.path.exists(source):
            raw = open(source).read()
        else:
            raw = source
    else:
        raw = os.environ.get("AWW_GRANT_JSON")
        if not raw:
            path = os.environ.get("AWW_GRANT_FILE")
            if path and os.path.exists(path):
                raw = open(path).read()

    if not raw:
        return None

    try:
        grant = json.loads(raw)
        # Validate required fields
        for field in ("private_key", "owner_public_key", "node_id", "slice_name", "server_url"):
            if field not in grant:
                return None
        return grant
    except (json.JSONDecodeError, TypeError):
        return None


def sign_pull_request(
    private_key_b64: str, node_id: str, slice_name: str
) -> Tuple[str, str, str]:
    """Sign an authenticated pull request.

    Args:
        private_key_b64: Base64-encoded Ed25519 private key (64 bytes)
        node_id: The node ID to pull from
        slice_name: The slice name to pull

    Returns:
        (public_key_b64, signature_b64, timestamp) for request headers
    """
    priv_bytes = base64.b64decode(private_key_b64)
    signing_key = nacl.signing.SigningKey(seed=priv_bytes[:32])
    verify_key = signing_key.verify_key

    timestamp = str(int(time.time()))
    message = f"GET {node_id}/{slice_name} {timestamp}"

    signed = signing_key.sign(message.encode())
    signature = signed.signature

    pub_b64 = base64.b64encode(verify_key.encode()).decode()
    sig_b64 = base64.b64encode(signature).decode()

    return pub_b64, sig_b64, timestamp


def decrypt_slice(
    encrypted_content_b64: str,
    key_wrap_b64: str,
    consumer_private_key_b64: str,
    owner_public_key_pinned_b64: str,
    owner_public_key_from_server_b64: str,
) -> str:
    """Decrypt a permissioned slice.

    1. Assert owner public key matches pinned key (from grant file)
    2. Convert Ed25519 keys to X25519 for nacl/box
    3. Unwrap content key using nacl/box
    4. Decrypt content using nacl/secretbox

    Args:
        encrypted_content_b64: Base64-encoded encrypted content (nonce + ciphertext)
        key_wrap_b64: Base64-encoded key wrap (nonce + box-encrypted content key)
        consumer_private_key_b64: Base64-encoded Ed25519 private key (64 bytes)
        owner_public_key_pinned_b64: From grant file (trusted)
        owner_public_key_from_server_b64: From server response (untrusted)

    Returns:
        Decrypted plaintext content

    Raises:
        ValueError: Owner key mismatch (possible server compromise) or decryption failure
    """
    # Pin check: abort if server claims a different owner key
    if owner_public_key_from_server_b64 != owner_public_key_pinned_b64:
        raise ValueError(
            "Owner public key mismatch — possible server compromise. "
            f"Pinned: {owner_public_key_pinned_b64[:20]}..., "
            f"Server: {owner_public_key_from_server_b64[:20]}..."
        )

    # Decode
    encrypted_content = base64.b64decode(encrypted_content_b64)
    key_wrap = base64.b64decode(key_wrap_b64)
    consumer_priv_bytes = base64.b64decode(consumer_private_key_b64)
    owner_pub_bytes = base64.b64decode(owner_public_key_pinned_b64)

    # Convert Ed25519 → X25519 for nacl/box key agreement
    # Consumer private: Ed25519 signing key → X25519 private key
    consumer_signing_key = nacl.signing.SigningKey(seed=consumer_priv_bytes[:32])
    consumer_x25519_priv = consumer_signing_key.to_curve25519_private_key()

    # Owner public: Ed25519 verify key → X25519 public key
    owner_verify_key = nacl.signing.VerifyKey(owner_pub_bytes)
    owner_x25519_pub = owner_verify_key.to_curve25519_public_key()

    # Unwrap content key using nacl/box
    # Format: nonce (24 bytes) || box-encrypted content key
    nonce_size = nacl.public.Box.NONCE_SIZE  # 24
    if len(key_wrap) < nonce_size + 16:  # 16 = Poly1305 tag
        raise ValueError(f"Key wrap too short ({len(key_wrap)} bytes)")

    box = nacl.public.Box(consumer_x25519_priv, owner_x25519_pub)
    wrap_nonce = key_wrap[:nonce_size]
    wrap_ciphertext = key_wrap[nonce_size:]
    content_key = box.decrypt(wrap_ciphertext, wrap_nonce)

    if len(content_key) != 32:
        raise ValueError(f"Unexpected content key size: {len(content_key)}")

    # Decrypt content using nacl/secretbox
    # Format: nonce (24 bytes) || secretbox-encrypted content
    if len(encrypted_content) < 24 + 16:
        raise ValueError(f"Encrypted content too short ({len(encrypted_content)} bytes)")

    secret_box = nacl.secret.SecretBox(content_key)
    content_nonce = encrypted_content[:24]
    content_ciphertext = encrypted_content[24:]
    plaintext = secret_box.decrypt(content_ciphertext, content_nonce)

    return plaintext.decode("utf-8")


def verify_signature(
    plaintext: str, signature_b64: str, owner_public_key_b64: str
) -> bool:
    """Verify the owner's Ed25519 signature over plaintext.

    Args:
        plaintext: The decrypted content
        signature_b64: Base64-encoded Ed25519 signature
        owner_public_key_b64: Base64-encoded Ed25519 public key (from grant file)

    Returns:
        True if signature is valid, False otherwise
    """
    try:
        sig_bytes = base64.b64decode(signature_b64)
        pub_bytes = base64.b64decode(owner_public_key_b64)
        verify_key = nacl.signing.VerifyKey(pub_bytes)
        # nacl.signing expects signature + message concatenated
        verify_key.verify(plaintext.encode(), sig_bytes)
        return True
    except Exception:
        return False
