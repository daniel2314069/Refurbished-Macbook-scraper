from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import requests

import monitor


NOW = datetime(2026, 7, 14, 8, 0, tzinfo=timezone.utc)


def page(*cards: str) -> str:
    return "<html><body><ul>" + "".join(cards) + "</ul></body></html>"


def card(product_id: str, name: str, price: str = "NT$35,900") -> str:
    return f"""
    <li class="rf-producttile">
      <a href="/tw/shop/product/{product_id}/refurbished-mac">
        <h3>{name}</h3>
      </a>
      <div class="price">{price}</div>
    </li>
    """


M5_AIR = card(
    "GTEST1TA-A",
    "13 吋 MacBook Air Apple M5 晶片配備 10 核心 CPU - 午夜色 (整修品)",
)
M5_AIR_SECOND = card(
    "GTEST2TA-A",
    "15 吋 MacBook Air Apple M5晶片配備 10 核心 GPU - 星光色 (整修品)",
    "NT$42,900",
)
M5_PRO = card(
    "GPROTA-A",
    "14 吋 MacBook Pro Apple M5 Pro 晶片 - 太空黑色 (整修品)",
)
M4_AIR = card(
    "GOLDTA-A",
    "13 吋 MacBook Air Apple M4 晶片 - 銀色 (整修品)",
)


def test_parse_and_filter_only_macbook_air_m5() -> None:
    products = monitor.parse_products(page(M5_AIR, M5_AIR_SECOND, M5_PRO, M4_AIR))
    targets = monitor.filter_target_products(products)

    assert [product.product_id for product in targets] == ["GTEST1TA-A", "GTEST2TA-A"]
    assert targets[0].price == "NT$35,900"
    assert targets[0].url.startswith("https://www.apple.com/tw/shop/product/")


@pytest.mark.parametrize(
    "name",
    [
        "14 吋 MacBook Pro Apple M5 晶片 (整修品)",
        "13 吋 MacBook Air Apple M4 晶片 (整修品)",
        "Mac mini Apple M5 晶片 (整修品)",
        "13 吋 MacBook Air Apple M50 晶片 (整修品)",
    ],
)
def test_non_targets_do_not_match(name: str) -> None:
    product = monitor.Product("id", name, "NT$1", "https://example.com")
    assert not monitor.is_target_product(product)


def test_parse_rejects_empty_or_changed_page() -> None:
    with pytest.raises(monitor.PageParseError):
        monitor.parse_products("<html><body>暫時無內容</body></html>")


def test_discord_payload_contains_product_details() -> None:
    product = monitor.filter_target_products(monitor.parse_products(page(M5_AIR)))[0]
    payload = monitor.build_discord_payload([product], NOW)

    assert "MacBook Air M5" in payload["content"]
    assert payload["allowed_mentions"] == {"parse": []}
    assert product.name == payload["embeds"][0]["title"]
    assert "NT$35,900" in payload["embeds"][0]["description"]
    assert payload["embeds"][0]["url"] == product.url


def test_state_prevents_duplicates_and_allows_reappearance(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "state.json"
    current_html = page(M5_AIR, M5_PRO)
    sent: list[list[str]] = []

    monkeypatch.setattr(monitor, "fetch_page", lambda session: current_html)
    monkeypatch.setattr(
        monitor,
        "send_discord_notification",
        lambda session, webhook, products, now: sent.append(
            [product.product_id for product in products]
        ),
    )

    monitor.run_monitor(object(), "https://discord.com/api/webhooks/test/token", state_path, NOW)
    assert sent == [["GTEST1TA-A"]]

    monitor.run_monitor(
        object(),
        "https://discord.com/api/webhooks/test/token",
        state_path,
        NOW + timedelta(hours=1),
    )
    assert sent == [["GTEST1TA-A"]]

    current_html = page(M5_PRO)
    monitor.run_monitor(
        object(),
        "https://discord.com/api/webhooks/test/token",
        state_path,
        NOW + timedelta(hours=2),
    )
    assert json.loads(state_path.read_text(encoding="utf-8"))["active_product_ids"] == []

    current_html = page(M5_AIR)
    monitor.run_monitor(
        object(),
        "https://discord.com/api/webhooks/test/token",
        state_path,
        NOW + timedelta(hours=3),
    )
    assert sent == [["GTEST1TA-A"], ["GTEST1TA-A"]]


def test_failed_notification_does_not_advance_state(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        '{"active_product_ids": [], "last_heartbeat": null}\n', encoding="utf-8"
    )
    original = state_path.read_text(encoding="utf-8")
    monkeypatch.setattr(monitor, "fetch_page", lambda session: page(M5_AIR))

    def fail(*args, **kwargs):
        raise monitor.NotificationError("Discord unavailable")

    monkeypatch.setattr(monitor, "send_discord_notification", fail)
    with pytest.raises(monitor.NotificationError):
        monitor.run_monitor(
            object(), "https://discord.com/api/webhooks/test/token", state_path, NOW
        )
    assert state_path.read_text(encoding="utf-8") == original


def test_fetch_failure_is_retryable_monitor_error() -> None:
    class BrokenSession:
        def get(self, *args, **kwargs):
            raise requests.ConnectionError("offline")

    with pytest.raises(monitor.MonitorError, match="無法取得"):
        monitor.fetch_page(BrokenSession())


def test_heartbeat_due_after_thirty_days() -> None:
    state = {
        "active_product_ids": [],
        "last_heartbeat": monitor.isoformat_z(NOW - timedelta(days=29)),
    }
    assert not monitor.heartbeat_is_due(state, NOW)
    state["last_heartbeat"] = monitor.isoformat_z(NOW - timedelta(days=30))
    assert monitor.heartbeat_is_due(state, NOW)
