#!/usr/bin/env python3
"""Apply the minimal private-network exemption for the internal /v1 gateway."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src/openakita/api/auth.py"


def main() -> None:
    text = PATH.read_text("utf-8")
    if "def is_private_direct_request" not in text:
        text = text.replace("import hmac\n", "import hmac\nimport ipaddress\n", 1)
        marker = "\ndef _is_auth_exempt(path: str) -> bool:\n"
        helper = '''\ndef is_private_direct_request(request: Request) -> bool:\n    \"\"\"Allow keyless /v1 only for direct private-network peers.\"\"\"\n    if not request.client:\n        return False\n    if request.headers.get(\"x-forwarded-for\") or request.headers.get(\"forwarded\"):\n        return False\n    try:\n        address = ipaddress.ip_address(request.client.host.removeprefix(\"::ffff:\"))\n    except ValueError:\n        return False\n    return address.is_private or address.is_loopback or address.is_link_local\n\n'''
        if marker not in text:
            raise RuntimeError("auth exemption marker missing")
        text = text.replace(marker, helper + marker, 1)
    condition = '''        path = request.url.path\n\n        # Static files and auth endpoints are always accessible\n'''
    replacement = '''        path = request.url.path\n\n        # Hermes uses this OpenAI-compatible gateway only over the direct\n        # Docker/private network. Requests carrying proxy forwarding headers\n        # still go through normal web authentication.\n        if path.startswith(\"/v1/\") and is_private_direct_request(request):\n            return await call_next(request)\n\n        # Static files and auth endpoints are always accessible\n'''
    if replacement not in text:
        if condition not in text:
            raise RuntimeError("auth middleware marker missing")
        text = text.replace(condition, replacement, 1)
    PATH.write_text(text, "utf-8")
    print("Hermes private gateway auth exemption integrated")


if __name__ == "__main__":
    main()
