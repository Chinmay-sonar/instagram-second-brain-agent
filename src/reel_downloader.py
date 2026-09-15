import os
import subprocess
import shutil
import uuid
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List
import requests
import yt_dlp

from src.config import TEMP_DIR, INSTAGRAM_SESSION_ID

@dataclass
class ReelData:
    url: str
    creator: str = "Unknown"
    caption: str = ""
    title: str = ""
    duration: float = 0.0
    media_type: str = "video"  # "video", "carousel", "photo"
    creator_id: Optional[str] = None
    video_path: Optional[Path] = None
    audio_path: Optional[Path] = None
    keyframes: List[Path] = field(default_factory=list)
    session_id: str = ""

    def cleanup(self):
        """Clean up downloaded media files for this session."""
        session_folder = TEMP_DIR / self.session_id
        if session_folder.exists():
            shutil.rmtree(session_folder, ignore_errors=True)

class ReelDownloader:
    def __init__(self):
        self.temp_dir = TEMP_DIR
        self.session_id_ig = INSTAGRAM_SESSION_ID
        self.user_id = self.session_id_ig.split("%3A")[0] if "%3A" in self.session_id_ig else "72104539753"

    def extract_shortcode(self, url: str) -> Optional[str]:
        """Extract Instagram shortcode from reel/post URL."""
        match = re.search(r'(?:reel|reels|p)/([A-Za-z0-9_-]+)', url)
        return match.group(1) if match else None

    def _fetch_ig_api_info(self, shortcode: str) -> Optional[dict]:
        """Fetch full media details directly from Instagram's native API."""
        from src.instagram_commenter import shortcode_to_media_id
        try:
            m_id = shortcode_to_media_id(shortcode)
            res = requests.get(
                f"https://www.instagram.com/api/v1/media/{m_id}/info/",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "X-IG-App-ID": "936619743392459",
                    "X-Requested-With": "XMLHttpRequest",
                    "Cookie": f"sessionid={self.session_id_ig}; ds_user_id={self.user_id}"
                },
                timeout=8
            )
            if res.status_code == 200:
                items = res.json().get("items", [])
                if items:
                    return items[0]
        except Exception as e:
            print(f"[WARN] Failed fetching IG API info: {e}")
        return None

    def download_reel(self, url: str, extract_frames: bool = True, num_frames: int = 6) -> ReelData:
        """
        Download Instagram Reel, Carousel, or Post metadata, media, and visual frames/slides.
        """
        session_id = f"media_{uuid.uuid4().hex[:8]}"
        session_folder = self.temp_dir / session_id
        session_folder.mkdir(parents=True, exist_ok=True)

        shortcode = self.extract_shortcode(url)
        api_item = self._fetch_ig_api_info(shortcode) if shortcode else None

        creator = "Unknown"
        caption = ""
        creator_id = None
        media_type = "video"
        keyframes: List[Path] = []
        downloaded_video: Optional[Path] = None
        duration = 0.0

        if api_item:
            creator = api_item.get("user", {}).get("username") or creator
            creator_id = str(api_item.get("user", {}).get("pk") or api_item.get("user", {}).get("id") or "")
            caption = (api_item.get("caption") or {}).get("text", "")
            raw_type = api_item.get("media_type")

            # Case A: Carousel Album (media_type == 8)
            if raw_type == 8:
                media_type = "carousel"
                carousel_media = api_item.get("carousel_media", [])
                print(f"[INFO] Detected Carousel post with {len(carousel_media)} slides.")
                for idx, slide in enumerate(carousel_media):
                    candidates = slide.get("image_versions2", {}).get("candidates", [])
                    if candidates:
                        img_url = candidates[0].get("url")
                        if img_url:
                            slide_path = session_folder / f"slide_{idx+1}.jpg"
                            try:
                                r = requests.get(img_url, timeout=10)
                                if r.status_code == 200:
                                    slide_path.write_bytes(r.content)
                                    keyframes.append(slide_path)
                            except Exception as e:
                                print(f"[WARN] Failed to download slide {idx+1}: {e}")

            # Case B: Single Photo (media_type == 1)
            elif raw_type == 1:
                media_type = "photo"
                candidates = api_item.get("image_versions2", {}).get("candidates", [])
                if candidates:
                    img_url = candidates[0].get("url")
                    if img_url:
                        photo_path = session_folder / "slide_1.jpg"
                        try:
                            r = requests.get(img_url, timeout=10)
                            if r.status_code == 200:
                                photo_path.write_bytes(r.content)
                                keyframes.append(photo_path)
                        except Exception as e:
                            print(f"[WARN] Failed to download photo: {e}")

            # Case C: Video / Reel (media_type == 2)
            elif raw_type == 2:
                media_type = "video"
                duration = float(api_item.get("video_duration") or 0.0)

        # If not a carousel/photo or we still need video frames for a reel, use yt-dlp
        if media_type == "video":
            ydl_opts = {
                'outtmpl': str(session_folder / "video.%(ext)s"),
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': False,
                'socket_timeout': 25,
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if info:
                        if creator == "Unknown":
                            creator = info.get('uploader') or info.get('uploader_id') or "Unknown"
                        if not caption:
                            caption = info.get('description') or info.get('title') or ""
                        if duration <= 0:
                            duration = float(info.get('duration') or 0.0)

                        for f in session_folder.glob("video.*"):
                            if f.suffix.lower() in ['.mp4', '.mov', '.webm', '.mkv']:
                                downloaded_video = f
                                break
            except Exception as e:
                print(f"[WARN] yt-dlp download failed: {e}")

            # Extract keyframes if video was downloaded
            if downloaded_video and downloaded_video.exists() and extract_frames:
                keyframes = self._extract_keyframes(downloaded_video, session_folder, duration, num_frames)

        return ReelData(
            url=url,
            creator=creator,
            creator_id=creator_id,
            caption=caption,
            title=caption.split("\n")[0][:80] if caption else "Instagram Resource",
            duration=duration,
            media_type=media_type,
            video_path=downloaded_video,
            keyframes=keyframes,
            session_id=session_id
        )

    def _extract_keyframes(self, video_path: Path, output_dir: Path, duration: float, count: int) -> List[Path]:
        """Extract evenly distributed frames across the video using ffmpeg."""
        frames: List[Path] = []
        if duration <= 0:
            duration = 15.0

        step = max(1.0, (duration - 1.0) / max(1, count))
        timestamps = [min(duration - 0.5, 0.5 + i * step) for i in range(count)]

        for i, ts in enumerate(timestamps):
            frame_path = output_dir / f"frame_{i+1}.jpg"
            cmd = [
                "ffmpeg",
                "-y",
                "-ss", str(ts),
                "-i", str(video_path),
                "-vframes", "1",
                "-q:v", "2",
                str(frame_path)
            ]
            try:
                res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if frame_path.exists() and frame_path.stat().st_size > 1000:
                    frames.append(frame_path)
            except Exception as e:
                print(f"[WARN] Failed to extract frame at {ts}s: {e}")

        return frames
