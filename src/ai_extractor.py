import json
import base64
import requests
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from openai import OpenAI

from src.config import GEMINI_API_KEY, NVIDIA_API_KEY, CATEGORIES
from src.reel_downloader import ReelData
from src.link_resolver import LinkResolver

class ExtractedResource(BaseModel):
    category: str = Field(description="One of: UI-UX, Internships, Hackathons, AI-Agents, Roadmaps, Dev-Tools")
    resource_name: str = Field(description="Official name of the tool, platform, program, course, or repo")
    website_url: Optional[str] = Field(default=None, description="Direct URL to the tool, course, or opportunity")
    summary: str = Field(description="2-3 sentence clear summary of what this resource is and why it is useful")
    humanized_use_case: str = Field(default="", description="SUPER SHORT (10-14 words) conversational use case for Notion table")
    sub_categories: List[str] = Field(default_factory=list, description="2-3 specific category badge pills like 'Course' or 'AI CodeEditor'")
    subscription_tier: str = Field(default="Freemium", description="Free, Limited, Paid, or Freemium")
    resource_type: str = Field(default="Tool", description="Course, Roadmap, Tool, Internship, Hackathon, or Dev-Tool")
    provider: Optional[str] = Field(default=None, description="Platform/Provider (e.g. Coursera, Udemy, YouTube, Harvard, freeCodeCamp, MIT, Google)")
    credential_status: Optional[str] = Field(default="None", description="Free Certificate, Paid Certificate, Audit Free, or None")
    duration: Optional[str] = Field(default=None, description="Estimated duration or weeks if course/roadmap")
    syllabus_modules: List[str] = Field(default_factory=list, description="Key modules, phases, or topics if course/roadmap")
    key_features: List[str] = Field(default_factory=list, description="Top 2-4 key features or highlights")
    actionable_steps: List[str] = Field(default_factory=list, description="How to use it, free tier details, or how to apply")
    pricing_or_eligibility: Optional[str] = Field(default=None, description="Pricing tier or eligibility criteria")
    deadline: Optional[str] = Field(default=None, description="Application or registration deadline if applicable")
    tags: List[str] = Field(default_factory=list, description="Relevant tags for Obsidian search")
    confidence: str = Field(default="Medium", description="High, Medium, or Low")

class AIExtractor:
    def __init__(self):
        self.gemini_key = GEMINI_API_KEY
        self.nvidia_key = NVIDIA_API_KEY
        self.resolver = LinkResolver()

    def _encode_image(self, image_path: Path) -> str:
        """Read image and convert to base64 string."""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def extract(self, reel_data: ReelData) -> ExtractedResource:
        """
        Analyze carousel slides, photo post, or reel visual keyframes + caption + metadata
        using Gemini Flash multimodal vision with NVIDIA NIM backup.
        """
        prompt = self._build_prompt(reel_data)

        # 1. Try Gemini Flash with Multimodal Vision
        if self.gemini_key:
            try:
                result = self._extract_with_gemini(prompt, reel_data.keyframes)
                if result:
                    return self._post_process(result)
            except Exception as e:
                print(f"[WARN] Gemini extraction failed: {e}. Falling back to NVIDIA NIM...")

        # 2. Fallback to NVIDIA NIM
        if self.nvidia_key:
            try:
                result = self._extract_with_nvidia(prompt, reel_data.keyframes)
                if result:
                    return self._post_process(result)
            except Exception as e:
                print(f"[ERROR] NVIDIA NIM extraction failed: {e}")

        # Fallback dummy object if both fail
        fallback = ExtractedResource(
            category="Dev-Tools",
            resource_name=reel_data.title or "Tech Resource",
            website_url=None,
            summary=reel_data.caption[:250] if reel_data.caption else "Resource shared via Instagram.",
            key_features=["Extracted from Instagram"],
            actionable_steps=["Check the original post for details"],
            tags=["instagram", "resource"],
            confidence="Low"
        )
        return self._post_process(fallback)

    def _build_prompt(self, reel_data: ReelData) -> str:
        media_context = f"Media Type: {reel_data.media_type.upper()} ({len(reel_data.keyframes)} slides/frames attached)"
        return f"""You are an expert AI Tech Scout, Course Curator, and Knowledge Architect.
Your job is to analyze this Instagram {reel_data.media_type.upper()} and extract the high-value technical resource, course, tool, internship, hackathon, or roadmap being discussed.

IMPORTANT CONTEXT ABOUT THIS POST:
- Creator: @{reel_data.creator}
- {media_context}
- Caption & Description:
\"\"\"{reel_data.caption}\"\"\"

CRITICAL INSTRUCTIONS FOR 'COMMENT FOR LINK' & MULTI-SLIDE POSTS:
1. Examine EVERY ATTACHED IMAGE (carousel slides or video keyframes).
2. Check slide headers, browser address bars, logos, course platforms (Coursera, Udemy, YouTube, Harvard, etc.), repo titles, or UI screens.
3. Identify the EXACT resource:
   - If it's a COURSE or LEARNING PATH: Identify the course name, provider/platform (Coursera, Udemy, YouTube, Harvard, MIT, etc.), certificate status (Free Certificate, Paid Certificate, Audit Free), and curriculum modules.
   - Categorize it strictly as one of:
     * "Roadmaps" (Courses, bootcamps, learning roadmaps, tutorials, cheat sheets)
     * "AI-Agents" (Agent frameworks, LLM tools, AI dev libraries)
     * "UI-UX" (Figma plugins, design tools, UI kits, design inspiration)
     * "Internships" (Job opportunities, student programs, fellowships)
     * "Hackathons" (Competitions, hackathons, bounties)
     * "Dev-Tools" (General dev utilities, APIs, VSCode extensions, open source repos)

Return ONLY a valid JSON object matching this exact schema:
{{
  "category": "Roadmaps" | "AI-Agents" | "UI-UX" | "Internships" | "Hackathons" | "Dev-Tools",
  "resource_type": "Course" | "Roadmap" | "Tool" | "Internship" | "Hackathon" | "Dev-Tool",
  "resource_name": "Exact Name of the Tool, Course, or Opportunity",
  "provider": "Platform/Provider name (e.g. Coursera, Udemy, YouTube, Harvard, Google, GitHub) or null",
  "credential_status": "Free Certificate" | "Paid Certificate" | "Audit Free" | "Certificate of Completion" | "None",
  "duration": "Duration estimate (e.g. '4 Weeks', '10 Hours', 'Self-paced') or null",
  "syllabus_modules": ["Module 1: ...", "Module 2: ..."],
  "website_url": "Direct official website or course URL if visible or known, else null",
  "summary": "2-3 crisp sentences explaining what this resource does and why it is valuable",
  "key_features": ["Highlight 1", "Highlight 2", "Highlight 3"],
  "actionable_steps": ["Step 1 on how to start/enroll", "Step 2"],
  "pricing_or_eligibility": "Free / Freemium / Open Source / Student Only / Paid",
  "deadline": "YYYY-MM-DD or text if a deadline applies, else null",
  "tags": ["tag1", "tag2", "tag3"],
  "confidence": "High" | "Medium" | "Low"
}}"""

    def _extract_with_gemini(self, prompt: str, keyframes: List[Path]) -> Optional[ExtractedResource]:
        models_to_try = ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.7-flash"]
        parts: List[Dict[str, Any]] = [{"text": prompt}]

        # Attach up to 10 keyframes / carousel slides
        for frame_path in keyframes[:10]:
            if frame_path.exists():
                b64_data = self._encode_image(frame_path)
                parts.append({
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": b64_data
                    }
                })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2
            }
        }

        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.gemini_key}"
            try:
                resp = requests.post(url, json=payload, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        parsed = json.loads(raw_text)
                        return ExtractedResource(**parsed)
            except Exception as e:
                print(f"[WARN] Error with {model_name}: {e}. Trying next...")

        return None

    def _extract_with_nvidia(self, prompt: str, keyframes: List[Path]) -> Optional[ExtractedResource]:
        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=self.nvidia_key
        )

        messages: List[Dict[str, Any]] = []
        user_content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]

        has_images = False
        for frame_path in keyframes[:4]:
            if frame_path.exists():
                b64 = self._encode_image(frame_path)
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                })
                has_images = True

        messages.append({"role": "user", "content": user_content if has_images else prompt})
        model = "meta/llama-3.2-11b-vision-instruct" if has_images else "deepseek-ai/deepseek-v4-flash-0731"

        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"} if not has_images else None,
            max_tokens=1200,
            temperature=0.2
        )

        content = completion.choices[0].message.content or ""
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        parsed = json.loads(content)
        return ExtractedResource(**parsed)

    def generate_humanized_notion_metadata(self, resource_name: str, summary: str, category: str) -> Dict[str, Any]:
        """
        Use NVIDIA NIM to generate a super-short, conversational 10-14 word use case,
        colored sub-category pills, and subscription tier matching the Notion database layout.
        """
        system_prompt = (
            "You are an expert developer curator for a Notion database. "
            "Write a SUPER SHORT (max 10-14 words), punchy, conversational, humanized Use Case. "
            "No corporate fluff, no AI buzzwords. Explain it like one dev recommending to another. "
            "Examples: 'AI-powered IDE for coding, autocompletion, and code refactoring.' "
            "or 'Official Harvard CS50 introduction to computer science and programming.' "
            "Also provide 2 sub-category badges (e.g. 'Course', 'Certifications', 'AI Agent') and a subscription pill ('Free', 'Limited', 'Paid', or 'Freemium'). "
            "Output JSON with keys: 'humanized_use_case', 'sub_categories', 'subscription_tier'."
        )
        user_prompt = f"Tool/Opportunity: {resource_name}\nCategory: {category}\nContext: {summary}"

        # 1. Try NVIDIA NIM
        if self.nvidia_key:
            try:
                headers = {"Authorization": f"Bearer {self.nvidia_key}", "Content-Type": "application/json"}
                payload = {
                    "model": "meta/llama-3.2-11b-vision-instruct",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 120
                }
                resp = requests.post("https://integrate.api.nvidia.com/v1/chat/completions", headers=headers, json=payload, timeout=5)
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    return json.loads(content)
            except Exception as e:
                print(f"[WARN] NVIDIA humanizer timeout/error: {e}. Falling back to Gemini...")

        # 2. Fallback to Gemini Flash
        if self.gemini_key:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={self.gemini_key}"
                payload = {
                    "contents": [{"parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]}],
                    "generationConfig": {"response_mime_type": "application/json", "temperature": 0.2}
                }
                resp = requests.post(url, json=payload, timeout=25)
                if resp.status_code == 200:
                    raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                    return json.loads(raw_text)
            except Exception as e:
                print(f"[WARN] Gemini humanizer error: {e}")

        fallback_text = summary if len(summary) <= 120 else summary.split(". ")[0] + "."
        return {
            "humanized_use_case": fallback_text or f"Useful {category} resource for tech builders.",
            "sub_categories": [category],
            "subscription_tier": "Free"
        }

    def _post_process(self, res: ExtractedResource) -> ExtractedResource:
        """Resolve missing URLs and generate Notion-style humanized metadata."""
        if res.category not in CATEGORIES:
            res.category = "Roadmaps" if res.resource_type == "Course" else "Dev-Tools"

        needs_search = False
        if not res.website_url:
            needs_search = True
        elif any(bad in res.website_url.lower() for bad in ["instagram.com", "linkin.bio", "bit.ly", "t.co", "example.com"]):
            unshortened = self.resolver.unshorten_url(res.website_url)
            if "instagram.com" in unshortened:
                needs_search = True
            else:
                res.website_url = unshortened

        if needs_search and res.resource_name and len(res.resource_name.split()) <= 5:
            official_link = self.resolver.search_official_link(res.resource_name, res.category)
            if official_link:
                res.website_url = official_link

        meta = self.generate_humanized_notion_metadata(res.resource_name, res.summary, res.category)
        res.humanized_use_case = meta.get("humanized_use_case", res.summary)
        res.sub_categories = meta.get("sub_categories", [res.category])
        res.subscription_tier = meta.get("subscription_tier", "Freemium")

        # If it's a course, ensure 'Course' is in sub_categories
        if res.resource_type == "Course" and "Course" not in res.sub_categories:
            res.sub_categories.insert(0, "Course")

        return res
