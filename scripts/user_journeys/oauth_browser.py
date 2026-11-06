"""External browser fixture for account-free ChatGPT sign-in failure journeys.

No OpenAI page is fetched and no token is issued. The actual app still creates
PKCE/state, starts its callback server, opens the configured browser command,
handles the HTTP callback and updates its real Settings controls.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import ProxyHandler, build_opener


def main():
    state = Path(os.environ["OPENWAND_E2E_STATE"]).resolve()
    output = Path(os.environ["OPENWAND_E2E_OUTPUT"]).resolve()
    assert (state / ".user-journey-state").is_file() and state.parent == output
    authorize = urlparse(sys.argv[1])
    assert (authorize.scheme, authorize.netloc, authorize.path) == ("https", "auth.openai.com", "/oauth/authorize")
    query = parse_qs(authorize.query)
    redirect = urlparse(query["redirect_uri"][0])
    assert redirect.scheme == "http" and redirect.hostname in {"localhost", "127.0.0.1"} and redirect.path == "/auth/callback"
    assert query["code_challenge_method"] == ["S256"] and len(query["code_challenge"][0]) >= 43
    assert query["state"][0] and query["response_type"] == ["code"]
    mode = (output / "browser-mode.txt").read_text(encoding="utf-8")
    callback = {"state": query["state"][0]}
    if mode == "declined":
        callback.update(error="access_denied", error_description="E2E sign-in declined")
    elif mode == "mismatched_state":
        callback.update(code="not-an-exchangeable-code", state="incorrect-state")
    elif mode != "missing_code":
        raise ValueError("Unsupported browser fixture mode")
    evidence = output / "browser-events.json"
    events = json.loads(evidence.read_text(encoding="utf-8")) if evidence.exists() else []
    events.append({"mode": mode, "pkce": True, "state_present": True, "callback_host": redirect.hostname})
    evidence.write_text(json.dumps(events, indent=2), encoding="utf-8")
    # Only the app's loopback callback is contacted. The mismatched and absent
    # code paths must fail before any external token exchange can take place.
    callback_url = redirect._replace(query=urlencode(callback)).geturl()
    with build_opener(ProxyHandler({})).open(callback_url, timeout=10) as response:
        assert response.status == 200
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
