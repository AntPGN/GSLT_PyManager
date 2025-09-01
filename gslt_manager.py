from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Callable, Optional, List
import os, time
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

# Choose one: undetected_chromedriver (recommended) or regular selenium Chrome
USE_UC = False
if USE_UC:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
else:
    from selenium import webdriver as uc  # alias to keep code the same
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

MANAGE_URL = "https://steamcommunity.com/dev/managegameservers"
LOGIN_URL  = "https://store.steampowered.com/login/"
DEFAULT_TIMEOUT = 25

@dataclass
class Token:
    appid: int
    gslt: str
    last_logon: Optional[str]  # raw string as shown on page
    memo: str
    steamid: str               # the per-token “GS account’s steamid”
    valid: bool

class SteamGSLTManager:
    def __init__(
        self,
        user_data_dir: Optional[str] = None,
        profile_dir: Optional[str] = None,
        headless: bool = True,
        get_guard_code: Optional[Callable[[], str]] = None,
        throttle_seconds: float = 1.0,
    ):
        """
        user_data_dir/profile_dir: reuse an already-signed-in Chrome profile to skip login/2FA.
        headless: set False if you want to see the browser.
        get_guard_code: optional callback that returns a Steam Guard code as string when prompted.
        throttle_seconds: polite sleep between actions.
        """
        self.get_guard_code = get_guard_code
        self.throttle = throttle_seconds

        if USE_UC:
            options = uc.ChromeOptions()
            if headless:
                options.add_argument("--headless=new")
            if user_data_dir:
                options.add_argument(f"--user-data-dir={user_data_dir}")
            if profile_dir:
                options.add_argument(f"--profile-directory={profile_dir}")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            self.driver = uc.Chrome(options=options)
        else:
            opts = Options()
            if headless:
                opts.add_argument("--headless=new")
            if user_data_dir:
                opts.add_argument(f"--user-data-dir={user_data_dir}")
            if profile_dir:
                opts.add_argument(f"--profile-directory={profile_dir}")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            self.driver = uc.Chrome(options=opts)

        self.wait = WebDriverWait(self.driver, DEFAULT_TIMEOUT)

    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass

    def _has_token_table(self) -> bool:
        try:
            server_list = self.driver.find_element(By.ID, "serverList")
        except NoSuchElementException:
            return False
        return len(server_list.find_elements(By.TAG_NAME, "table")) > 0

    def ensure_signed_in(self, interactive: bool = False, timeout: int = 180):
        """
        Ensures we're signed in and the tokens table is present.
        If interactive=True, opens Steam login and waits for you to complete 2FA.
        """
        # Try the manage page first
        self.driver.get(MANAGE_URL)
        if self._has_token_table():
            return  # already signed in

        # If we can do scripted login (env creds set), try that first
        if not interactive and os.environ.get("STEAM_USER") and os.environ.get("STEAM_PASS"):
            self._login_flow()
            self.driver.get(MANAGE_URL)
            if self._has_token_table():
                return

        if not interactive:
            raise RuntimeError("Not signed in. Either call ensure_signed_in(interactive=True) "
                               "or set STEAM_USER/STEAM_PASS and optionally get_guard_code().")

        # Interactive flow: send you to login and wait until the table appears
        self.driver.get(LOGIN_URL)
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(2)
            # Once login finishes (including Guard), go check the manage page
            if "login" not in self.driver.current_url.lower():
                self.driver.get(MANAGE_URL)
                if self._has_token_table():
                    return
                # Might still be bouncing; loop until ready

        raise RuntimeError("Timed out waiting for interactive login to complete.")


    # ---------- Public API ----------

    def create_gslt(self, appid: int, memo: str) -> str:
        """Create a new GSLT and return the newly created token string."""
        self._ensure_manage_page()
        before = {t.gslt for t in self.get_all_tokens()}
        self._fill_create_form(appid, memo)
        time.sleep(self.throttle)
        self._ensure_manage_page()  # reload/land back
        after = [t for t in self.get_all_tokens() if t.appid == int(appid)]
        # Find the token that wasn't present before (by gslt)
        for t in after:
            if t.gslt not in before and t.memo == memo:
                return t.gslt
        # Fallback: return most recently listed matching appid (table often appends newest)
        if after:
            return after[-1].gslt
        raise RuntimeError("Create GSLT appears to have failed or page structure changed.")

    def get_all_tokens(self, appid: Optional[int] = None) -> List[Token]:
        """Return all tokens (optionally filtered by appid)."""
        self._ensure_manage_page()
        tokens = self._parse_token_table()
        if appid is None:
            return tokens
        return [t for t in tokens if t.appid == int(appid)]

    def is_token_valid(self, gslt: str) -> bool:
        """Return True if token row is not struck-through; False otherwise."""
        self._ensure_manage_page()
        for t in self._parse_token_table():
            if t.gslt.upper() == gslt.upper():
                return t.valid
        # Not found on page => not valid for this account
        return False

    def regenerate_token(self, gslt: str) -> str:
        """
        Click the 'Regenerate Token' form on the row matching GSLT.
        Returns the NEW token value after the page reloads.
        """
        self._ensure_manage_page()
        row = self._find_row_by_token(gslt)
        if row is None:
            raise ValueError("Token not found on manage page.")
        steamid = self._extract_steamid_from_row(row)
        # Click the 'Regenerate Token' submit in the forms cell
        forms_cell = row.find_elements(By.TAG_NAME, "td")[-1]
        regen_form = None
        for f in forms_cell.find_elements(By.TAG_NAME, "form"):
            action = f.get_attribute("action") or ""
            if "resetgstoken" in action:
                regen_form = f
                break
        if regen_form is None:
            raise RuntimeError("Could not locate regenerate form for this token.")

        # The page uses a confirm()—triggered by onsubmit—so we bypass JS confirm by submitting via JS.
        self.driver.execute_script("arguments[0].submit();", regen_form)
        time.sleep(self.throttle + 1.5)
        self._ensure_manage_page()

        # Find the row by same per-token steamid; the token value will have changed.
        new_row = self._find_row_by_steamid(steamid)
        if new_row is None:
            # fallback: search by memo/appid proximity
            time.sleep(self.throttle)
            all_tokens = self._parse_token_table()
            for t in all_tokens:
                if t.steamid == steamid:
                    return t.gslt
            raise RuntimeError("Post-regen row not found; page structure may have changed.")
        new_token = new_row.find_elements(By.TAG_NAME, "td")[1].text.strip()
        return new_token

    # ---------- Internals ----------

    def _ensure_manage_page(self):
        self.driver.get(MANAGE_URL)
        # If we’re bounced to login, try to log in
        if LOGIN_URL.split("//")[1].split("/")[0] in self.driver.current_url:
            self._login_flow()
            self.driver.get(MANAGE_URL)
        self.wait.until(EC.presence_of_element_located((By.ID, "serverList")))

    def _login_flow(self):
        """Attempt a basic login; supports optional Steam Guard via callback."""
        # Very light-touch; best is to reuse a signed-in Chrome profile.
        # This is here as a fallback if you want scripted login.
        try:
            self.wait.until(EC.presence_of_element_located((By.ID, "input_username")))
        except Exception:
            return  # maybe already logged in

        # Fill username/password from environment or prompt (you can customize this)
        import os
        user = os.environ.get("STEAM_USER")
        pw = os.environ.get("STEAM_PASS")
        if not user or not pw:
            raise RuntimeError(
                 "Login required but STEAM_USER/STEAM_PASS not set. "
                "Prefer reusing a logged-in Chrome profile via user_data_dir/profile_dir."
            )

        self.driver.find_element(By.ID, "input_username").send_keys(user)
        self.driver.find_element(By.ID, "input_password").send_keys(pw)
        self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

        # Steam Guard?
        try:
            guard_box = WebDriverWait(self.driver, 6).until(
                EC.presence_of_element_located((By.ID, "authcode"))
            )
            code = self.get_guard_code() if self.get_guard_code else None
            if not code:
                raise RuntimeError("Steam Guard code required but no get_guard_code callback provided.")
            guard_box.send_keys(code)
            self.driver.find_element(By.ID, "auth_buttonset_entercode").click()
            WebDriverWait(self.driver, DEFAULT_TIMEOUT).until(
                EC.url_contains("steam")
            )
        except Exception:
            # No guard or already satisfied
            pass

    def _fill_create_form(self, appid: int, memo: str):
        form = self.wait.until(EC.presence_of_element_located((By.ID, "createAccountForm")))
        form.find_element(By.NAME, "appid").clear()
        form.find_element(By.NAME, "appid").send_keys(str(appid))
        form.find_element(By.NAME, "memo").clear()
        form.find_element(By.NAME, "memo").send_keys(memo)
        # Submit via JS to avoid any confirm()
        self.driver.execute_script("arguments[0].submit();", form)

    def _parse_token_table(self):
        tokens = []
        try:
            server_list = self.driver.find_element(By.ID, "serverList")
        except NoSuchElementException:
            return tokens  # not on the right page yet
    
        tables = server_list.find_elements(By.TAG_NAME, "table")
        if not tables:
            return tokens  # logged out or zero-state UI
    
        table = tables[0]
        rows = table.find_elements(By.CSS_SELECTOR, "tbody > tr")
        for r in rows:
            tds = r.find_elements(By.TAG_NAME, "td")
            if len(tds) < 5:
                continue
            appid_txt = tds[0].text.strip()
            gslt_cell = tds[1]
            last_logon_txt = tds[2].text.strip() or None
            memo_txt = tds[3].text.strip()
    
            gslt_txt = gslt_cell.text.strip()
            is_valid = self._cell_not_struck(gslt_cell)
            steamid = self._extract_steamid_from_row(r)
    
            try:
                appid_val = int(appid_txt)
            except ValueError:
                continue
            
            tokens.append(Token(
                appid=appid_val,
                gslt=gslt_txt,
                last_logon=last_logon_txt,
                memo=memo_txt,
                steamid=steamid,
                valid=is_valid,
            ))
        return tokens

    def _cell_not_struck(self, cell) -> bool:
        """
        Detect if the token cell is visually struck-through.
        Steam sometimes renders strike-through with <s>, <strike>, or CSS.
        We check common patterns and computed style.
        """
        # Descendant <s>/<strike>?
        try:
            if cell.find_elements(By.TAG_NAME, "s") or cell.find_elements(By.TAG_NAME, "strike"):
                return False
        except Exception:
            pass
        # Computed style
        try:
            struck = self.driver.execute_script(
                "var e=arguments[0];"
                "var s=window.getComputedStyle(e);"
                "return (s.textDecorationLine||s.textDecoration||'').includes('line-through');",
                cell
            )
            if struck:
                return False
        except Exception:
            pass
        # Fallback: assume valid
        return True

    def _find_row_by_token(self, gslt: str):
        tokens = self._parse_token_table()
        target = None
        for t in tokens:
            if t.gslt.upper() == gslt.upper():
                target = t
                break
        if not target:
            return None
        # Re-query DOM to return the actual row element
        server_list = self.driver.find_element(By.ID, "serverList")
        table = server_list.find_element(By.TAG_NAME, "table")
        for r in table.find_elements(By.CSS_SELECTOR, "tbody > tr"):
            if r.find_elements(By.TAG_NAME, "td")[1].text.strip().upper() == gslt.upper():
                return r
        return None

    def _find_row_by_steamid(self, steamid: str):
        server_list = self.driver.find_element(By.ID, "serverList")
        table = server_list.find_element(By.TAG_NAME, "table")
        for r in table.find_elements(By.CSS_SELECTOR, "tbody > tr"):
            if self._extract_steamid_from_row(r) == steamid:
                return r
        return None

    def _extract_steamid_from_row(self, row) -> str:
        """
        The last cell contains three forms; each has a hidden 'steamid'.
        We read from the 'resetgstoken' form to associate with this row.
        """
        forms_cell = row.find_elements(By.TAG_NAME, "td")[-1]
        for f in forms_cell.find_elements(By.TAG_NAME, "form"):
            action = f.get_attribute("action") or ""
            if "resetgstoken" in action or "deletegsaccount" in action or "updategsmemo" in action:
                hid = f.find_element(By.NAME, "steamid").get_attribute("value")
                if hid:
                    return hid
        return ""

# ------------- Convenience top-level functions -------------
_singleton: Optional[SteamGSLTManager] = None

def init_manager(**kwargs) -> SteamGSLTManager:
    global _singleton
    if _singleton is None:
        _singleton = SteamGSLTManager(**kwargs)
    return _singleton

def create_gslt(appid: int, memo: str) -> str:
    mgr = init_manager()
    return mgr.create_gslt(appid, memo)

def get_all_tokens(appid: Optional[int] = None) -> List[Token]:
    mgr = init_manager()
    return mgr.get_all_tokens(appid)

def is_token_valid(gslt: str) -> bool:
    mgr = init_manager()
    return mgr.is_token_valid(gslt)

def regenerate_token(gslt: str) -> str:
    mgr = init_manager()
    return mgr.regenerate_token(gslt)
