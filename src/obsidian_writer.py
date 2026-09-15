import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from src.config import OBSIDIAN_VAULT_PATH, CATEGORIES
from src.ai_extractor import ExtractedResource
from src.reel_downloader import ReelData
from src.web_extractor import DeepResource

SEGMENT_FILES = {
    "UI-UX": "01 - 🎨 UI & UX Resources.md",
    "AI-Agents": "02 - 🤖 AI Tools & Agents.md",
    "Internships": "03 - 💼 Internships & Opportunities.md",
    "Hackathons": "04 - 🏆 Hackathons & Competitions.md",
    "Roadmaps": "05 - 🗺️ Roadmaps & Learning.md",
    "Dev-Tools": "06 - 🛠️ Dev Tools & Utilities.md"
}

class ObsidianWriter:
    def __init__(self, vault_path: Optional[Path] = None):
        self.vault_path = vault_path or OBSIDIAN_VAULT_PATH
        self.resources_dir = self.vault_path / "Resources"
        self._initialize_vault_structure()

    def _initialize_vault_structure(self):
        """Create category subfolders and segment files if they do not exist."""
        self.resources_dir.mkdir(parents=True, exist_ok=True)
        for cat_folder in CATEGORIES.values():
            (self.resources_dir / cat_folder).mkdir(parents=True, exist_ok=True)

        self._sync_all_segment_tables()

    def _sanitize_filename(self, name: str) -> str:
        """Remove invalid filename characters on Windows."""
        clean = re.sub(r'[\\/*?:"<>|]', '', name).strip()
        return clean[:80] or "Untitled Resource"

    def _format_badges(self, sub_cats: List[str], fallback: str = "General") -> str:
        if not sub_cats:
            return f"`{fallback}`"
        return " ".join([f"`{c}`" for c in sub_cats[:3]])

    def save_resource(self, resource: ExtractedResource, reel_data: ReelData) -> Path:
        """Write the extracted resource into a structured Markdown note and update segment table."""
        folder_name = CATEGORIES.get(resource.category, "Dev Tools & Utilities")
        target_folder = self.resources_dir / folder_name
        target_folder.mkdir(parents=True, exist_ok=True)

        safe_name = self._sanitize_filename(resource.resource_name)
        file_path = target_folder / f"{safe_name}.md"

        now_str = datetime.now().strftime("%Y-%m-%d")
        tags_yaml = "\n".join([f"  - {t.strip().replace(' ', '-')}" for t in resource.tags if t.strip()]) or "  - resource"
        features_md = "\n".join([f"- {f}" for f in resource.key_features]) or "- See original post"
        actions_md = "\n".join([f"1. {a}" for a in resource.actionable_steps]) or "1. Visit the resource link below."
        website_link_md = f"[{resource.website_url}]({resource.website_url})" if resource.website_url else "*(Not specified)*"

        # Course specific modules / syllabus
        course_section = ""
        if resource.resource_type == "Course" or resource.provider:
            modules_list = "\n".join([f"- **Module {i+1}:** {m}" for i, m in enumerate(resource.syllabus_modules)]) if resource.syllabus_modules else "- Check course link for complete module list."
            course_section = f"""
### 🎓 Course & Provider Intelligence
| Property | Detail |
| :--- | :--- |
| **Provider / Platform** | `{resource.provider or 'Self-Hosted / Independent'}` |
| **Credential / Certificate** | `{resource.credential_status or 'None'}` |
| **Estimated Duration** | `{resource.duration or 'Self-Paced'}` |
| **Direct Course Link** | {website_link_md} |

### 📚 Syllabus Breakdown
{modules_list}
"""

        content = f"""---
title: "{resource.resource_name}"
category: "{resource.category}"
resource_type: "{resource.resource_type}"
resource_name: "{resource.resource_name}"
provider: "{resource.provider or ''}"
credential_status: "{resource.credential_status or 'None'}"
duration: "{resource.duration or ''}"
url: "{resource.website_url or ''}"
humanized_use_case: "{resource.humanized_use_case}"
sub_categories: {resource.sub_categories}
subscription: "{resource.subscription_tier}"
date_saved: {now_str}
tags:
{tags_yaml}
status: "To Explore"
pricing: "{resource.pricing_or_eligibility or 'Unknown'}"
deadline: {f'"{resource.deadline}"' if resource.deadline else 'null'}
creator: "@{reel_data.creator}"
source_url: "{reel_data.url}"
confidence: "{resource.confidence}"
---

# {resource.resource_name}

> [!TIP] **Quick Use Case**
> {resource.humanized_use_case or resource.summary}
{course_section}
### 🌟 Key Highlights & Value
{features_md}

### 🚀 Actionable Steps
{actions_md}

### ℹ️ Resource Details
| Property | Value |
| :--- | :--- |
| **Category** | `{resource.category}` |
| **Type** | `{resource.resource_type}` |
| **Sub-Categories** | {' '.join([f'`{c}`' for c in resource.sub_categories])} |
| **Pricing / Access** | `{resource.subscription_tier}` |
| **Deadline** | {resource.deadline or 'None'} |
| **Creator** | [@{reel_data.creator}](https://instagram.com/{reel_data.creator}) |
| **Official Link** | {website_link_md} |
| **Original Instagram Post** | [Open Post on Instagram]({reel_data.url}) |

---
*Captured and organized automatically by your Instagram Second Brain Agent on {now_str}.*
"""
        file_path.write_text(content, encoding="utf-8")
        self._sync_all_segment_tables()
        return file_path

    def save_deep_resource(self, deep_res: DeepResource) -> Path:
        """Write an in-depth roadmap/course/tool note and update segment table."""
        folder_name = CATEGORIES.get(deep_res.category, "Roadmaps & Learning")
        target_folder = self.resources_dir / folder_name
        target_folder.mkdir(parents=True, exist_ok=True)

        safe_name = self._sanitize_filename(deep_res.resource_name)
        file_path = target_folder / f"{safe_name}.md"

        now_str = datetime.now().strftime("%Y-%m-%d")
        tags_yaml = "\n".join([f"  - {t.strip().replace(' ', '-')}" for t in deep_res.tags if t.strip()]) or "  - course"
        features_md = "\n".join([f"- {f}" for f in deep_res.key_features]) or "- See curriculum below"
        actions_md = "\n".join([f"1. {a}" for a in deep_res.actionable_steps]) or "1. Follow syllabus below."

        course_section = ""
        if deep_res.resource_type == "Course" or deep_res.provider:
            modules_list = "\n".join([f"- **Module {i+1}:** {m}" for i, m in enumerate(deep_res.syllabus_modules)]) if deep_res.syllabus_modules else "- Complete syllabus extracted below."
            course_section = f"""
### 🎓 Course & Provider Intelligence
| Property | Detail |
| :--- | :--- |
| **Provider / Platform** | `{deep_res.provider or 'Direct / Official'}` |
| **Credential / Certificate** | `{deep_res.credential_status or 'None'}` |
| **Estimated Duration** | `{deep_res.duration or 'Self-Paced'}` |
| **Direct Course Link** | [{deep_res.website_url}]({deep_res.website_url}) |

### 📚 Syllabus Breakdown
{modules_list}
"""

        content = f"""---
title: "{deep_res.resource_name}"
category: "{deep_res.category}"
resource_type: "{deep_res.resource_type}"
resource_name: "{deep_res.resource_name}"
provider: "{deep_res.provider or ''}"
credential_status: "{deep_res.credential_status or 'None'}"
duration: "{deep_res.duration or ''}"
url: "{deep_res.website_url}"
humanized_use_case: "{deep_res.humanized_use_case}"
sub_categories: {deep_res.sub_categories}
subscription: "{deep_res.subscription_tier}"
date_saved: {now_str}
tags:
{tags_yaml}
status: "To Explore"
pricing: "{deep_res.pricing_or_eligibility or 'Free'}"
deadline: {f'"{deep_res.deadline}"' if deep_res.deadline else 'null'}
creator: "@{deep_res.creator}"
source_url: "{deep_res.source_url}"
confidence: "High (Verified DM Resource)"
---

# {deep_res.resource_name}

> [!TIP] **Quick Use Case**
> {deep_res.humanized_use_case or deep_res.summary}
{course_section}
### 🌟 Core Highlights
{features_md}

### 🚀 How to Execute & Get Started
{actions_md}

---

## 📖 Complete Curriculum & In-Depth Notes
{deep_res.detailed_notes_markdown}

---
### ℹ️ Resource Details
| Property | Value |
| :--- | :--- |
| **Category** | `{deep_res.category}` |
| **Type** | `{deep_res.resource_type}` |
| **Sub-Categories** | {' '.join([f'`{c}`' for c in deep_res.sub_categories])} |
| **Pricing / Access** | `{deep_res.subscription_tier}` |
| **Official Link** | [{deep_res.website_url}]({deep_res.website_url}) |
| **Creator / Source** | [@{deep_res.creator}](https://instagram.com/{deep_res.creator}) |
| **Status** | `To Explore` |

---
*Captured and organized in full depth by your Instagram Second Brain Agent on {now_str}.*
"""
        file_path.write_text(content, encoding="utf-8")
        self._sync_all_segment_tables()
        return file_path

    def _sync_all_segment_tables(self):
        """
        Scan all notes in Resources/ and regenerate each dedicated segment file
        matching the Notion database table view with deep course intelligence.
        """
        grouped: Dict[str, List[Dict[str, Any]]] = {cat: [] for cat in SEGMENT_FILES.keys()}

        for md_file in self.resources_dir.glob("*/*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                title = md_file.stem
                cat = "Dev-Tools"
                res_type = "Tool"
                provider = ""
                credential = "None"
                duration = ""
                url = ""
                date_saved = "2026-09-10"
                use_case = ""
                subs = ["Tech"]
                pricing = "Free"
                deadline = None
                status = "To Explore"

                for line in content.splitlines()[:35]:
                    if line.startswith("title:"):
                        title = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("category:"):
                        cat = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("resource_type:"):
                        res_type = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("provider:"):
                        provider = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("credential_status:"):
                        credential = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("duration:"):
                        duration = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("url:"):
                        url = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("date_saved:"):
                        date_saved = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("humanized_use_case:"):
                        use_case = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("subscription:"):
                        pricing = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("sub_categories:"):
                        raw_subs = line.split(":", 1)[1].strip().strip("[]")
                        subs = [s.strip().strip("'\"") for s in raw_subs.split(",") if s.strip()]
                    elif line.startswith("deadline:") and "null" not in line and "None" not in line:
                        deadline = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("status:"):
                        status = line.split(":", 1)[1].strip().strip('"\'')

                if cat not in grouped:
                    cat = "Dev-Tools"

                rel_note_link = f"[[Resources/{md_file.parent.name}/{md_file.name}|{title}]]"
                short_url = url.replace("https://", "").replace("http://", "").split("/")[0] if url else "None"
                web_link = f"[{short_url}]({url})" if url else "None"

                grouped[cat].append({
                    "title": title,
                    "rel_link": rel_note_link,
                    "url": url,
                    "web_link": web_link,
                    "use_case": use_case or f"Essential resource for {cat}.",
                    "sub_cats": subs if subs else [cat],
                    "res_type": res_type,
                    "provider": provider or ("Coursera" if "coursera" in url.lower() else "Udemy" if "udemy" in url.lower() else "YouTube" if "youtube" in url.lower() or "youtu.be" in url.lower() else "Harvard" if "harvard" in url.lower() else "Independent"),
                    "credential": credential if credential and credential != "None" else ("Free Certificate" if "free" in pricing.lower() and "cert" in use_case.lower() else "Audit / None"),
                    "duration": duration or "Self-paced",
                    "pricing": pricing,
                    "date": date_saved,
                    "deadline": deadline or "Open",
                    "status": status,
                    "mtime": md_file.stat().st_mtime
                })
            except Exception:
                continue

        for cat in grouped:
            grouped[cat].sort(key=lambda x: x["mtime"], reverse=True)

        self._write_ui_ux_table(grouped.get("UI-UX", []))
        self._write_ai_tools_table(grouped.get("AI-Agents", []))
        self._write_internships_table(grouped.get("Internships", []))
        self._write_hackathons_table(grouped.get("Hackathons", []))
        self._write_roadmaps_table(grouped.get("Roadmaps", []))
        self._write_dev_tools_table(grouped.get("Dev-Tools", []))
        self._write_master_hub(grouped)

    def _write_ui_ux_table(self, items: List[Dict[str, Any]]):
        path = self.vault_path / SEGMENT_FILES["UI-UX"]
        rows = [
            "| Resource Name | Categories | URL & Source | Use Cases | Subscription | Added On |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ]
        if items:
            for it in items:
                cats = self._format_badges(it.get("sub_cats", []), "Design")
                rows.append(f"| {it['rel_link']} | {cats} | {it['web_link']} | {it['use_case']} | `{it['pricing']}` | {it['date']} |")
        else:
            rows.append("| *(No UI/UX tools saved yet)* | `Design System` `Figma` | `https://...` | *Send an Instagram design reel or link to add here!* | `Free` | *Today* |")

        table_body = "\n".join(rows)
        content = f"""# 🎨 UI & UX Resources Database

A dedicated database of design systems, Figma libraries, interactive UI components, and design toolkits.

---

### 📋 All Resources ({len(items)})
{table_body}

---
*Return to [[00 - 🚀 Master Hub|Master Hub]]*
"""
        path.write_text(content, encoding="utf-8")

    def _write_ai_tools_table(self, items: List[Dict[str, Any]]):
        path = self.vault_path / SEGMENT_FILES["AI-Agents"]
        rows = [
            "| Tool Name | Categories | URL & Source | Use Cases | Subscription | Added On |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ]
        if items:
            for it in items:
                cats = self._format_badges(it.get("sub_cats", []), "AI Agent")
                rows.append(f"| {it['rel_link']} | {cats} | {it['web_link']} | {it['use_case']} | `{it['pricing']}` | {it['date']} |")
        else:
            rows.append("| *(No AI tools saved yet)* | `AI Agent` `AI Tool` | `https://...` | *Send an AI reel or tool link to @ExtractorXCodyseeybot to add here!* | `Freemium` | *Today* |")

        table_body = "\n".join(rows)
        content = f"""# 🤖 AI Tools & Agents Collection

A dedicated database of autonomous agents, AI code editors, LLM frameworks, and generative AI tools.

---

### 📋 All Tools ({len(items)})
{table_body}

---
*Return to [[00 - 🚀 Master Hub|Master Hub]]*
"""
        path.write_text(content, encoding="utf-8")

    def _write_internships_table(self, items: List[Dict[str, Any]]):
        path = self.vault_path / SEGMENT_FILES["Internships"]
        rows = [
            "| Opportunity / Company | Categories | Portal & Apply | Eligibility & Highlights | Stipend / Access | Deadline |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ]
        if items:
            for it in items:
                cats = self._format_badges(it.get("sub_cats", []), "Internship")
                rows.append(f"| {it['rel_link']} | {cats} | {it['web_link']} | {it['use_case']} | `{it['pricing']}` | `{it['deadline']}` |")
        else:
            rows.append("| *(No internships saved yet)* | `Internship` `Hiring` | `https://...` | *Send an opportunity reel to @ExtractorXCodyseeybot to add here!* | `Paid` | `Open` |")

        table_body = "\n".join(rows)
        content = f"""# 💼 Internships & Career Opportunities

A dedicated database of active student developer internships, fellowships, and hiring programs.

---

### 📋 Active Openings ({len(items)})
{table_body}

---
*Return to [[00 - 🚀 Master Hub|Master Hub]]*
"""
        path.write_text(content, encoding="utf-8")

    def _write_hackathons_table(self, items: List[Dict[str, Any]]):
        path = self.vault_path / SEGMENT_FILES["Hackathons"]
        rows = [
            "| Hackathon / Contest | Categories | Portal & Apply | Focus & Highlights | Prize / Access | Deadline |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ]
        if items:
            for it in items:
                cats = self._format_badges(it.get("sub_cats", []), "Hackathon")
                rows.append(f"| {it['rel_link']} | {cats} | {it['web_link']} | {it['use_case']} | `{it['pricing']}` | `{it['deadline']}` |")
        else:
            rows.append("| *(No hackathons saved yet)* | `Hackathon` `AI Contest` | `https://...` | *Send a hackathon reel to @ExtractorXCodyseeybot to add here!* | `Prizes` | `Upcoming` |")

        table_body = "\n".join(rows)
        content = f"""# 🏆 Hackathons & Competitions

A dedicated database of upcoming hackathons, AI builder challenges, and prize tracks.

---

### 📋 Active Competitions ({len(items)})
{table_body}

---
*Return to [[00 - 🚀 Master Hub|Master Hub]]*
"""
        path.write_text(content, encoding="utf-8")

    def _write_roadmaps_table(self, items: List[Dict[str, Any]]):
        """Dedicated database table for Courses, Certifications, and Learning Roadmaps."""
        path = self.vault_path / SEGMENT_FILES["Roadmaps"]
        rows = [
            "| Course / Roadmap Title | Platform / Provider | Credential | Direct Link | Curriculum & Focus | Added On |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ]
        if items:
            for it in items:
                prov = f"`{it['provider']}`"
                cred = f"`{it['credential']}`"
                rows.append(f"| {it['rel_link']} | {prov} | {cred} | {it['web_link']} | {it['use_case']} | {it['date']} |")
        else:
            rows.append("| *(No courses saved yet)* | `Coursera / Harvard` | `Free Certificate` | `https://...` | *Paste a course link or send a reel/carousel to extract here!* | *Today* |")

        table_body = "\n".join(rows)
        content = f"""# 🗺️ Courses, Certifications & Learning Roadmaps

A dedicated, structured database of verified online courses, university programs, developer learning paths, and curriculum guides.

---

### 📋 All Courses & Roadmaps ({len(items)})
{table_body}

---
*Return to [[00 - 🚀 Master Hub|Master Hub]]*
"""
        path.write_text(content, encoding="utf-8")

    def _write_dev_tools_table(self, items: List[Dict[str, Any]]):
        path = self.vault_path / SEGMENT_FILES["Dev-Tools"]
        rows = [
            "| Tool Name | Categories | URL & Source | Use Cases | Subscription | Added On |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ]
        if items:
            for it in items:
                cats = self._format_badges(it.get("sub_cats", []), "DevTool")
                rows.append(f"| {it['rel_link']} | {cats} | {it['web_link']} | {it['use_case']} | `{it['pricing']}` | {it['date']} |")
        else:
            rows.append("| *(No dev utilities saved yet)* | `DevTool` `CLI` | `https://...` | *Send a developer tool reel or GitHub link to add here!* | `Open Source` | *Today* |")

        table_body = "\n".join(rows)
        content = f"""# 🛠️ Dev Tools & Utilities Collection

A dedicated database of developer tools, CLI utilities, libraries, and extensions.

---

### 📋 All Utilities ({len(items)})
{table_body}

---
*Return to [[00 - 🚀 Master Hub|Master Hub]]*
"""
        path.write_text(content, encoding="utf-8")

    def _write_master_hub(self, grouped: Dict[str, List[Dict[str, Any]]]):
        path = self.vault_path / "00 - 🚀 Master Hub.md"
        total = sum(len(items) for items in grouped.values())
        content = f"""# 🚀 Personal Knowledge & Tech Hub

Welcome to your dedicated **Second Brain**! Every resource captured from Instagram or the web is automatically filed into its dedicated database table.

---

### 📊 Vault Statistics
* **Total Resources Captured:** `{total}`
* **🎨 UI & UX Resources:** `{len(grouped.get('UI-UX', []))}`
* **🤖 AI Tools & Autonomous Agents:** `{len(grouped.get('AI-Agents', []))}`
* **💼 Internships & Career Opportunities:** `{len(grouped.get('Internships', []))}`
* **🏆 Hackathons & Builder Challenges:** `{len(grouped.get('Hackathons', []))}`
* **🗺️ Courses, Certifications & Roadmaps:** `{len(grouped.get('Roadmaps', []))}`
* **🛠️ Developer Tools & Utilities:** `{len(grouped.get('Dev-Tools', []))}`

---

### 📂 Quick Navigation
1. [[01 - 🎨 UI & UX Resources|UI & UX Resources]]
2. [[02 - 🤖 AI Tools & Agents|AI Tools & Autonomous Agents]]
3. [[03 - 💼 Internships & Opportunities|Internships & Opportunities]]
4. [[04 - 🏆 Hackathons & Competitions|Hackathons & Competitions]]
5. [[05 - 🗺️ Roadmaps & Learning|Courses, Certifications & Roadmaps]]
6. [[06 - 🛠️ Dev Tools & Utilities|Developer Tools & Utilities]]

---
*Generated by Instagram Knowledge Extractor Agent*
"""
        path.write_text(content, encoding="utf-8")

    def wipe_vault(self):
        """Completely reset the vault resources and regenerate fresh segment tables."""
        if self.resources_dir.exists():
            for folder in self.resources_dir.iterdir():
                if folder.is_dir():
                    for f in folder.glob("*.md"):
                        try:
                            f.unlink()
                        except Exception:
                            pass
        self._sync_all_segment_tables()
