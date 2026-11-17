import asyncio
import json
import re
import time
import uuid
import requests
from urllib.parse import urlparse, parse_qs, unquote
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

from src.config import INSTAGRAM_SESSION_ID, BASE_DIR
from src.web_extractor import WebExtractor, DeepResource
from src.obsidian_writer import ObsidianWriter

CACHE_FILE = BASE_DIR / "processed_dms.json"

class ActiveDMJob:
    def __init__(
        self,
        job_id: str,
        creator_username: str,
        creator_id: Optional[str] = None,
        timeout_seconds: int = 90,
        on_status_update: Optional[Callable[[str], None]] = None
    ):
        self.job_id = job_id
        self.creator_username = creator_username.lower().replace("@", "").strip()
        self.creator_id = str(creator_id).strip() if creator_id else None
        self.timeout_seconds = timeout_seconds
        self.on_status_update = on_status_update
        self.created_at = time.time()
        self.event = asyncio.Event()
        self.result_urls: List[str] = []
        self.timed_out = False
        self.notified_button = False

class InstagramDMWatcher:
    def __init__(self):
        self.session_id = INSTAGRAM_SESSION_ID
        self.user_id = self.session_id.split("%3A")[0] if "%3A" in self.session_id else "72104539753"
        self.web_extractor = WebExtractor()
        self.writer = ObsidianWriter()
        self.processed_ids = self._load_processed_ids()
        self.session = requests.Session()
        self.csrf_token: Optional[str] = None
        self.active_jobs: Dict[str, ActiveDMJob] = {}
        self._poller_task: Optional[asyncio.Task] = None
        self.on_session_expired: Optional[Callable[[], None]] = None
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

    def update_session_id(self, new_session_id: str):
        """Update session cookie dynamically and refresh web headers."""
        self.session_id = new_session_id.strip()
        self.user_id = self.session_id.split("%3A")[0] if "%3A" in self.session_id else self.user_id
        self._init_session()

    def approve_thread(self, thread_id: str) -> bool:
        """
        Programmatically approve a pending message request thread from Instagram's pending requests.
        Ensures ManyChat links are readable without manual human inbox intervention.
        """
        if not thread_id:
            return False
        try:
            url = f"https://www.instagram.com/api/v1/direct_v2/threads/{thread_id}/approve/"
            resp = self.session.post(url, headers=self._get_web_headers(), timeout=8)
            if resp.status_code == 200:
                print(f"[SUCCESS] Approved pending message request thread {thread_id}")
                return True
        except Exception as e:
            print(f"[WARN] Failed to approve thread {thread_id}: {e}")
        return False

    def _poll_once(self) -> None:
        """
        Single unified polling sweep for all active jobs across Primary and Pending inboxes.
        Uses exact creator matching (username or pk) and automatically approves pending requests.
        """
        if not self.active_jobs or not self.session_id:
            return

        now = time.time()
        # 1. Check timeouts for active jobs
        for job_id, job in list(self.active_jobs.items()):
            if now - job.created_at >= job.timeout_seconds:
                print(f"[TIMEOUT] Job for @{job.creator_username} reached {job.timeout_seconds}s limit.")
                job.timed_out = True
                job.event.set()
                if job_id in self.active_jobs:
                    del self.active_jobs[job_id]

        if not self.active_jobs:
            return

        threads_to_check = []
        pending_thread_ids = set()

        # 2. Fetch Primary Inbox
        try:
            inbox_url = "https://www.instagram.com/api/v1/direct_v2/inbox/?persistentBadging=true&folder=&limit=15"
            inbox_resp = self.session.get(inbox_url, headers=self._get_read_headers(), timeout=8)
            if inbox_resp.status_code == 200 and "json" in inbox_resp.headers.get("content-type", ""):
                threads_to_check.extend(inbox_resp.json().get("inbox", {}).get("threads", []))
            elif inbox_resp.status_code in (401, 403) or "not-logged-in" in inbox_resp.text:
                print("[ERROR] Instagram Session Expired! Please update INSTAGRAM_SESSION_ID.")
                if self.on_session_expired:
                    self.on_session_expired()
                return
        except Exception as e:
            print(f"[WARN] Error fetching main inbox: {e}")

        # 3. Fetch Pending Inbox
        try:
            pending_url = "https://www.instagram.com/api/v1/direct_v2/pending_inbox/?persistentBadging=true"
            pending_resp = self.session.get(pending_url, headers=self._get_read_headers(), timeout=8)
            if pending_resp.status_code == 200 and "json" in pending_resp.headers.get("content-type", ""):
                p_threads = pending_resp.json().get("inbox", {}).get("threads", [])
                for pt in p_threads:
                    tid = pt.get("thread_id")
                    if tid:
                        pending_thread_ids.add(str(tid))
                threads_to_check.extend(p_threads)
        except Exception as e:
            print(f"[WARN] Error fetching pending inbox: {e}")

        # 4. Strict Matching against gathered threads
        for t in threads_to_check:
            thread_id = t.get("thread_id")
            users = t.get("users", [])
            usernames = [u.get("username", "").lower().strip() for u in users]
            user_pks = [str(u.get("pk", "")) for u in users]

            # Check every active job against this thread
            for job_id, job in list(self.active_jobs.items()):
                # Strict matching: target creator must be in the thread users
                is_match = (job.creator_username in usernames) or (job.creator_id and job.creator_id in user_pks)
                if not is_match:
                    continue

                # Auto-approve if thread is in pending inbox
                if str(thread_id) in pending_thread_ids:
                    self.approve_thread(thread_id)

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

                # Extract URLs from recent incoming messages
                for item in items[:6]:
                    if item.get("is_sent_by_viewer", False):
                        continue
                    urls = self.extract_urls_from_item(item)
                    if urls:
                        print(f"[SUCCESS] Strictly matched creator DM from @{job.creator_username}: {urls[0]}")
                        job.result_urls = urls
                        job.event.set()
                        if job_id in self.active_jobs:
                            del self.active_jobs[job_id]
                        break

                # Inform user if interactive ManyChat prompt is detected
                if not job.event.is_set() and not job.notified_button and job.on_status_update:
                    for item in items[:2]:
                        if item.get("item_type") == "placeholder" or (item.get("generic_xma") and any(b.get("cta_type") == "postback" for b in item.get("generic_xma", [{}])[0].get("cta_buttons", []))):
                            job.on_status_update(f"📱 Creator ManyChat sent an interactive button! Tap it in your Instagram app...")
                            job.notified_button = True
                            break

    async def _run_polling_loop(self):
        """Asynchronous worker that drives unified polling every 3.5s as long as active jobs exist."""
        while self.active_jobs:
            try:
                await asyncio.to_thread(self._poll_once)
            except Exception as e:
                print(f"[WARN] Error in unified DM polling loop: {e}")
            await asyncio.sleep(3.5)
        self._poller_task = None

    async def wait_for_creator_dm_async(
        self,
        creator_username: str,
        creator_id: Optional[str] = None,
        timeout_seconds: int = 90,
        on_status_update: Optional[Callable[[str], None]] = None
    ) -> List[str]:
        """
        Asynchronously register a DM job and wait for the matching creator's DM.
        Runs in parallel across multiple reels with a single, shared background polling engine.
        """
        job_id = f"{creator_username}_{time.time()}_{uuid.uuid4().hex[:6]}"
        job = ActiveDMJob(
            job_id=job_id,
            creator_username=creator_username,
            creator_id=creator_id,
            timeout_seconds=timeout_seconds,
            on_status_update=on_status_update
        )
        self.active_jobs[job_id] = job

        # Start unified poller task if not already running
        if not self._poller_task or self._poller_task.done():
            self._poller_task = asyncio.create_task(self._run_polling_loop())

        await job.event.wait()
        if job.timed_out:
            return []
        return job.result_urls

    def wait_for_creator_dm(
        self,
        creator_username: str,
        timeout_seconds: int = 90,
        on_status_update: Optional[Callable[[str], None]] = None
    ) -> Optional[str]:
        """Synchronous polling fallback for legacy calls."""
        start_time = time.time()
        creator_clean = creator_username.lower().replace("@", "").strip()
        while time.time() - start_time < timeout_seconds:
            self._poll_once()
            time.sleep(3.5)
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
