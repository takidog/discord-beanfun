import argparse
import json
from typing import Any

import requests


def _request(
    method: str,
    base_url: str,
    token: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> requests.Response:
    url = f"{base_url.rstrip('/')}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Beanfun-Guard": "discord-beanfun",
    }
    return requests.request(
        method=method, url=url, headers=headers, json=payload, timeout=20
    )


def do_status(base_url: str, token: str):
    res = _request("GET", base_url, token, "/status")
    print(f"[GET /status] {res.status_code}")
    print(json.dumps(res.json(), ensure_ascii=False, indent=2))


def do_accounts(base_url: str, token: str):
    res = _request("GET", base_url, token, "/account")
    print(f"[GET /account] {res.status_code}")
    print(json.dumps(res.json(), ensure_ascii=False, indent=2))


def do_otp(base_url: str, token: str, account: str):
    res = _request("POST", base_url, token, "/account", payload={"account": account})
    print(f"[POST /account] {res.status_code}")
    print(json.dumps(res.json(), ensure_ascii=False, indent=2))


def do_interactive(base_url: str, token: str):
    while True:
        print("\nChoose action:")
        print("1) status")
        print("2) accounts")
        print("3) otp")
        print("q) quit")
        choice = input("> ").strip().lower()

        if choice == "1":
            do_status(base_url, token)
        elif choice == "2":
            do_accounts(base_url, token)
        elif choice == "3":
            account = input("account id: ").strip()
            if not account:
                print("account id is required")
                continue
            do_otp(base_url, token, account)
        elif choice == "q":
            break
        else:
            print("Unknown choice")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Test client for discord-beanfun app HTTP server"
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8999",
        help="HTTP server base url, e.g. http://127.0.0.1:8080",
    )
    parser.add_argument("--token", required=True, help="API token from /register-app")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run interactive mode",
    )

    sub = parser.add_subparsers(dest="command")
    sub.required = False

    sub.add_parser("status", help="Call GET /status")
    sub.add_parser("accounts", help="Call GET /account")
    otp = sub.add_parser("otp", help="Call POST /account")
    otp.add_argument("--account", required=True, help="Target account id")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.interactive:
        do_interactive(args.base_url, args.token)
        return

    if args.command == "status":
        do_status(args.base_url, args.token)
        return
    if args.command == "accounts":
        do_accounts(args.base_url, args.token)
        return
    if args.command == "otp":
        do_otp(args.base_url, args.token, args.account)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
