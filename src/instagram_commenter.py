import re
import json
import requests
from typing import Optional, Tuple
from urllib.parse import urlparse

from src.config import INSTAGRAM_SESSION_ID, GEMINI_API_KEY

ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'

def shortcode_to_media_id(shortcode: str) -> int:
    """Convert Instagram base64 shortcode (e.g. Dc_tXtcs2-Q) to numeric media ID."""
    media_id = 0
    for char in shortcode:
        media_id = media_id * 64 + ALPHABET.index(char)
    return media_id

def extract_shortcode(url: str) -> Optional[str]:
    """Extract reel/post shortcode from URL."""
    match = re.search(r'/(?:reel|reels|p)/([A-Za-z0-9_-]+)', url)
    return match.group(1) if match else None

class InstagramCommenter:
    def __init__(self):
        self.session_id = INSTAGRAM_SESSION_ID
        self.user_id = self.session_id.split("%3A")[0] if "%3A" in self.session_id else "72104539753"
        self.gemini_key = GEMINI_API_KEY
        self.session = requests.Session()
        self.csrf_token: Optional[str] = None
        self._init_session()

    def _init_session(self):
        """Warm up session and grab active CSRF token quickly via HEAD request."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "X-IG-App-ID": "936619743392459",
            "Cookie": f"sessionid={self.session_id}; ds_user_id={self.user_id}"
        }
        self.session.headers.update(headers)
        try:
            resp = self.session.head("https://www.instagram.com/", timeout=5)
            self.csrf_token = self.session.cookies.get("csrftoken")
        except Exception as e:
            print(f"[WARN] Failed to fetch Instagram CSRF: {e}")

    def detect_trigger_keyword(self, caption: str) -> str:
        """
        Use Gemini to inspect the reel caption and identify what exact keyword
        the creator asked viewers to comment (e.g. 'ROADMAP', 'AI', 'LINK').
        """
        if not caption:
            return "Link please ❤️"

        prompt = f"""Analyze this Instagram Reel caption from a tech creator:
\"\"\"{caption}\"\"\"

TASK:
Determine if the creator is asking viewers to comment a specific keyword to trigger a ManyChat / automated DM (e.g. "Comment 'AI'", "Comment 'ROADMAP'", "Comment 'DEV'").

RULES:
1. If the creator specified a single word or phrase to comment (in quotes or uppercase), output ONLY that word (e.g. "AI" or "ROADMAP" or "ASTRA").
2. If the creator generically said "comment for link" or "comment karo", output: "Link please ❤️"
3. Output ONLY the comment text string. Nothing else."""

        models = ["gemini-3.5-flash", "gemini-3.1-flash-lite"]
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 30}
        }

        for m in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={self.gemini_key}"
            try:
                r = requests.post(url, json=payload, timeout=12)
                if r.status_code == 200:
                    text = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                    clean_text = text.replace('"', '').replace("'", "").strip()
                    if clean_text and clean_text.lower() not in ("none", "null", "no keyword", "n/a", "no", "nothing"):
                        return clean_text
            except Exception:
                continue

        # Regex fallback
        match = re.search(r'comment\s+["\']([A-Za-z0-9_]+)["\']', caption, re.IGNORECASE)
        if match:
            return match.group(1).upper()

        return "Link please ❤️"

    def post_comment(self, reel_url: str, caption: Optional[str] = None) -> Tuple[bool, str, str]:
        """
        Post the detected trigger comment on the reel.
        Returns: (success: bool, comment_posted: str, status_or_error: str)
        """
        shortcode = extract_shortcode(reel_url)
        if not shortcode:
            return False, "", "Invalid Reel URL (no shortcode found)"

        media_id = shortcode_to_media_id(shortcode)
        comment_text = self.detect_trigger_keyword(caption or "")

        if not self.csrf_token:
            self._init_session()

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "X-IG-App-ID": "936619743392459",
            "X-CSRFToken": self.csrf_token or "",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://www.instagram.com/p/{shortcode}/",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": f"sessionid={self.session_id}; ds_user_id={self.user_id}; csrftoken={self.csrf_token or ''}"
        }

        endpoint = f"https://www.instagram.com/api/v1/web/comments/{media_id}/add/"
        data = {"comment_text": comment_text}

        try:
            resp = self.session.post(endpoint, headers=headers, data=data, timeout=12)
            if resp.status_code == 200:
                return True, comment_text, "Comment posted successfully"
            else:
                return False, comment_text, f"Status {resp.status_code}: {resp.text[:150]}"
        except Exception as e:
            return False, comment_text, f"Request failed: {e}"

    def follow_user(self, target_user_id: str) -> Tuple[bool, str]:
        """
        Automatically follow a creator account by numeric user ID.
        Satisfies ManyChat 'Must Follow Account' requirements to unlock resource DMs.
        """
        if not target_user_id:
            return False, "No creator ID provided"

        if not self.csrf_token:
            self._init_session()

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "X-IG-App-ID": "936619743392459",
            "X-CSRFToken": self.csrf_token or "",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.instagram.com/",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": f"sessionid={self.session_id}; ds_user_id={self.user_id}; csrftoken={self.csrf_token or ''}"
        }

        endpoint = f"https://www.instagram.com/api/v1/friendships/create/{target_user_id}/"
        data = {"user_id": str(target_user_id), "radio_type": "wifi-none"}

        try:
            resp = self.session.post(endpoint, headers=headers, data=data, timeout=10)
            if resp.status_code == 200:
                body = resp.json()
                status = body.get("friendship_status", {})
                if status.get("following"):
                    return True, "Following creator"
                elif status.get("outgoing_request"):
                    return True, "Follow request sent"
                return True, "Followed creator successfully"
            else:
                return False, f"Status {resp.status_code}: {resp.text[:100]}"
        except Exception as e:
            return False, f"Follow error: {e}"

