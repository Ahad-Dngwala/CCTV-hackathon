import os
import json
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet
import logging

logger = logging.getLogger(__name__)

# Fetch the encryption key from environment variable.
# Should be a base64-encoded 32-byte key (e.g. Fernet.generate_key().decode())
ENCRYPTION_KEY = os.getenv("VMS_ENCRYPTION_KEY")

_fernet = None
if ENCRYPTION_KEY:
    try:
        _fernet = Fernet(ENCRYPTION_KEY.encode())
    except Exception as e:
        logger.error(f"Failed to initialize Fernet with VMS_ENCRYPTION_KEY: {e}")

def encrypt_config(config_dict: Dict[str, Any]) -> str:
    """Encrypt a dictionary into a JSON string, then Fernet encrypt it if key is available."""
    config_str = json.dumps(config_dict)
    if _fernet:
        return _fernet.encrypt(config_str.encode()).decode()
    
    # Fallback to plain JSON if no encryption key (e.g., local dev without key)
    # Warning: In production, lack of a key means credentials are saved in plaintext.
    return config_str

def decrypt_config(encrypted_str: Optional[str]) -> Dict[str, Any]:
    """Decrypt a Fernet-encrypted JSON string back to a dictionary."""
    if not encrypted_str:
        return {}
        
    # Check if it looks like a Fernet token (starts with 'gAAAAA')
    if _fernet and encrypted_str.startswith("gAAAAA"):
        try:
            decrypted = _fernet.decrypt(encrypted_str.encode()).decode()
            return json.loads(decrypted)
        except Exception as e:
            logger.error(f"Failed to decrypt config: {e}")
            return {}
            
    # If not encrypted or no key, just parse as plain JSON
    try:
        return json.loads(encrypted_str)
    except Exception:
        return {}
