import re
import random
import asyncio
from typing import Optional
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from src.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_ALLOWED_USER_ID,
    set_allowed_telegram_user,
    set_instagram_session_id,
    CATEGORIES,
    OBSIDIAN_VAULT_PATH
)
from src.reel_downloader import ReelDownloader
from src.ai_extractor import AIExtractor
from src.obsidian_writer import ObsidianWriter, SEGMENT_FILES
from src.web_extractor import WebExtractor
from src.instagram_dm_watcher import InstagramDMWatcher
from src.instagram_commenter import InstagramCommenter

INSTAGRAM_REGEX = re.compile(r'https?://(?:www\.)?instagram\.com/(?:reel|reels|p)/([A-Za-z0-9_-]+)')
GENERAL_URL_REGEX = re.compile(r'https?://[^\s]+')
async def safe_edit_text(message, text: str, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=False):
    """Edit message text with automatic plain text fallback if Markdown parsing fails."""
    try:
        return await message.edit_text(text, parse_mode=parse_mode, disable_web_page_preview=disable_web_page_preview)
    except Exception:
        clean_text = text.replace("*", "").replace("`", "").replace("_", "")
        try:
            return await message.edit_text(clean_text, parse_mode=None, disable_web_page_preview=disable_web_page_preview)
        except Exception:
            pass

async def safe_reply_text(message, text: str, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=False):
    """Reply with automatic plain text fallback if Markdown parsing fails."""
    try:
        return await message.reply_text(text, parse_mode=parse_mode, disable_web_page_preview=disable_web_page_preview)
    except Exception:
        clean_text = text.replace("*", "").replace("`", "").replace("_", "")
        try:
            return await message.reply_text(clean_text, parse_mode=None, disable_web_page_preview=disable_web_page_preview)
        except Exception:
            pass

class TelegramBotService:
    def __init__(self):
        self.downloader = ReelDownloader()
        self.extractor = AIExtractor()
        self.web_extractor = WebExtractor()
        self.writer = ObsidianWriter()
        self.dm_watcher = InstagramDMWatcher()
        self.commenter = InstagramCommenter()
        self.action_lock = asyncio.Lock()
        self.app = None
        self.dm_watcher.on_session_expired = self._handle_session_expired

    def _handle_session_expired(self):
        """Notify the authorized user on Telegram when Instagram session expires."""
        if self.app and TELEGRAM_ALLOWED_USER_ID:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(
                        self.app.bot.send_message(
                            chat_id=int(TELEGRAM_ALLOWED_USER_ID),
                            text="⚠️ *Instagram Session Expired!*\n\n"
                                 "Instagram returned 401/403 or requested re-login.\n"
                                 "To resume autonomous capture, send:\n"
                                 "`/set_cookie <new_sessionid>`",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    )
            except Exception as e:
                print(f"[WARN] Failed to send session expiry alert: {e}")

    def is_authorized(self, user_id: int) -> bool:
        if not TELEGRAM_ALLOWED_USER_ID:
            set_allowed_telegram_user(user_id)
            return True
        return str(user_id) == TELEGRAM_ALLOWED_USER_ID

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        user_id = user.id if user else 0

        if self.is_authorized(user_id):
            msg = (
                f"👋 *Hey {user.first_name}! Your Instagram Second Brain is Active & Ready.*\n\n"
                "Here is how you can use me:\n\n"
                "1️⃣ *Share Any Instagram Content (Reels, Carousels, Posts):*\n"
                "Send any link! I will auto-comment the trigger keyword, follow the creator, capture their ManyChat DM, and write full structured notes to Obsidian.\n\n"
                "2️⃣ *Send Multiple Links Back-to-Back:*\n"
                "Drop multiple reels simultaneously! They will be commented safely and tracked concurrently in parallel.\n\n"
                "3️⃣ *Send Any Direct Link:* (Courses, Roadmaps, Notion, GitHub)\n"
                "Paste the URL directly and I will extract the complete syllabus, provider, and module notes.\n\n"
                "4️⃣ *Update Instagram Cookie:* Send `/set_cookie <new_sessionid>` if your session expires.\n"
                "5️⃣ *Scan Instagram DMs:* Send `/scan_dms` to check your inbox manually.\n"
                "6️⃣ *Wipe Vault:* Send `/wipe` to reset your Obsidian database clean."
            )
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("🔒 *Unauthorized access.*", parse_mode=ParseMode.MARKDOWN)

    async def set_cookie_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Update Instagram session cookie dynamically from Telegram."""
        user = update.effective_user
        if not self.is_authorized(user.id if user else 0):
            return

        if not context.args:
            await update.message.reply_text(
                "ℹ️ *Usage:* `/set_cookie <new_sessionid>`\n\n"
                "Copy the fresh `sessionid` cookie value from your browser (Application ➔ Cookies ➔ instagram.com) and paste it here.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        new_cookie = context.args[0].strip().strip('"\'')
        set_instagram_session_id(new_cookie)
        self.dm_watcher.update_session_id(new_cookie)
        self.commenter.update_session_id(new_cookie)
        await update.message.reply_text(
            "✅ *Instagram Session Cookie Updated & Saved!*\n\n"
            "The agent's session is now refreshed and ready to comment, follow, and capture creator DMs.",
            parse_mode=ParseMode.MARKDOWN
        )

    async def wipe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reset the Obsidian vault tables and remove old notes upon user request."""
        user = update.effective_user
        if not self.is_authorized(user.id if user else 0):
            return

        status = await update.message.reply_text("🧹 *Wiping Obsidian vault & resetting segment databases...*", parse_mode=ParseMode.MARKDOWN)
        try:
            await asyncio.to_thread(self.writer.wipe_vault)
            await status.edit_text(
                "✨ *Obsidian Vault completely wiped clean!*\n\n"
                "All 6 dedicated segment database tables have been reset to a fresh state.\n"
                "Ready to capture and categorize new resources!",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            await status.edit_text(f"❌ *Failed to wipe vault:* `{str(e)[:200]}`", parse_mode=ParseMode.MARKDOWN)

    async def scan_dms_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manually trigger an Instagram Direct Inbox scan."""
        user = update.effective_user
        if not self.is_authorized(user.id):
            return

        status = await update.message.reply_text("📬 *Scanning your Instagram Direct Inbox for creator messages and links...*", parse_mode=ParseMode.MARKDOWN)

        try:
            results = await asyncio.to_thread(self.dm_watcher.scan_inbox)
            if not results:
                await status.edit_text("✅ *Inbox checked:* No new creator links found right now.\n\nDrop a comment on a reel/carousel and try `/scan_dms` once ManyChat replies, or paste the link directly here!", parse_mode=ParseMode.MARKDOWN)
                return

            msg_lines = [f"🎉 *Captured {len(results)} New Resources from Instagram DMs:*\n"]
            for r in results:
                msg_lines.append(f"• *{r['resource_name']}* (from @{r['creator']})\n  🔗 [Official Link]({r['url']})\n  📂 Category: `{r['category']}`\n")

            await status.edit_text("\n".join(msg_lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        except Exception as e:
            await status.edit_text(f"❌ *Failed to scan inbox:* `{str(e)[:200]}`", parse_mode=ParseMode.MARKDOWN)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        user_id = user.id if user else 0

        if not self.is_authorized(user_id):
            await update.message.reply_text("🔒 *Unauthorized access.*", parse_mode=ParseMode.MARKDOWN)
            return

        text = update.message.text or update.message.caption or ""

        # Case 1: Instagram Reel / Carousel / Post URL (Dispatch asynchronously so multiple reels run in parallel)
        ig_match = INSTAGRAM_REGEX.search(text)
        if ig_match:
            asyncio.create_task(self._process_instagram_content(update, ig_match.group(0)))
            return

        # Case 2: General URL (Courses, Notion, Roadmap, GitHub, YouTube)
        url_match = GENERAL_URL_REGEX.search(text)
        if url_match:
            asyncio.create_task(self._process_general_url(update, url_match.group(0)))
            return

        await update.message.reply_text(
            "ℹ️ Send me an Instagram link (Reel, Carousel, Post) or paste any resource/course URL to extract it into Obsidian.",
            parse_mode=ParseMode.MARKDOWN
        )

    async def _process_instagram_content(self, update: Update, post_url: str):
        status_msg = await update.message.reply_text(
            "⏳ *Analyzing Instagram Content...*\n1️⃣ Fetching post details & media slides...",
            parse_mode=ParseMode.MARKDOWN
        )
        try:
            # 1. Download media (handles carousels, photos, reels)
            media_data = await asyncio.to_thread(self.downloader.download_reel, post_url)
            type_label = f"Carousel ({len(media_data.keyframes)} slides)" if media_data.media_type == "carousel" else ("Photo Post" if media_data.media_type == "photo" else "Reel")
            creator_tag = f"`@{media_data.creator}`"

            # 2. Closed-Loop: Staggered Queue Execution (Auto-Follow creator + Post trigger comment)
            await safe_edit_text(
                status_msg,
                f"⏳ *Queued for Staggered Execution...* ({type_label})\n"
                f"🎯 Preparing comment on {creator_tag}'s post safely..."
            )

            follow_ok = False
            comment_ok = False
            keyword = ""

            async with self.action_lock:
                if media_data.creator_id:
                    follow_ok, follow_status = await asyncio.to_thread(
                        self.commenter.follow_user, media_data.creator_id
                    )

                comment_ok, keyword, comment_status = await asyncio.to_thread(
                    self.commenter.post_comment, post_url, media_data.caption
                )
                # Anti-ban human-like randomized delay before releasing the lock for the next reel
                await asyncio.sleep(random.uniform(3.0, 5.0))

            raw_links = []
            if comment_ok:
                follow_line = f"2️⃣ ➕ Followed {creator_tag} to satisfy ManyChat gate ✅\n" if follow_ok else ""
                poll_num = "3️⃣" if follow_ok else "2️⃣"
                await safe_edit_text(
                    status_msg,
                    f"⏳ *Closed-Loop Engine Active!* ({type_label})\n"
                    f"1️⃣ 💬 Commented '*{keyword}*' on {creator_tag}'s post ✅\n"
                    f"{follow_line}"
                    f"{poll_num} 📬 Listening for ManyChat DM (active in background up to 10 mins)... ⏳\n\n"
                    f"💡 *Tip:* If ManyChat sends an interactive button (like _'Send me the access'_), tap it in your Instagram app! The agent will capture the final link."
                )
                loop = asyncio.get_running_loop()
                def on_dm_status(text: str):
                    try:
                        asyncio.run_coroutine_threadsafe(
                            safe_edit_text(status_msg, f"⏳ *Closed-Loop Engine Active!*\n{text}"),
                            loop
                        )
                    except Exception:
                        pass

                raw_links = await self.dm_watcher.wait_for_creator_dm_async(
                    creator_username=media_data.creator,
                    creator_id=media_data.creator_id,
                    timeout_seconds=600,
                    on_status_update=on_dm_status
                )

            # Path A: 100% Accurate Verified DM Link Captured!
            if raw_links:
                primary_link, bonus_links = await asyncio.to_thread(
                    self.web_extractor.select_primary_and_bonus_urls,
                    raw_links,
                    media_data.caption,
                    media_data.creator
                )

                follow_success_line = f"2️⃣ ➕ Followed {creator_tag} ✅\n" if follow_ok else ""
                step3_num = "3️⃣" if follow_ok else "2️⃣"
                step4_num = "4️⃣" if follow_ok else "3️⃣"
                await safe_edit_text(
                    status_msg,
                    f"🎯 *Closed-Loop Interception Succeeded!*\n"
                    f"1️⃣ 💬 Auto-commented '*{keyword}*' ✅\n"
                    f"{follow_success_line}"
                    f"{step3_num} 📬 ManyChat DM Captured: [Direct Link]({primary_link}) ✅\n"
                    f"{step4_num} 🧠 Extracting complete course & resource intelligence into Obsidian...",
                    disable_web_page_preview=True
                )
                deep_res = await asyncio.to_thread(self.web_extractor.extract_deep_resource, primary_link, creator=media_data.creator)
                if deep_res:
                    saved_path = await asyncio.to_thread(self.writer.save_deep_resource, deep_res, additional_links=bonus_links)
                    media_data.cleanup()

                    cats_line = " ".join([f"`{c}`" for c in deep_res.sub_categories]) if deep_res.sub_categories else f"`{deep_res.category}`"
                    seg_file = SEGMENT_FILES.get(deep_res.category, "05 - 🗺️ Roadmaps & Learning.md")

                    prov_line = f"\n🏛️ *Provider / Platform:* `{deep_res.provider}`" if deep_res.provider else ""
                    cred_line = f"\n🎓 *Credential:* `{deep_res.credential_status}`" if deep_res.credential_status and deep_res.credential_status != "None" else ""
                    bonus_msg = f"\n🎁 *Bonus Links Bundled:* `{len(bonus_links)}`" if bonus_links else ""

                    funnel_msg = f"Commented '`{keyword}`' + Followed {creator_tag}" if follow_ok else f"Commented '`{keyword}`'"
                    response_card = (
                        f"🎯 *Verified Resource Captured from DM!*\n\n"
                        f"📌 *{deep_res.resource_name}*\n"
                        f"🏷️ {cats_line}{prov_line}{cred_line}{bonus_msg}\n"
                        f"🔗 *Verified Link:* {deep_res.website_url}\n"
                        f"💰 *Tier:* `{deep_res.subscription_tier}`\n\n"
                        f"💡 *Use Case:*\n_{deep_res.humanized_use_case or deep_res.summary}_\n\n"
                        f"🤖 *Creator Funnel:* {funnel_msg} ➔ Captured ManyChat DM\n"
                        f"📊 *Updated Table:* `{seg_file}`\n"
                        f"📁 *Deep Note:* `{saved_path.name}`"
                    )
                    try:
                        await status_msg.delete()
                    except Exception:
                        pass
                    await safe_reply_text(update.message, response_card, disable_web_page_preview=False)
                    return

            # Path B: Timeout occurred - Zero Hallucination Draft Fallback!
            saved_draft = await asyncio.to_thread(self.writer.save_unverified_draft, media_data)
            media_data.cleanup()
            follow_txt = f"• Followed {creator_tag} ✅\n" if follow_ok else ""
            fail_notice = (
                f"⏳ *ManyChat DM Timed Out (10 mins)*\n\n"
                f"• Commented '*{keyword}*' on {creator_tag}'s post ✅\n"
                f"{follow_txt}"
                f"• Creator's ManyChat did not deliver an unlockable resource link within 10 minutes.\n\n"
                f"📝 *Saved as Unverified Draft:*\n"
                f"• File: `Drafts/{saved_draft.name}`\n"
                f"• Tags: `#unverified` `#missing-link`\n"
                f"🛡️ *Obsidian Knowledge Tables were NOT modified* (zero fake or hallucinated URLs).\n\n"
                f"💡 *Next Steps:*\n"
                f"• If ManyChat delivers the link with a delay, send `/scan_dms` to sync it automatically.\n"
                f"• Or paste the resource link directly here to extract full notes!"
            )
            try:
                await status_msg.delete()
            except Exception:
                pass
            await safe_reply_text(update.message, fail_notice)

        except Exception as e:
            await safe_edit_text(status_msg, f"❌ Failed to process Instagram content: {str(e)[:200]}", parse_mode=None)

    async def _process_general_url(self, update: Update, url: str):
        status_msg = await update.message.reply_text(
            "🌐 *Direct Resource / Course Mode Detected!*\nFetching full page contents & analyzing syllabus...",
            parse_mode=ParseMode.MARKDOWN
        )
        try:
            deep_res = await asyncio.to_thread(self.web_extractor.extract_deep_resource, url)
            if not deep_res:
                await status_msg.edit_text("❌ *Could not extract content from that link.*", parse_mode=ParseMode.MARKDOWN)
                return

            saved_path = await asyncio.to_thread(self.writer.save_deep_resource, deep_res)
            cats_line = " ".join([f"`{c}`" for c in deep_res.sub_categories]) if deep_res.sub_categories else f"`{deep_res.category}`"
            seg_file = SEGMENT_FILES.get(deep_res.category, "05 - 🗺️ Roadmaps & Learning.md")

            prov_line = f"\n🏛️ *Provider / Platform:* `{deep_res.provider}`" if deep_res.provider else ""
            cred_line = f"\n🎓 *Credential:* `{deep_res.credential_status}`" if deep_res.credential_status and deep_res.credential_status != "None" else ""

            response_card = (
                f"🎉 *Course / Resource Added to Database!*\n\n"
                f"📌 *{deep_res.resource_name}*\n"
                f"🏷️ {cats_line}{prov_line}{cred_line}\n"
                f"🔗 *Direct Link:* {deep_res.website_url}\n"
                f"💰 *Tier:* `{deep_res.subscription_tier}`\n\n"
                f"💡 *Use Case:*\n_{deep_res.humanized_use_case or deep_res.summary}_\n\n"
                f"📖 *Full Syllabus & Module Breakdown saved to Obsidian!*\n\n"
                f"📊 *Updated Table:* `{seg_file}`\n"
                f"📁 *Deep Note:* `{saved_path.name}`"
            )
            await status_msg.delete()
            await update.message.reply_text(response_card, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=False)
        except Exception as e:
            await status_msg.edit_text(f"❌ *Failed to extract document:* `{str(e)[:200]}`", parse_mode=ParseMode.MARKDOWN)

    def run(self):
        if not TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set in .env!")

        print("🚀 Starting Instagram Extractor Telegram Bot...")
        print(f"📁 Obsidian Vault: {OBSIDIAN_VAULT_PATH}")

        app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        self.app = app
        app.add_handler(CommandHandler("start", self.start_command))
        app.add_handler(CommandHandler("scan_dms", self.scan_dms_command))
        app.add_handler(CommandHandler("set_cookie", self.set_cookie_command))
        app.add_handler(CommandHandler("wipe", self.wipe_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        print("✅ Bot is online and polling! Send /start to your bot on Telegram.")
        app.run_polling()
