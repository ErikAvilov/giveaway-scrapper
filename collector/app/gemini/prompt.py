"""Prompts for structured giveaway analysis (single + micro-batch)."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

SYSTEM_INSTRUCTION = """You are a careful giveaway/contest fact extractor.

Return ONLY structured data matching the provided JSON schema. Never write prose outside the schema.

Rules:
- Extract facts only from the supplied page URL, title, text, and links.
- Never invent eligibility, dates, prizes, or requirements.
- Use null when a field is missing or uncertain.
- is_giveaway=true only if this page is itself an actionable giveaway/contest people can enter.
- is_giveaway=false for news/articles that merely discuss giveaways, product pages, gift guides, expired archives without entry, or unrelated content.
- Distinguish free entry from purchase-required promotions.
- France eligibility is a hard gate. Set france_eligibility to eligible|ineligible|unknown.
- Accept only positive evidence: France listed, worldwide/international (France not excluded),
  EU/Europe including France, or an explicit country list containing France.
- Reject UK-only, US/USA-only, Canada-only, Australia-only, or country lists without France.
- Never guess: English-language pages are NOT automatically international.
- Never assume an aggregator listing implies France eligibility.
- If eligibility cannot be determined from the supplied text, france_eligibility=unknown.
- Keep eligible_france in sync: eligible→true, ineligible→false, unknown→null.
- Fill eligibility_reason, eligible_countries, and excluded_countries from explicit text only.
- Prefer dates present on the page; do not guess.
- When is_giveaway=false, set rejection_reason to a short factual reason.
- confidence must reflect how sure you are (0 to 1).

Prize preference (critical):
- Classify the ACTUAL prize for economic usefulness, not advertised marketing value.
- Wanted: cash, bank/PayPal transfers, prepaid Visa/Mastercard, broadly usable gift cards,
  electronics, appliances, furniture, tools, bikes/scooters, useful physical goods,
  video game keys / Steam / console games, useful software licenses.
- Unwanted (wanted_prize=false, prize_priority 0-9): trips, hotels, flights, travel packages,
  concert/festival/sports/cinema tickets, escape rooms, restaurants, spa/wellness,
  experiences, wedding packages, photography sessions, coaching, courses, local activities,
  books/ebook bundles, magazine subscriptions, discount coupons, percentage off,
  vouchers that require meaningful additional spending, narrow retailer vouchers.
- Example: "Wedding package worth €18,000" → wanted_prize=false, prize_priority near 0.
- Example: "Luxury weekend worth €5,000" → unwanted despite high monetary value.
- Example: "PS5 + trip to Tokyo" → wanted_prize=true because a desirable asset is included.
- Gift cards: prepaid Visa/Mastercard/PayPal = high value; min-spend vouchers =
  restricted_gift_card, wanted_prize=false, requires_additional_spend=true.
- Set requires_travel / requires_additional_spend from the prize terms when clear.

When multiple GIVEAWAY blocks are provided in one request:
- Each giveaway is independent; never mix information between giveaways.
- Preserve each giveaway_id exactly as supplied (opaque UUID).
- Output exactly one result item for every supplied giveaway_id.
- Do not invent missing information; use null when uncertain.
- Do not omit giveaways; do not invent extra giveaway_ids.
"""


def build_user_prompt(
    *,
    url: str,
    title: str | None,
    text: str | None,
    links: list[str],
) -> str:
    links_block = "\n".join(f"- {link}" for link in links[:40]) if links else "- (none)"
    body = (text or "").strip() or "(empty)"
    return (
        "Analyze this page for giveaway/contest facts.\n\n"
        f"URL:\n{url}\n\n"
        f"Title:\n{title or '(none)'}\n\n"
        f"Relevant outgoing links:\n{links_block}\n\n"
        f"Cleaned page text:\n{body}\n"
    )


def build_batch_user_prompt(
    items: Sequence[tuple[UUID, str, str | None, str | None, list[str]]],
) -> str:
    """
    Build one user prompt containing multiple independent giveaways.

    Each tuple is (giveaway_id, url, title, text, links).
    """
    parts = [
        (
            "Analyze each GIVEAWAY independently. Return one structured item per id.\n"
            "Never mix facts across giveaways. Preserve every giveaway_id exactly.\n"
        )
    ]
    for giveaway_id, url, title, text, links in items:
        links_block = "\n".join(f"- {link}" for link in links[:40]) if links else "- (none)"
        body = (text or "").strip() or "(empty)"
        parts.append(
            "GIVEAWAY\n"
            f"id: {giveaway_id}\n"
            f"url: {url}\n"
            f"title: {title or '(none)'}\n"
            f"links:\n{links_block}\n"
            f"text:\n{body}\n"
        )
    return "\n".join(parts)
