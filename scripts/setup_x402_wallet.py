"""Create one private local TESTNET payer key without ever displaying its contents."""

import argparse
import json
import os
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a dedicated Base Sepolia testnet payer.")
    parser.add_argument("--path", default=".local/x402-payer.key")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = Path(arguments.path)
    if not destination.is_absolute():
        destination = root / destination
    destination = destination.resolve()
    if not destination.is_relative_to((root / ".local").resolve()):
        print("Store the dedicated testnet key beneath this project's ignored .local directory.", file=sys.stderr)
        return 1
    try:
        from eth_account import Account
    except ImportError:
        print("Install the optional wallet dependencies: uv sync --locked --extra x402", file=sys.stderr)
        return 1
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    account = Account.create()
    try:
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        print("Key file already exists. It was not read or overwritten.", file=sys.stderr)
        return 1
    with os.fdopen(descriptor, "w") as stream:
        stream.write("0x" + account.key.hex().removeprefix("0x") + "\n")
    print(json.dumps({
        "network": "eip155:84532", "address": account.address,
        "key_file": str(destination.relative_to(root)), "funding_required": True,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
