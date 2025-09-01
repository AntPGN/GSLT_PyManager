# Steam GSLT Manager (Selenium)

Manage your Steam **Game Server Login Tokens (GSLTs)** from Python using Selenium (or undetected-chromedriver).  
This library opens the official Steam “Manage Game Servers” page and performs the same actions you would: create tokens, list tokens, check validity, and regenerate tokens.

> ✅ Works with a regular Chrome WebDriver *or* `undetected_chromedriver`  
> ✅ Can reuse an already-signed-in Chrome profile (skips login/2FA)  
> ✅ Optional scripted login via `STEAM_USER` / `STEAM_PASS`, with Steam Guard callback

---

## Contents

- [Features](#features)  
- [Requirements](#requirements)  
- [Install](#install)  
- [Quick Start](#quick-start)  
- [API](#api)  
  - [Top-level convenience functions](#top-level-convenience-functions)  
  - [Class API](#class-api)  
  - [Token dataclass](#token-dataclass)  
- [Auth & Session Options](#auth--session-options)  
- [Headless vs Headed](#headless-vs-headed)  
- [Tips: Profile Paths / Relative Paths](#tips-profile-paths--relative-paths)  
- [Troubleshooting](#troubleshooting)  
- [Notes & Disclaimer](#notes--disclaimer)  
- [License](#license)

---

## Features

- **Create** a new GSLT for a given `appid` with a memo.
- **List** all tokens, optionally filtering by `appid`.
- **Check validity** (detects strike-through styling that Steam uses for invalid tokens).
- **Regenerate** an existing token (returns the *new* token string).
- **Handle login**:
  - Reuse a signed-in Chrome profile (recommended).
  - Or provide env vars `STEAM_USER` / `STEAM_PASS`.
  - Optional callback to supply **Steam Guard** code when prompted.

---

## Requirements

- Python 3.8+
- One of:
  - **Selenium** + **ChromeDriver** that matches your Chrome version
  - **undetected_chromedriver** (recommended for some environments)
- Google Chrome (or Chromium) installed
- A Steam account with access to the GSLT page

---

## Install

```bash
pip install selenium undetected-chromedriver
```

> If you prefer standard Selenium only, you can skip `undetected_chromedriver`. The code supports both.

---

## Quick Start

### 1) Reuse a signed-in Chrome profile (fastest path)
```python
from gslt_manager import init_manager, get_all_tokens, create_gslt

mgr = init_manager(
    user_data_dir=r"C:\Users\you\AppData\Local\Google\Chrome\User Data",
    profile_dir="Default",     # e.g. "Default" or "Profile 1"
    headless=True,             # set False to watch the browser
    throttle_seconds=1.0
)

# Optional: ensure you're signed in (will open login if needed)
mgr.ensure_signed_in(interactive=True)

# List tokens
for t in get_all_tokens():
    print(t.appid, t.gslt, t.valid, t.memo)

# Create a new token
new_token = create_gslt(appid=730, memo="My CS2 server")
print("New token:", new_token)
```

### 2) Scripted login with env vars (falls back automatically)
Set environment variables first:
```bash
# Windows PowerShell
$env:STEAM_USER="your_steam_username"
$env:STEAM_PASS="your_steam_password"
```

Then:
```python
from gslt_manager import init_manager, get_all_tokens

mgr = init_manager(headless=True)
# If not already signed in with a profile, library will try scripted login
mgr.ensure_signed_in()  # interactive=False by default

print(get_all_tokens())
```

### 3) Steam Guard 2FA
If you expect Steam Guard prompts, pass a callback that returns the current code:

```python
def fetch_guard_code() -> str:
    # Pull from your authenticator, CLI prompt, env var, etc.
    return input("Enter Steam Guard code: ").strip()

mgr = init_manager(get_guard_code=fetch_guard_code, headless=False)
mgr.ensure_signed_in()
```

---

## API

### Top-level convenience functions

```python
from gslt_manager import (
    init_manager,
    create_gslt,
    get_all_tokens,
    is_token_valid,
    regenerate_token,
)
```

- `init_manager(**kwargs) -> SteamGSLTManager`  
  Singleton initializer. Accepts the same kwargs as `SteamGSLTManager(...)`.

- `create_gslt(appid: int, memo: str) -> str`  
  Creates a token and returns the **token string**.

- `get_all_tokens(appid: Optional[int] = None) -> List[Token]`  
  Returns all tokens; filter by `appid` if provided.

- `is_token_valid(gslt: str) -> bool`  
  True if the token row is **not** struck-through on the page.

- `regenerate_token(gslt: str) -> str`  
  Clicks “Regenerate Token” for the row matching `gslt` and returns the **new** token string.

> These helpers implicitly reuse the singleton manager you created with `init_manager()`.

---

### Class API

```python
from gslt_manager import SteamGSLTManager

mgr = SteamGSLTManager(
    user_data_dir: Optional[str] = None,
    profile_dir:   Optional[str] = None,
    headless:      bool = True,
    get_guard_code: Optional[Callable[[], str]] = None,
    throttle_seconds: float = 1.0,
)
```

- `ensure_signed_in(interactive: bool = False, timeout: int = 180) -> None`  
  Ensures the session is signed in and token table is present.  
  - If `interactive=True`, opens Steam login and waits for you to finish (incl. guard).  
  - If `interactive=False` and `STEAM_USER`/`STEAM_PASS` are set, attempts scripted login.

- `create_gslt(appid: int, memo: str) -> str`  
  Creates a token and returns the token string.

- `get_all_tokens(appid: Optional[int] = None) -> List[Token]`  
  Returns token list, optionally filtered by `appid`.

- `is_token_valid(gslt: str) -> bool`  
  Checks strike-through styling to infer validity.

- `regenerate_token(gslt: str) -> str`  
  Submits the “resetgstoken” form for that row and returns the new token.

- `close() -> None`  
  Quits the browser (called automatically by Python if the process exits, but it’s good hygiene to call it yourself).

---

### Token dataclass

```python
@dataclass
class Token:
    appid: int
    gslt: str
    last_logon: Optional[str]  # raw timestamp text shown on the page
    memo: str
    steamid: str               # per-token “GS account’s steamid”
    valid: bool                # True if not visually struck-through
)
```

---

## Auth & Session Options

You have three main ways to handle auth:

1. **Reuse a signed-in Chrome profile (recommended)**  
   Pass `user_data_dir` and `profile_dir`. This typically bypasses login and Steam Guard entirely.

2. **Scripted login via env vars**  
   Set `STEAM_USER` and `STEAM_PASS`. The library fills the login form for you.  
   - If Steam Guard appears, provide `get_guard_code` callback; otherwise you’ll get a runtime error.

3. **Interactive mode**  
   Call `ensure_signed_in(interactive=True)` to manually complete login. Useful if you don’t want to store creds anywhere.

---

## Headless vs Headed

- `headless=True` runs Chrome without a visible window (default).  
- Set `headless=False` to watch the automation (useful while debugging login or DOM changes).

---

## Tips: Profile Paths / Relative Paths

If your project keeps a `Profile/` folder next to your script, you can build the path at runtime:

```python
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # this file's directory
profile_root = os.path.join(BASE_DIR, "Profile")

mgr = init_manager(
    user_data_dir=profile_root,
    profile_dir="Default",
    headless=True,
)
```

On Windows, a typical Chrome profile root is:

```
C:\Users\<YOU>\AppData\Local\Google\Chrome\User Data
```

---

## Troubleshooting

- **“It goes to the page and instantly dies / no tokens table”**  
  You’re probably not signed in. Use a signed-in Chrome profile **or** call:  
  ```python
  mgr.ensure_signed_in(interactive=True)
  ```

- **Token validity always True/False**  
  Steam renders invalid tokens with strike-through using `<s>/<strike>` or CSS.  
  This library checks both. If Steam changes markup, adjust `_cell_not_struck`.

- **Regenerate didn’t return the new token**  
  The page layout can shift. If DOM changes significantly, update `_find_row_by_steamid`.

- **Chrome/driver mismatches**  
  Ensure your ChromeDriver matches your Chrome version. Consider `undetected_chromedriver`.

- **Headless login quirks**  
  If Steam behaves differently in headless mode, try `headless=False` for first login.

---

## Notes & Disclaimer

- This library **automates your own browser** to interact with Steam’s official page.  
- Use responsibly and in accordance with Steam’s Terms of Service.  
- Page structure can change. Inspect DOM and update `_parse_token_table()` if needed.  
- Reusing a signed-in profile is the most reliable option.

---

## License

MIT — see `LICENSE` for details.
