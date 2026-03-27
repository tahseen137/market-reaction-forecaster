from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from xml.etree import ElementTree

import httpx

from app.config import Settings
from app.universe import SAMPLE_PRICE_MAP


@dataclass
class QuoteSnapshot:
    symbol: str
    price: float
    day_change_pct: float
    as_of: datetime
    source_status: str


@dataclass
class NormalizedEventCandidate:
    symbol: str
    event_type: str
    headline: str
    summary: str
    thesis: str
    source_label: str
    source_type: str
    source_url: str
    occurred_at: datetime
    directional_bias: float
    tags: list[str]
    content_hash: str


def _now() -> datetime:
    return datetime.now(UTC)


def hash_content(*parts: str) -> str:
    joined = "||".join(part.strip() for part in parts if part)
    return sha256(joined.encode("utf-8")).hexdigest()


class TwelveDataClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def get_quote(self, symbol: str) -> QuoteSnapshot:
        if not self.settings.twelve_data_api_key:
            return QuoteSnapshot(
                symbol=symbol,
                price=SAMPLE_PRICE_MAP.get(symbol, 100.0),
                day_change_pct=0.8,
                as_of=_now(),
                source_status="delayed",
            )
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(
                    "https://api.twelvedata.com/quote",
                    params={"symbol": symbol, "apikey": self.settings.twelve_data_api_key},
                )
                response.raise_for_status()
                payload = response.json()
            price = float(payload.get("close") or payload.get("price") or SAMPLE_PRICE_MAP.get(symbol, 100.0))
            percent_change = payload.get("percent_change") or 0.0
            source_status = "real-time"
        except Exception:
            price = SAMPLE_PRICE_MAP.get(symbol, 100.0)
            percent_change = 0.8
            source_status = "delayed"
        return QuoteSnapshot(
            symbol=symbol,
            price=price,
            day_change_pct=float(percent_change),
            as_of=_now(),
            source_status=source_status,
        )


class FinnhubClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def get_company_news(self, symbol: str, *, start_date: date | None = None, end_date: date | None = None) -> list[NormalizedEventCandidate]:
        if not self.settings.finnhub_api_key:
            return []
        start = start_date or (_now().date() - timedelta(days=3))
        end = end_date or _now().date()
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(
                    "https://finnhub.io/api/v1/company-news",
                    params={
                        "symbol": symbol,
                        "from": start.isoformat(),
                        "to": end.isoformat(),
                        "token": self.settings.finnhub_api_key,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return []
        candidates: list[NormalizedEventCandidate] = []
        for item in payload[:5]:
            headline = str(item.get("headline", "")).strip()
            summary = str(item.get("summary", "")).strip()
            published = datetime.fromtimestamp(int(item.get("datetime", 0) or 0), tz=UTC) if item.get("datetime") else _now()
            candidates.append(
                NormalizedEventCandidate(
                    symbol=symbol,
                    event_type="macro" if "fed" in headline.casefold() else "analyst_rating",
                    headline=headline,
                    summary=summary,
                    thesis=summary or headline,
                    source_label="Finnhub News",
                    source_type="news",
                    source_url=str(item.get("url", "")),
                    occurred_at=published,
                    directional_bias=0.02,
                    tags=["news"],
                    content_hash=hash_content(symbol, headline, summary, str(item.get("url", ""))),
                )
            )
        return candidates


class SecEdgarClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def get_recent_filings(self, symbol: str, cik: str | None) -> list[NormalizedEventCandidate]:
        if not cik:
            return []
        padded_cik = cik.zfill(10)
        headers = {"User-Agent": self.settings.sec_user_agent}
        try:
            with httpx.Client(timeout=10, headers=headers) as client:
                response = client.get(f"https://data.sec.gov/submissions/CIK{padded_cik}.json")
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return []
        filings = payload.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        dates = filings.get("filingDate", [])
        accessions = filings.get("accessionNumber", [])
        primary_docs = filings.get("primaryDocument", [])
        candidates: list[NormalizedEventCandidate] = []
        for form, filing_date, accession, primary_doc in list(zip(forms, dates, accessions, primary_docs, strict=False))[:3]:
            if form not in {"8-K", "10-Q", "10-K"}:
                continue
            clean_accession = str(accession).replace("-", "")
            source_url = f"https://www.sec.gov/Archives/edgar/data/{int(padded_cik)}/{clean_accession}/{primary_doc}"
            candidates.append(
                NormalizedEventCandidate(
                    symbol=symbol,
                    event_type="earnings" if form in {"10-Q", "10-K"} else "regulatory",
                    headline=f"{symbol} filed {form}",
                    summary=f"Recent SEC filing detected for {symbol}.",
                    thesis=f"Recent SEC filing detected for {symbol}.",
                    source_label="SEC EDGAR",
                    source_type="sec_filing",
                    source_url=source_url,
                    occurred_at=datetime.fromisoformat(f"{filing_date}T16:00:00+00:00"),
                    directional_bias=0.03 if form in {"10-Q", "10-K"} else -0.02,
                    tags=[form.casefold()],
                    content_hash=hash_content(symbol, form, filing_date, accession),
                )
            )
        return candidates


class RssFeedClient:
    def get_items(self, symbol: str, feed_url: str) -> list[NormalizedEventCandidate]:
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(feed_url)
                response.raise_for_status()
        except Exception:
            return []
        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError:
            return []
        items: list[NormalizedEventCandidate] = []
        for item in root.findall(".//item")[:3]:
            title = item.findtext("title", default="").strip()
            link = item.findtext("link", default="").strip()
            description = item.findtext("description", default="").strip()
            if not title:
                continue
            items.append(
                NormalizedEventCandidate(
                    symbol=symbol,
                    event_type="product_launch" if "launch" in title.casefold() else "guidance",
                    headline=title,
                    summary=description,
                    thesis=description or title,
                    source_label="Investor Relations",
                    source_type="rss",
                    source_url=link,
                    occurred_at=_now(),
                    directional_bias=0.05,
                    tags=["rss"],
                    content_hash=hash_content(symbol, title, link),
                )
            )
        return items
