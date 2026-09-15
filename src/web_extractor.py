import json
import re
import requests
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from src.config import GEMINI_API_KEY, CATEGORIES

class DeepResource(BaseModel):
    category: str
    resource_type: str = Field(default="Roadmap", description="Course, Roadmap, Tool, Internship, Hackathon, or Dev-Tool")
    resource_name: str
    provider: Optional[str] = Field(default=None, description="Platform or Provider (Coursera, Udemy, YouTube, Harvard, etc.)")
    credential_status: Optional[str] = Field(default="None", description="Free Certificate, Paid Certificate, Audit Free, or None")
    duration: Optional[str] = Field(default=None, description="Duration or time commitment")
    syllabus_modules: List[str] = Field(default_factory=list, description="List of syllabus modules/phases")
    website_url: str
    summary: str
    humanized_use_case: str = Field(default="", description="10-14 word punchy humanized use case")
    sub_categories: List[str] = Field(default_factory=list, description="Sub-category pills")
    subscription_tier: str = Field(default="Free", description="Free, Limited, Paid, or Freemium")
    detailed_notes_markdown: str
    key_features: List[str] = Field(default_factory=list)
    actionable_steps: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    pricing_or_eligibility: Optional[str] = "Free"
    deadline: Optional[str] = None
    creator: str = "Web"
    source_url: str = ""

class WebExtractor:
    def __init__(self):
        self.gemini_key = GEMINI_API_KEY
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        })

    def unshorten(self, url: str) -> str:
        """Follow redirects to get the real canonical URL."""
        try:
            resp = self.session.head(url, allow_redirects=True, timeout=10)
            return resp.url
        except Exception:
            return url

    def fetch_page_content(self, url: str) -> str:
        """
        Fetch full page content using Jina AI reader (converts any webpage or Notion doc to clean Markdown).
        """
        canonical_url = self.unshorten(url)
        jina_endpoint = f"https://r.jina.ai/{canonical_url}"
        try:
            resp = self.session.get(jina_endpoint, timeout=20)
            if resp.status_code == 200 and len(resp.text) > 100:
                return resp.text
        except Exception as e:
            print(f"[WARN] Jina Reader failed for {url}: {e}. Trying direct fetch...")

        try:
            resp = self.session.get(canonical_url, timeout=15)
            if resp.status_code == 200:
                text = re.sub(r'<script.*?</script>', '', resp.text, flags=re.DOTALL)
                text = re.sub(r'<style.*?</style>', '', text, flags=re.DOTALL)
                clean_text = re.sub(r'<[^>]+>', ' ', text)
                return clean_text[:10000]
        except Exception as e:
            print(f"[ERROR] Direct fetch failed for {url}: {e}")

        return ""

    def extract_deep_resource(self, url: str, creator: str = "Unknown") -> Optional[DeepResource]:
        """
        Analyze the full extracted webpage or roadmap with Gemini Flash to produce deep, thorough notes.
        """
        canonical_url = self.unshorten(url)
        content = self.fetch_page_content(canonical_url)
        if not content:
            return None

        truncated_content = content[:40000]

        prompt = f"""You are an expert AI Technical Curator, Course Evaluator & Career Mentor.
You are given the full webpage/document content of a technical resource, course, roadmap, tool, or opportunity that a user saved.

CREATOR / SOURCE: @{creator}
DESTINATION URL: {canonical_url}

FULL CONTENT EXTRACTED FROM PAGE:
\"\"\"{truncated_content}\"\"\"

TASK:
Produce a comprehensive, exhaustive, and structured breakdown of this resource.
- If it is a COURSE or LEARNING PATH:
  * Extract the Official Course Title, Provider/Platform (Coursera, Udemy, YouTube, Harvard, MIT, edX, Google, etc.).
  * Identify Certificate Status (Free Certificate, Paid Certificate, Audit Free, None).
  * Extract duration/weeks and every single module/phase with its key topics.
- If it is a ROADMAP or GUIDE:
  * Extract every single stage/phase/module in order with topics and links.
- If it is a TOOL or REPOSITORY:
  * Extract the core purpose, technical stack, key use cases, and how to get started.

Return ONLY a valid JSON object matching this schema:
{{
  "category": "Roadmaps" | "AI-Agents" | "UI-UX" | "Internships" | "Hackathons" | "Dev-Tools",
  "resource_type": "Course" | "Roadmap" | "Tool" | "Internship" | "Hackathon" | "Dev-Tool",
  "resource_name": "Official Title / Name of the Resource or Course",
  "provider": "Platform/Provider name (e.g. Coursera, Udemy, YouTube, Harvard, Google, freeCodeCamp) or null",
  "credential_status": "Free Certificate" | "Paid Certificate" | "Audit Free" | "Certificate of Completion" | "None",
  "duration": "Duration (e.g. '4 Weeks', '12 Hours', 'Self-paced') or null",
  "syllabus_modules": ["Module 1: Title & Topics", "Module 2: Title & Topics"],
  "website_url": "{canonical_url}",
  "summary": "2-3 crisp sentences summarizing the entire resource or course",
  "humanized_use_case": "SUPER SHORT (max 10-14 words), punchy, conversational, humanized Use Case for Notion table. E.g. 'Comprehensive deep learning specialization covering neural networks and Transformers.'",
  "sub_categories": ["Category 1", "Category 2"],
  "subscription_tier": "Free" | "Limited" | "Paid" | "Freemium",
  "detailed_notes_markdown": "Full, beautifully formatted markdown breakdown containing all curriculum stages, topics, books, repositories, modules, and links from the document.",
  "key_features": ["Top highlight 1", "Top highlight 2", "Top highlight 3"],
  "actionable_steps": ["Step 1 to start/enroll", "Step 2", "Step 3"],
  "tags": ["tag1", "tag2", "tag3", "tag4"],
  "pricing_or_eligibility": "Free / Freemium / Paid",
  "deadline": "YYYY-MM-DD or null"
}}"""

        models_to_try = ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.7-flash"]
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2
            }
        }

        for model_name in models_to_try:
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.gemini_key}"
            try:
                resp = requests.post(api_url, json=payload, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        parsed = json.loads(raw_text)
                        parsed["creator"] = creator
                        parsed["source_url"] = canonical_url

                        # Enhance with NVIDIA NIM humanized metadata
                        try:
                            from src.ai_extractor import AIExtractor
                            ai = AIExtractor()
                            meta = ai.generate_humanized_notion_metadata(
                                parsed.get("resource_name", "Technical Resource"),
                                parsed.get("summary", ""),
                                parsed.get("category", "Roadmaps")
                            )
                            parsed["humanized_use_case"] = meta.get("humanized_use_case", parsed.get("summary", "")[:90])
                            parsed["sub_categories"] = meta.get("sub_categories", [parsed.get("category", "Tech")])
                            parsed["subscription_tier"] = meta.get("subscription_tier", "Free")
                        except Exception as e:
                            print(f"[WARN] NVIDIA NIM humanizer fallback for deep resource: {e}")
                            if not parsed.get("humanized_use_case"):
                                parsed["humanized_use_case"] = parsed.get("summary", "")[:90]
                            if not parsed.get("sub_categories"):
                                parsed["sub_categories"] = [parsed.get("category", "Tech")]

                        if parsed.get("resource_type") == "Course" and "Course" not in parsed.get("sub_categories", []):
                            parsed["sub_categories"].insert(0, "Course")

                        return DeepResource(**parsed)
            except Exception as e:
                print(f"[WARN] Gemini extraction error with {model_name}: {e}")

        return None
