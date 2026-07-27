from pathlib import Path
from cryptography.fernet import Fernet

def key(secret_dir):
    path=Path(secret_dir)/".keyfile"; path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists(): path.write_bytes(Fernet.generate_key()); path.chmod(0o600)
    return path.read_bytes()
def encrypt(value, secret_dir): return Fernet(key(secret_dir)).encrypt(value.encode())
def decrypt(value, secret_dir): return Fernet(key(secret_dir)).decrypt(value).decode()
