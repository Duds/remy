"""
Week-at-a-glance image generator for rich media briefings (US-rich-media-briefing-summaries).

Produces a single image (e.g. PNG) summarising the week: dates, optional goals.
Falls back to None if image generation fails.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def generate_week_image(
    week_start: datetime | None = None,
    goals_text: str = "",
    tz_name: str = "UTC",
) -> tuple[bytes | None, str]:
    """
    Generate a simple week-at-a-glance image and caption.

    Returns (png_bytes, caption). png_bytes is None if generation fails.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("PIL not available for week-at-a-glance image")
        return None, ""

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")

    try:
        now = datetime.now(tz)
        if week_start is None:
            # Monday of current week
            week_start = now - timedelta(days=now.weekday())
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        width, height = 800, 400
        img = Image.new("RGB", (width, height), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
            font_small = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16
            )
        except OSError:
            font = ImageFont.load_default()
            font_small = font

        y = 20
        title = f"Week of {week_start.strftime('%d %b')} — {week_start + timedelta(days=6):%d %b %Y}"
        draw.text((20, y), title, fill=(0, 0, 0), font=font)
        y += 40

        for i in range(7):
            d = week_start + timedelta(days=i)
            day_str = d.strftime("%a %d %b")
            draw.text((20, y + i * 32), day_str, fill=(60, 60, 60), font=font_small)

        if goals_text:
            y += 7 * 32 + 20
            draw.text((20, y), "Goals:", fill=(0, 0, 0), font=font_small)
            goals_short = (goals_text[:120] + "…") if len(goals_text) > 120 else goals_text
            draw.text((20, y + 22), goals_short, fill=(80, 80, 80), font=font_small)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        caption = f"Week of {week_start.strftime('%d %b')}. {goals_text[:80]}..." if goals_text else title
        if len(caption) > 1024:
            caption = caption[:1021] + "..."
        return buf.getvalue(), caption
    except Exception as e:
        logger.warning("Week-at-a-glance image generation failed: %s", e)
        return None, ""
