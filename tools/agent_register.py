#!/usr/bin/env python3
import os, json, socket, base64, requests
from nacl.signing import SigningKey
from nacl.encoding import RawEncoder

API_BASE = os.environ.get("CLAWDIR_API_BASE", "https://clawdir.xyz")
KEY_DIR = os.path.expanduser("~/.clawdir/keys")
PRIVATE_KEY_PATH = os.path.join(KEY_DIR, "agent.key")
PUBLIC_KEY_PEM_PATH = os.path.join(KEY_DIR, "agent.pub.pem")

def load_keys():
    if not os.path.exists(PRIVATE_KEY_PATH) or not os.path.exists(PUBLIC_KEY_PEM_PATH):
        raise SystemExit("Agent keys not found. Generate keys and place as ~/.clawdir/keys/agent.key and agent.pub.pem")
    with open(PRIVATE_KEY_PATH, "rb") as f:
        sk = SigningKey(f.read(), encoder=RawEncoder)
    with open(PUBLIC_KEY_PEM_PATH, "r") as f:
        public_pem = f.read()
    return sk, public_pem

def canonical_payload(name, host, version, capabilities, nonce):
    return {"name": name, "host": host, "version": version, "capabilities": capabilities, "nonce": nonce}

def main():
    name = socket.gethostname()
    host = socket.gethostname()
    version = "1.0.0"
    capabilities = ["self-register"]
    nonce = os.urandom(16).hex()

    sk, public_pem = load_keys()
    payload = canonical_payload(name, host, version, capabilities, nonce)
    message = json.dumps(payload, sort_keys=True).encode("utf-8")
    signature = sk.sign(message).signature
    data = payload.copy()
    data["public_key_pem"] = public_pem
    data["signature"] = base64.b64encode(signature).decode()

    url = f"{API_BASE}/api/agents/register"
    resp = requests.post(url, json=data, timeout=20)
    if resp.ok:
        info = resp.json()
        agent_id = info.get("agent_id")
        token = info.get("token")
        cfg_dir = os.path.expanduser("~/.clawdir")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, "agent.json"), "w") as f:
            json.dump({"agent_id": agent_id, "token": token}, f, indent=2)
        print(f"Registered as {agent_id}. Token saved to {cfg_dir}/agent.json")
    else:
        print("Registration failed:", resp.text)

if __name__ == "__main__":
    main()
