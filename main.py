import sys
import os

# Fix Windows console UTF-8 emoji encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import argparse
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console(legacy_windows=False, force_terminal=True)

from src.config import TELEGRAM_BOT_TOKEN, OBSIDIAN_VAULT_PATH, GEMINI_API_KEY
from src.reel_downloader import ReelDownloader, ReelData
from src.ai_extractor import AIExtractor, ExtractedResource
from src.obsidian_writer import ObsidianWriter

def test_single_url(url: str):
    console.print(f"\n[bold cyan]🔍 Testing Reel Extraction on:[/bold cyan] {url}")

    downloader = ReelDownloader()
    extractor = AIExtractor()
    writer = ObsidianWriter()

    with console.status("[bold green]Downloading reel and extracting keyframes..."):
        reel_data = downloader.download_reel(url)

    console.print(f"✅ Downloaded! Creator: [bold]@{reel_data.creator}[/bold] | Keyframes: {len(reel_data.keyframes)}")

    with console.status("[bold yellow]Running Gemini 2.5 Flash Multimodal Extraction..."):
        resource = extractor.extract(reel_data)

    with console.status("[bold magenta]Saving note to Obsidian Vault..."):
        saved_path = writer.save_resource(resource, reel_data)

    reel_data.cleanup()

    # Display results
    table = Table(title="🎉 Extracted Resource Summary")
    table.add_column("Field", style="bold cyan")
    table.add_column("Value", style="white")

    table.add_row("Resource Name", resource.resource_name)
    table.add_row("Category", resource.category)
    table.add_row("Official URL", resource.website_url or "None")
    table.add_row("Summary", resource.summary)
    table.add_row("Confidence", resource.confidence)
    table.add_row("Saved Note", str(saved_path))

    console.print(table)
    console.print(f"\n[bold green]✅ Saved successfully into Obsidian Vault:[/bold green] {saved_path}")

def run_dry_run_simulation():
    """Simulate a reel extraction without needing live Instagram network connection."""
    console.print("\n[bold cyan]🧪 Running End-to-End Pipeline Dry Run Simulation...[/bold cyan]")

    extractor = AIExtractor()
    writer = ObsidianWriter()

    simulated_reel = ReelData(
        url="https://www.instagram.com/reel/C8xyz123Mock",
        creator="tech_growth_daily",
        caption="Stop wasting hours building landing pages! This insane AI tool turns any prompt into full UI wireframes, sitemaps and responsive Figma components in 10 seconds. Comment 'TOOL' to get the link! #uiux #figma #ai #design",
        title="Insane AI UI/UX Tool",
        duration=25.0
    )

    console.print(f"🎬 Simulated Reel: [italic]{simulated_reel.caption[:80]}...[/italic]")

    with console.status("[bold yellow]Testing AI Extraction with Gemini 2.5 Flash..."):
        resource = extractor.extract(simulated_reel)

    console.print(f"✨ Extracted: [bold green]{resource.resource_name}[/bold green] (Category: {resource.category})")
    console.print(f"🔗 Resolved URL: [bold blue]{resource.website_url}[/bold blue]")

    with console.status("[bold magenta]Writing note to Obsidian Vault..."):
        saved_path = writer.save_resource(resource, simulated_reel)

    console.print(f"📁 [bold green]Note successfully created in Obsidian:[/bold green] {saved_path}")
    console.print(f"📊 [bold green]Vault Dashboard ready at:[/bold green] {OBSIDIAN_VAULT_PATH / '00 - Resource Dashboard.md'}")

def main():
    parser = argparse.ArgumentParser(description="Instagram Second Brain Agent")
    parser.add_argument("--test-url", type=str, help="Test extraction on a single Instagram Reel URL")
    parser.add_argument("--dry-run", action="store_true", help="Run end-to-end simulation test without downloading")
    args = parser.parse_args()

    if args.dry_run:
        run_dry_run_simulation()
        return

    if args.test_url:
        test_single_url(args.test_url)
        return

    # Default: Run Telegram Bot
    from src.telegram_bot import TelegramBotService
    bot_service = TelegramBotService()
    bot_service.run()

if __name__ == "__main__":
    main()
