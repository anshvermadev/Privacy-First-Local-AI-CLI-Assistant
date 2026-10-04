"""AES-GCM via cryptography; keyring or scrypt-wrapped master key, never homemade crypto."""
import base64
from .interaction import ask
import hashlib
import json
import os
from pathlib import Path
import uuid

from .models import SafeError
from .permissions import secure


def b64(value):
    return base64.b64encode(value).decode("ascii")


def unb64(value):
    return base64.b64decode(value, validate=True)


def aes(key):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise SafeError("Install the crypto extra, or explicitly initialize with --no-encryption.", "CRYPTO_UNAVAILABLE") from None
    return AESGCM(key)


def passphrase(confirm=False):
    value = ask("Passphrase (at least 12 characters): ", password=True)
    if len(value) < 12:
        raise SafeError("Use a passphrase of at least 12 characters.")
    if confirm and value != ask("Repeat passphrase: ", password=True):
        raise SafeError("Passphrases did not match.")
    return value


def derive(password, salt):
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=32768, r=8, p=1, dklen=32, maxmem=67108864)


def seal(key, data, aad):
    nonce = os.urandom(12)
    return nonce + aes(key).encrypt(nonce, data, aad)


def unseal(key, data, aad):
    return aes(key).decrypt(data[:12], data[12:], aad)


def write_private(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    created = False
    try:
        with tmp.open("x", encoding="utf-8") as file:
            created = True
            secure(tmp)
            json.dump(obj, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, path)
    finally:
        if created and tmp.exists():
            tmp.unlink()


class Vault:
    def __init__(self, key=None):
        self.key = key

    def encrypt(self, value, event_id):
        encoded = value.encode("utf-8")
        return seal(self.key, encoded, event_id.encode()) if self.key else encoded

    def decrypt(self, value, event_id):
        return (unseal(self.key, value, event_id.encode()) if self.key else value).decode("utf-8")

    @classmethod
    def initialize(cls, root, mode="auto", password=None):
        if mode == "none":
            write_private(root / "crypto.json", {"mode": "none", "version": 1})
            return cls()
        key = os.urandom(32)
        aes(key)
        account = str(uuid.uuid4())
        if mode in ("auto", "keyring"):
            try:
                import keyring
                backend = type(keyring.get_keyring()).__module__
                if backend not in {"keyring.backends.Windows", "keyring.backends.macOS", "keyring.backends.SecretService", "keyring.backends.kwallet"}:
                    raise ValueError("Not a supported OS-backed keyring")
                keyring.set_password("privacy-first-local-ai", account, b64(key))
                if keyring.get_password("privacy-first-local-ai", account) != b64(key):
                    keyring.delete_password("privacy-first-local-ai", account)
                    raise ValueError()
            except Exception:
                if mode == "keyring":
                    raise SafeError("OS keyring unavailable. Initialize with --encryption passphrase.", "KEY_UNAVAILABLE") from None
            else:
                try:
                    write_private(root / "crypto.json", {"mode": "keyring", "account": account, "version": 1})
                except BaseException:
                    keyring.delete_password("privacy-first-local-ai", account)
                    raise
                return cls(key)
        password = password if password is not None else passphrase(confirm=True)
        if len(password) < 12:
            raise SafeError("Use a passphrase of at least 12 characters.")
        salt = os.urandom(16)
        wrapped = seal(derive(password, salt), key, b"local-ai-master-v1")
        write_private(root / "crypto.json", {"mode": "passphrase", "version": 1, "salt": b64(salt), "wrapped": b64(wrapped)})
        return cls(key)

    @classmethod
    def open(cls, root, password=None):
        try:
            obj = json.loads((root / "crypto.json").read_text(encoding="utf-8"))
            if obj["version"] != 1:
                raise ValueError()
            if obj["mode"] == "none":
                return cls()
            if obj["mode"] == "keyring":
                import keyring
                key = unb64(keyring.get_password("privacy-first-local-ai", obj["account"]))
            elif obj["mode"] == "passphrase":
                password = password if password is not None else passphrase()
                key = unseal(derive(password, unb64(obj["salt"])), unb64(obj["wrapped"]), b"local-ai-master-v1")
            else:
                raise ValueError()
            if len(key) != 32:
                raise ValueError()
            return cls(key)
        except SafeError:
            raise
        except Exception:
            raise SafeError("Cannot unlock raw storage; check passphrase, keyring and crypto metadata.", "KEY_UNAVAILABLE") from None


def remove_key(root):
    try:
        obj = json.loads((root / "crypto.json").read_text(encoding="utf-8"))
        if obj["mode"] == "keyring":
            import keyring
            keyring.delete_password("privacy-first-local-ai", obj["account"])
    except Exception:
        raise SafeError("Could not remove the keyring key; wipe stopped before deleting state.", "KEY_UNAVAILABLE") from None
