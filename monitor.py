from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


APPLE_URL = "https://www.apple.com/tw/shop/refurbished/mac"
DEFAULT_STATE_PATH = Path(__file__).with_name("state.json")
HEARTBEAT_INTERVAL = timedelta(days=30)
PRODUCT_LINK_RE = re.compile(r"/shop/product/([^/?#]+)", re.IGNORECASE)
TARGET_MODEL_RE = re.compile(r"\bMacBook\s+Air\b", re.IGNORECASE)
TARGET_CHIP_RE = re.compile(r"(?<![A-Za-z0-9])M5(?![A-Za-z0-9])", re.IGNORECASE)
PRICE_RE = re.compile(r"NT\$\s*[\d,]+")


class MonitorError(RuntimeError):
    """Base exception for a monitor run that should be retried."""


class PageParseError(MonitorError):
    """Raised when the Apple page no longer looks like a product listing."""


class NotificationError(MonitorError):
    """Raised when Discord did not accept a notification."""


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    price: str
    url: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def create_http_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (compatible; AppleRefurbishedMonitor/1.0; "
                "+https://github.com/)"
            ),
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
        }
    )
    return session


def fetch_page(session: requests.Session, url: str = APPLE_URL) -> str:
    try:
        response = session.get(url, timeout=(10, 30))
        response.raise_for_status()
    except requests.RequestException as exc:
        raise MonitorError(f"無法取得 Apple 整修品頁面：{exc}") from exc

    if not response.text.strip():
        raise PageParseError("Apple 整修品頁面是空白內容")
    return response.text


def _find_product_container(link: Tag) -> Tag:
    fallback = link
    for parent in [link, *link.parents]:
        if not isinstance(parent, Tag):
            continue
        fallback = parent
        text = normalize_text(parent.get_text(" ", strip=True))
        if PRICE_RE.search(text) and len(text) < 2500:
            return parent
        if parent.name in {"body", "html"}:
            break
    return fallback


def _extract_name(link: Tag, container: Tag) -> str:
    candidates: list[str] = []
    for value in (link.get("aria-label"), link.get("title")):
        if isinstance(value, str):
            candidates.append(value)
    candidates.append(link.get_text(" ", strip=True))
    for element in container.select("h2, h3, [class*='title']"):
        candidates.append(element.get_text(" ", strip=True))

    cleaned: list[str] = []
    for candidate in candidates:
        value = normalize_text(PRICE_RE.sub("", candidate)).strip(" -")
        if value and value not in cleaned:
            cleaned.append(value)

    preferred = [value for value in cleaned if "整修品" in value]
    if not preferred:
        preferred = [value for value in cleaned if "Mac" in value]
    return max(preferred or cleaned, key=len, default="")


def parse_products(html: str, base_url: str = APPLE_URL) -> list[Product]:
    soup = BeautifulSoup(html, "html.parser")
    links = soup.select('a[href*="/shop/product/"]')
    if not links:
        raise PageParseError(
            "找不到 Apple 商品連結，頁面結構可能已改變；為避免誤判，狀態不會更新"
        )

    products: dict[str, Product] = {}
    for link in links:
        href = link.get("href")
        if not isinstance(href, str):
            continue
        url = urljoin(base_url, href)
        match = PRODUCT_LINK_RE.search(urlparse(url).path)
        product_id = match.group(1) if match else hashlib.sha256(url.encode()).hexdigest()[:16]
        container = _find_product_container(link)
        name = _extract_name(link, container)
        card_text = normalize_text(container.get_text(" ", strip=True))
        price_match = PRICE_RE.search(card_text)
        price = normalize_text(price_match.group(0)) if price_match else "價格請見 Apple 網站"
        if name:
            products.setdefault(
                product_id,
                Product(product_id=product_id, name=name, price=price, url=url),
            )

    if not products:
        raise PageParseError(
            "找到商品連結但無法解析商品名稱；為避免誤判，狀態不會更新"
        )
    return list(products.values())


def is_target_product(product: Product) -> bool:
    return bool(
        TARGET_MODEL_RE.search(product.name) and TARGET_CHIP_RE.search(product.name)
    )


def filter_target_products(products: Iterable[Product]) -> list[Product]:
    return [product for product in products if is_target_product(product)]


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"active_product_ids": [], "last_heartbeat": None}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MonitorError(f"無法讀取狀態檔 {path}：{exc}") from exc
    if not isinstance(state.get("active_product_ids"), list):
        raise MonitorError("狀態檔格式錯誤：active_product_ids 必須是陣列")
    return state


def heartbeat_is_due(state: dict[str, Any], now: datetime) -> bool:
    value = state.get("last_heartbeat")
    if not value:
        return True
    try:
        previous = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return True
    return now - previous.astimezone(timezone.utc) >= HEARTBEAT_INTERVAL


def save_state(path: Path, active_ids: Iterable[str], now: datetime) -> None:
    state = {
        "active_product_ids": sorted(set(active_ids)),
        "last_heartbeat": isoformat_z(now),
    }
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def build_discord_payload(products: list[Product], detected_at: datetime) -> dict[str, Any]:
    embeds = []
    timestamp = isoformat_z(detected_at)
    for product in products:
        embeds.append(
            {
                "title": product.name[:256],
                "url": product.url,
                "description": f"**價格：{product.price}**\n[立即前往 Apple 查看商品]({product.url})",
                "color": 0x34C759,
                "timestamp": timestamp,
                "footer": {"text": f"Apple 台灣整修品｜商品編號 {product.product_id}"},
            }
        )
    return {
        "content": "🚨 **發現 MacBook Air M5 整修品！**",
        "username": "Apple 整修品監控器",
        "embeds": embeds,
        "allowed_mentions": {"parse": []},
    }


def _post_webhook(
    session: requests.Session, webhook_url: str, payload: dict[str, Any]
) -> None:
    separator = "&" if "?" in webhook_url else "?"
    url = f"{webhook_url}{separator}wait=true"
    try:
        response = session.post(url, json=payload, timeout=(10, 30))
        response.raise_for_status()
    except requests.RequestException as exc:
        raise NotificationError(f"Discord Webhook 傳送失敗：{exc}") from exc


def send_discord_notification(
    session: requests.Session,
    webhook_url: str,
    products: list[Product],
    detected_at: datetime,
) -> None:
    for start in range(0, len(products), 10):
        _post_webhook(
            session,
            webhook_url,
            build_discord_payload(products[start : start + 10], detected_at),
        )


def send_test_notification(
    session: requests.Session, webhook_url: str, now: datetime
) -> None:
    payload = {
        "content": "✅ **Apple 整修品監控器測試成功**",
        "username": "Apple 整修品監控器",
        "embeds": [
            {
                "title": "Discord 通知已正確設定",
                "description": "之後偵測到 MacBook Air M5 整修品時，會在這個頻道通知你。",
                "color": 0x007AFF,
                "timestamp": isoformat_z(now),
            }
        ],
        "allowed_mentions": {"parse": []},
    }
    _post_webhook(session, webhook_url, payload)


def run_monitor(
    session: requests.Session,
    webhook_url: str,
    state_path: Path,
    now: datetime,
) -> tuple[list[Product], list[Product]]:
    html = fetch_page(session)
    all_products = parse_products(html)
    targets = filter_target_products(all_products)
    state = load_state(state_path)
    previous_ids = set(str(value) for value in state["active_product_ids"])
    current_ids = {product.product_id for product in targets}
    new_products = [product for product in targets if product.product_id not in previous_ids]

    # Notify first. A failed notification must never advance the state.
    if new_products:
        send_discord_notification(session, webhook_url, new_products, now)

    if current_ids != previous_ids or heartbeat_is_due(state, now):
        save_state(state_path, current_ids, now)
    return targets, new_products


def require_webhook_url() -> str:
    value = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not value.startswith("https://discord.com/api/webhooks/") and not value.startswith(
        "https://discordapp.com/api/webhooks/"
    ):
        raise MonitorError(
            "請在環境變數或 GitHub Secret 設定有效的 DISCORD_WEBHOOK_URL"
        )
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="監控 Apple 台灣 MacBook Air M5 整修品")
    parser.add_argument("--test-notification", action="store_true", help="只傳送 Discord 測試通知")
    parser.add_argument("--dry-run", action="store_true", help="檢查 Apple 頁面但不通知、不更新狀態")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH, help="狀態檔位置")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    session = create_http_session()
    now = utc_now()
    try:
        if args.test_notification:
            send_test_notification(session, require_webhook_url(), now)
            print("Discord 測試通知已傳送。")
            return 0

        if args.dry_run:
            products = filter_target_products(parse_products(fetch_page(session)))
            print(json.dumps([asdict(product) for product in products], ensure_ascii=False, indent=2))
            print(f"檢查完成，共找到 {len(products)} 項 MacBook Air M5 整修品。")
            return 0

        targets, new_products = run_monitor(
            session, require_webhook_url(), args.state, now
        )
        print(
            f"檢查完成：目前 {len(targets)} 項符合，"
            f"本次新出現 {len(new_products)} 項。"
        )
        return 0
    except MonitorError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
