import json
import re
import time
import requests
from urllib.parse import urlparse, parse_qs, unquote
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

from src.config import INSTAGRAM_SESSION_ID, BASE_DIR
from src.web_extractor import WebExtractor, DeepResource
from src.obsidian_writer import ObsidianWriter

CACHE_FILE = BASE_DIR / "processed_dms.json"

class InstagramDMWatcher:
    def __init__(self):
        self.session_id = INSTAGRAM_SESSION_ID
        self.user_id = self.session_id.split("%3A")[0] if "%3A" in self.session_id else "72104539753"
        self.web_extractor = WebExtractor()
        self.writer = ObsidianWriter()
        self.processed_ids = self._load_processed_ids()
        self.session = requests.Session()
        self.csrf_token: Optional[str] = None
        self._init_session()

    def _init_session(self):
        """
        Initialize persistent web session with pure Chrome Desktop headers.
        Strictly avoid calling mobile-only endpoints (like broadcast/text) to ensure
        the session cookie remains permanently valid.
        """
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "X-IG-App-ID": "936619743392459",
            "Cookie": f"sessionid={self.session_id}; ds_user_id={self.user_id}"
        })
        self._refresh_csrf()
        self.session.headers.update({
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        })

    def _refresh_csrf(self):
        """Fetch fresh CSRF token from Instagram."""
        try:
            resp = self.session.head("https://www.instagram.com/", timeout=6)
            token = self.session.cookies.get("csrftoken")
            if token:
                self.csrf_token = token
                self.session.headers["X-CSRFToken"] = token
        except Exception as e:
            print(f"[WARN] Failed to refresh CSRF token: {e}")

    def _get_web_headers(self, referer: str = "https://www.instagram.com/direct/inbox/") -> Dict[str, str]:
        headers = dict(self.session.headers)
        headers["Referer"] = referer
        if self.csrf_token:
            headers["X-CSRFToken"] = self.csrf_token
        return headers

    def _get_read_headers(self) -> Dict[str, str]:
        """
        Headers enabling Instagram to return full generic_xma ManyChat cards and cta_buttons.
        Safe for GET requests and does not trigger session revocation.
        """
        return {
            "User-Agent": "Instagram 320.0.0.35.109 Android (31/12; 480dpi; 1080x2400; samsung; SM-G991B; o1s; exynos2100; en_US; 571216503)",
            "X-IG-App-ID": "936619743392459",
            "X-IG-Capabilities": "3brBvw==",
            "Cookie": f"sessionid={self.session_id}; ds_user_id={self.user_id}"
        }

    def _load_processed_ids(self) -> set:
        if CACHE_FILE.exists():
            try:
                data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                return set(data)
            except Exception:
                return set()
        return set()

    def _save_processed_ids(self):
        try:
            CACHE_FILE.write_text(json.dumps(list(self.processed_ids)), encoding="utf-8")
        except Exception:
            pass

    def unshorten_url(self, url: str) -> str:
        """
        Unshorten and resolve dynamic ManyChat redirectors and link-in-bio aggregators:
        - LinkPlease (linkplease.co, fb.wh.linkplease.in)
        - Cosmofeed (cosmofeed.com)
        - LinkToDM (opening.linktodm.com, linktodm.com)
        - Bitly, TinyURL, Cuttly, Dub.sh, etc.
        - Google Drive (drive.google.com)
        - Linktree, Bento (extracts the first featured resource link if it's an aggregator)
        """
        if not url:
            return url

        # 1. LinkPlease direct API lookup
        if "linkplease.co/r/" in url:
            code = url.split("linkplease.co/r/")[-1].split("?")[0].split("/")[0]
            try:
                r = requests.get(f"https://fb.wh.linkplease.in/v0/get_short_link/{code}", timeout=6)
                if r.status_code == 200:
                    orig = r.json().get("original_url")
                    if orig:
                        return self.unshorten_url(orig)
            except Exception:
                pass

        # 2. Cosmofeed or LinkToDM query param url=
        if ("cosmofeed.com" in url or "linktodm.com" in url) and "url=" in url:
            try:
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                if "url" in params and params["url"]:
                    orig = unquote(params["url"][0])
                    return self.unshorten_url(orig)
            except Exception:
                pass

        # 3. Instagram external link wrapper (l.instagram.com/?u=...)
        if "l.instagram.com" in url and "u=" in url:
            try:
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                if "u" in params and params["u"]:
                    orig = unquote(params["u"][0])
                    return self.unshorten_url(orig)
            except Exception:
                pass

        # 4. If Google Drive link, preserve it directly
        if "drive.google.com" in url:
            return url

        # 5. Follow HTTP redirects to destination
        final_url = url
        try:
            resp = requests.get(
                url,
                allow_redirects=True,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            final_url = resp.url
        except Exception:
            final_url = url

        # 6. If final URL is Linktree or Bento aggregator, find the primary destination link
        if "linktr.ee" in final_url or "bento.me" in final_url:
            try:
                r = requests.get(final_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
                if r.status_code == 200:
                    found_links = re.findall(r'href="(https?://[^"]+)"', r.text)
                    for l in found_links:
                        if not any(ign in l.lower() for ign in ["instagram.com", "linktr.ee", "bento.me", "twitter.com", "facebook.com", "tiktok.com"]):
                            return l
            except Exception:
                pass

        return final_url

    def extract_urls_from_item(self, item: Dict[str, Any]) -> List[str]:
        """Extract and unshorten all valid external resource links from a DM message item."""
        extracted = []

        # 1. generic_xma CTA buttons (ManyChat interactive cards)
        xma_list = item.get("generic_xma") or item.get("xma") or []
        if isinstance(xma_list, dict):
            xma_list = [xma_list]

        for xma in xma_list:
            for btn in xma.get("cta_buttons", []):
                act = btn.get("action_url")
                if act:
                    extracted.append(act)
            if xma.get("target_url"):
                extracted.append(xma["target_url"])

        # 2. Standard link payload
        if "link" in item:
            link_obj = item["link"]
            if isinstance(link_obj, dict):
                text_url = link_obj.get("text")
                if text_url:
                    extracted.append(text_url)
                link_ctx = link_obj.get("link_context", {})
                if link_ctx.get("link_url"):
                    extracted.append(link_ctx.get("link_url"))

        # 3. Text message regex
        text = item.get("text", "") or ""
        urls = re.findall(r'https?://[^\s"\'<>]+', text)
        extracted.extend(urls)

        # 4. Filter out garbage / internal social URLs and resolve redirects
        clean = []
        for u in extracted:
            bad_domains = [
                "cdninstagram", "fbcdn", "facebook.com",
                "w3.org", "schema.org", "xmlns"
            ]
            if "l.instagram.com" in u:
                u = self.unshorten_url(u)

            if not any(bad in u.lower() for bad in bad_domains) and "instagram.com" not in u.lower():
                unshortened = self.unshorten_url(u)
                if unshortened and unshortened not in clean:
                    clean.append(unshortened)

        return clean

    def wait_for_creator_dm(
        self,
        creator_username: str,
        timeout_seconds: int = 50,
        on_status_update: Optional[Callable[[str], None]] = None
    ) -> Optional[str]:
        """
        Poll for the creator's automated ManyChat reply immediately after commenting.
        Checks both Primary Inbox and Pending / Hidden Requests using clean Web API calls.
        """
        if not self.session_id:
            return None

        creator_clean = creator_username.lower().replace("@", "").strip()
        start_time = time.time()
        notified_button = False

        print(f"[POLL] Listening for ManyChat DM from @{creator_clean} (Timeout: {timeout_seconds}s)...")

        while time.time() - start_time < timeout_seconds:
            try:
                threads_to_check = []

                # 1. Fetch Primary Inbox
                try:
                    inbox_url = "https://www.instagram.com/api/v1/direct_v2/inbox/?persistentBadging=true&folder=&limit=15"
                    inbox_resp = self.session.get(inbox_url, headers=self._get_read_headers(), timeout=8)
                    if inbox_resp.status_code == 200 and "json" in inbox_resp.headers.get("content-type", ""):
                        threads_to_check.extend(inbox_resp.json().get("inbox", {}).get("threads", []))
                    elif inbox_resp.status_code in (401, 403):
                        print("[ERROR] Instagram Session Expired! Please update INSTAGRAM_SESSION_ID.")
                except Exception as e:
                    print(f"[WARN] Error fetching main inbox: {e}")

                # 2. Fetch Pending Inbox
                try:
                    pending_url = "https://www.instagram.com/api/v1/direct_v2/pending_inbox/?persistentBadging=true"
                    pending_resp = self.session.get(pending_url, headers=self._get_read_headers(), timeout=8)
                    if pending_resp.status_code == 200 and "json" in pending_resp.headers.get("content-type", ""):
                        threads_to_check.extend(pending_resp.json().get("inbox", {}).get("threads", []))
                except Exception as e:
                    print(f"[WARN] Error fetching pending inbox: {e}")

                # 3. Search through gathered threads
                for t in threads_to_check:
                    users = [u.get("username", "").lower() for u in t.get("users", [])]
                    is_match = (creator_clean in users) or any(creator_clean in u for u in users if u) or any(u in creator_clean for u in users if u)

                    # Also match if this is the newest thread received within the last 2 minutes
                    if not is_match and t == threads_to_check[0] and (time.time() - start_time < 25):
                        last_act = (t.get("last_activity_at") or 0) / 1000000.0
                        if time.time() - last_act < 120:
                            is_match = True

                    if is_match:
                        thread_id = t.get("thread_id")
                        items = []
                        if thread_id:
                            try:
                                t_url = f"https://www.instagram.com/api/v1/direct_v2/threads/{thread_id}/"
                                t_resp = self.session.get(t_url, headers=self._get_read_headers(), timeout=8)
                                if t_resp.status_code == 200:
                                    items = t_resp.json().get("thread", {}).get("items", [])
                            except Exception as e:
                                print(f"[WARN] Error fetching thread items: {e}")

                        if not items:
                            items = t.get("items", [])

                        # Check for verified link
                        for item in items[:6]:
                            if item.get("is_sent_by_viewer", False):
                                continue
                            urls = self.extract_urls_from_item(item)
                            if urls:
                                print(f"[SUCCESS] Intercepted creator DM link from @{creator_clean}: {urls[0]}")
                                return urls[0]

                        # If creator sent a postback button requiring interaction on phone
                        if not notified_button and on_status_update:
                            for item in items[:2]:
                                if item.get("item_type") == "placeholder" or (item.get("generic_xma") and any(b.get("cta_type") == "postback" for b in item.get("generic_xma", [{}])[0].get("cta_buttons", []))):
                                    on_status_update(f"📱 Creator ManyChat sent an interactive button! Tap it in your Instagram app...")
                                    notified_button = True
                                    break

            except Exception as e:
                print(f"[WARN] DM polling exception: {e}")

            time.sleep(3)

        print(f"[TIMEOUT] No DM link captured from @{creator_clean} within {timeout_seconds}s.")
        return None

    def scan_inbox(self) -> List[Dict[str, Any]]:
        """Scan Instagram Direct Inbox and Pending Requests for unparsed creator messages and links."""
        if not self.session_id:
            return []

        threads = []

        # Check main inbox
        try:
            inbox_url = "https://www.instagram.com/api/v1/direct_v2/inbox/?persistentBadging=true&folder=&limit=25"
            r = self.session.get(inbox_url, headers=self._get_read_headers(), timeout=10)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                threads.extend(r.json().get("inbox", {}).get("threads", []))
        except Exception:
            pass

        # Check pending inbox
        try:
            pending_url = "https://www.instagram.com/api/v1/direct_v2/pending_inbox/?persistentBadging=true"
            r = self.session.get(pending_url, headers=self._get_read_headers(), timeout=10)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                threads.extend(r.json().get("inbox", {}).get("threads", []))
        except Exception:
            pass

        extracted_items = []

        for thread in threads[:8]:
            users = [u.get("username") for u in thread.get("users", [])]
            creator = users[0] if users else "Creator"
            thread_id = thread.get("thread_id")
            items = thread.get("items", [])

            has_placeholder = any(it.get("item_type") == "placeholder" for it in items[:4])
            if has_placeholder and thread_id:
                try:
                    t_url = f"https://www.instagram.com/api/v1/direct_v2/threads/{thread_id}/"
                    t_resp = self.session.get(t_url, headers=self._get_read_headers(), timeout=6)
                    if t_resp.status_code == 200:
                        items = t_resp.json().get("thread", {}).get("items", [])
                except Exception:
                    pass

            for item in items[:4]:
                msg_id = item.get("message_id") or item.get("item_id")
                if not msg_id or msg_id in self.processed_ids:
                    continue

                if item.get("is_sent_by_viewer", False):
                    continue

                urls = self.extract_urls_from_item(item)
                target_url = urls[0] if urls else None

                # Fallback for plain text search instructions
                text = item.get("text", "") or ""
                if not target_url and len(text) > 20 and any(w in text.lower() for w in ["search for", "chrome webstore", "check out"]):
                    from src.link_resolver import LinkResolver
                    resolver = LinkResolver()
                    target_url = resolver.search_official_link(text)

                if target_url:
                    print(f"[INFO] Processing DM from @{creator}: {target_url}")
                    deep_res = self.web_extractor.extract_deep_resource(target_url, creator=creator)
                    if deep_res:
                        saved_path = self.writer.save_deep_resource(deep_res)
                        self.processed_ids.add(msg_id)
                        extracted_items.append({
                            "creator": creator,
                            "resource_name": deep_res.resource_name,
                            "category": deep_res.category,
                            "url": deep_res.website_url,
                            "path": str(saved_path)
                        })
                else:
                    self.processed_ids.add(msg_id)

        self._save_processed_ids()
        return extracted_items
