#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auth_runner.py — Simple auth runner.

Design principle: the user supplies username+password upfront (via SKILL prompt
or env vars). This script tries to log in with those credentials. If auto-login
fails, it launches a non-headless browser so the user can log in manually,
then captures storageState for reuse.

Three commands:
  login    — auto-login with supplied credentials + save storageState
  record   — launch non-headless browser, user logs in manually
  verify   — check existing storageState still works

Input is a minimal JSON file (not a big YAML blueprint):
  {
    "base_url":   "http://localhost:3000",
    "login_url":  "/login",                  # optional, auto-discovered if not set
    "username":   "admin@etc.vn",
    "password":   "Admin@123",
    "selectors": {                           # optional — only if auto-discovery fails
      "username": "#username",
      "password": "#password",
      "submit":   "button[type=submit]"
    },
    "post_login_url": "/dashboard"           # optional, used to verify login success
  }
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        print("ERROR: Playwright not installed. Run: pip install playwright && playwright install chromium",
              file=sys.stderr)
        sys.exit(2)


# ─────────────────────────── Selector cascade (fallback) ───────────────────────────

USERNAME_SELECTORS = [
    "[data-testid*='email']", "[data-testid*='user']",
    "[name='email']", "[name='userName']", "[name='username']", "[name='user']",
    "[id='email']", "[id='username']", "[id='user']",
    "input[type='email']",
    "input[placeholder*='email' i]",
    "input[placeholder*='tài khoản' i]",
    "input[placeholder*='Email' i]",
]

PASSWORD_SELECTORS = [
    "[data-testid*='password']", "[data-testid*='pwd']",
    "[name='password']", "[name='pwd']", "[name='pass']",
    "[id='password']", "[id='pwd']",
    "input[type='password']",
]

SUBMIT_SELECTORS = [
    "[data-testid*='submit']", "[data-testid*='login']", "[data-testid*='signin']",
    "button[type='submit']", "input[type='submit']",
    "button:has-text('Đăng nhập')", "button:has-text('Login')",
    "button:has-text('Sign in')", "button:has-text('Log in')",
    "button:has-text('Tiếp tục')",
]


def _find_selector(page, candidates: list[str]) -> str | None:
    """Try each selector; return first that resolves to a visible element."""
    for sel in candidates:
        if not sel:
            continue
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=500):
                return sel
        except Exception:
            continue
    return None


def _discover_login_url(page, base_url: str) -> str | None:
    """Try common login paths until one returns a page with a password field."""
    for path in ("/login", "/auth/login", "/signin", "/sign-in", "/users/sign_in"):
        try:
            page.goto(f"{base_url}{path}", wait_until="networkidle", timeout=8000)
        except Exception:
            continue
        if page.locator("input[type='password']").first.is_visible(timeout=1000):
            return path
    return None


def _verify_logged_in(page, base_url: str, post_login_url: str | None) -> bool:
    """Return True if the page appears to be authenticated.

    Checks (any-of): URL != login, storage token exists, logout UI visible.
    """
    if post_login_url:
        try:
            page.goto(f"{base_url}{post_login_url}", wait_until="networkidle", timeout=10_000)
        except Exception:
            pass
    url = page.url
    if re.search(r"/(login|signin|sign[_-]in|auth)(/|\?|$)", url):
        return False
    try:
        has_token = page.evaluate("""() => {
            const keys = ['access_token','token','auth_token','jwt','authToken'];
            for (const k of keys) {
                if (localStorage.getItem(k) || sessionStorage.getItem(k)) return true;
            }
            return false;
        }""")
        if has_token:
            return True
    except Exception:
        pass
    try:
        if page.locator("text=/logout|đăng xuất|sign out/i").first.is_visible(timeout=1000):
            return True
    except Exception:
        pass
    # URL is not-login and no indicator caught — still OK (some apps just route)
    return True


# ─────────────────────────── Commands ───────────────────────────

def cmd_login(args) -> int:
    creds = json.loads(Path(args.input).read_text(encoding="utf-8"))
    base_url = creds["base_url"].rstrip("/")
    username = creds["username"]
    password = creds["password"]
    login_url = creds.get("login_url")
    post_login_url = creds.get("post_login_url")
    provided = creds.get("selectors") or {}
    state_out = Path(args.state_out)
    state_out.parent.mkdir(parents=True, exist_ok=True)

    result = {"status": "pending", "method": None, "error": None, "elapsed_s": 0}
    t0 = time.time()

    sync_pw = _import_playwright()
    with sync_pw() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # Discover login URL if not provided
        if not login_url:
            login_url = _discover_login_url(page, base_url)
            if not login_url:
                result["status"] = "failed"
                result["error"] = "no login page found. Set `login_url` in auth.json."
                print(json.dumps(result, indent=2))
                browser.close()
                return 1

        page.goto(f"{base_url}{login_url}", wait_until="networkidle", timeout=10_000)

        # Resolve selectors — provided first, else cascade
        user_sel = provided.get("username") or _find_selector(page, USERNAME_SELECTORS)
        pwd_sel = provided.get("password") or _find_selector(page, PASSWORD_SELECTORS)
        sub_sel = provided.get("submit") or _find_selector(page, SUBMIT_SELECTORS)

        if not (user_sel and pwd_sel and sub_sel):
            result["status"] = "failed"
            result["error"] = (
                f"Could not locate login form elements: "
                f"username={bool(user_sel)}, password={bool(pwd_sel)}, submit={bool(sub_sel)}. "
                f"Suggest: run `auth_runner.py record` for manual login."
            )
            print(json.dumps(result, indent=2))
            browser.close()
            return 1

        # Fill + submit
        try:
            page.fill(user_sel, username)
            page.fill(pwd_sel, password)
            page.click(sub_sel)
            # Wait for navigation away from login URL
            try:
                page.wait_for_function(
                    "() => !window.location.pathname.match(/\\\\/(login|signin|sign[_-]in|auth)($|\\\\/|\\\\?)/i)",
                    timeout=10_000,
                )
            except Exception:
                pass
        except Exception as e:
            result["status"] = "failed"
            result["error"] = f"fill/submit crashed: {e}"
            print(json.dumps(result, indent=2))
            browser.close()
            return 1

        if _verify_logged_in(page, base_url, post_login_url):
            context.storage_state(path=str(state_out))
            result["status"] = "success"
            result["method"] = "auto-login"
            result["state_file"] = str(state_out)
            result["selectors_used"] = {"username": user_sel, "password": pwd_sel, "submit": sub_sel}
            result["elapsed_s"] = round(time.time() - t0, 2)
            browser.close()
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0

        result["status"] = "failed"
        result["error"] = f"verification failed — still on {page.url}"
        result["elapsed_s"] = round(time.time() - t0, 2)
        browser.close()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1


def cmd_record(args) -> int:
    """Launch non-headless browser, let user log in manually, capture state."""
    creds_path = Path(args.input) if args.input else None
    base_url = args.base_url
    state_out = Path(args.state_out)
    state_out.parent.mkdir(parents=True, exist_ok=True)

    if creds_path and creds_path.exists():
        c = json.loads(creds_path.read_text(encoding="utf-8"))
        base_url = base_url or c.get("base_url")

    if not base_url:
        print("ERROR: --base-url required (or provide in --input JSON)", file=sys.stderr)
        return 1

    print()
    print("=" * 60)
    print("MANUAL LOGIN MODE")
    print("=" * 60)
    print(f"Browser sẽ mở. Hãy đăng nhập thủ công tại {base_url}.")
    print("Sau khi vào được dashboard / home, ĐÓNG browser window.")
    print("Pipeline sẽ tự động lưu session để dùng các lần sau.")
    print("=" * 60)
    print()

    sync_pw = _import_playwright()
    result = {"status": "pending", "method": "manual-recording", "elapsed_s": 0}
    t0 = time.time()

    with sync_pw() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        try:
            page.goto(base_url, wait_until="networkidle", timeout=10_000)
        except Exception:
            pass

        timeout_min = args.timeout_minutes
        deadline = time.time() + timeout_min * 60

        try:
            while time.time() < deadline:
                time.sleep(2)
                try:
                    if page.is_closed() or not browser.is_connected():
                        break
                except Exception:
                    break
                # Auto-detect: URL no longer matches login → give 3s more, then save
                try:
                    url = page.url
                    if not re.search(r"/(login|signin|sign[_-]in|auth)(/|\?|$)", url):
                        time.sleep(3)
                        if not re.search(r"/(login|signin|sign[_-]in|auth)(/|\?|$)", page.url):
                            break
                except Exception:
                    break
        except KeyboardInterrupt:
            pass

        try:
            context.storage_state(path=str(state_out))
            result["status"] = "success"
            result["state_file"] = str(state_out)
            result["final_url"] = page.url if not page.is_closed() else "closed"
        except Exception as e:
            result["status"] = "failed"
            result["error"] = f"state save failed: {e}"
        finally:
            try:
                browser.close()
            except Exception:
                pass

    result["elapsed_s"] = round(time.time() - t0, 2)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "success" else 1


def cmd_verify(args) -> int:
    sync_pw = _import_playwright()
    state_file = args.state_file
    base_url = args.base_url.rstrip("/")
    target_url = args.target_url or "/"

    with sync_pw() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(storage_state=state_file)
        except Exception as e:
            browser.close()
            print(json.dumps({"status": "invalid", "error": f"cannot load state: {e}"}))
            return 1
        page = context.new_page()
        try:
            page.goto(f"{base_url}{target_url}", wait_until="networkidle", timeout=10_000)
        except Exception:
            pass
        url = page.url
        browser.close()

    if re.search(r"/(login|signin|sign[_-]in|auth)(/|\?|$)", url):
        print(json.dumps({"status": "stale", "final_url": url}))
        return 1
    print(json.dumps({"status": "valid", "final_url": url}))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Simple auth runner for doc generation pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser("login", help="Auto-login with provided credentials")
    p_login.add_argument("--input", required=True, help="Path to auth.json with base_url/username/password")
    p_login.add_argument("--state-out", required=True, help="Where to save captured storageState")
    p_login.set_defaults(func=cmd_login)

    p_rec = sub.add_parser("record", help="Manual login mode — launch non-headless browser")
    p_rec.add_argument("--input", default=None, help="Optional auth.json for base_url")
    p_rec.add_argument("--base-url", default=None)
    p_rec.add_argument("--state-out", required=True)
    p_rec.add_argument("--timeout-minutes", type=int, default=5)
    p_rec.set_defaults(func=cmd_record)

    p_ver = sub.add_parser("verify", help="Check if existing storageState is still valid")
    p_ver.add_argument("--state-file", required=True)
    p_ver.add_argument("--base-url", required=True)
    p_ver.add_argument("--target-url", default="/", help="URL to navigate for verification")
    p_ver.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
