#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright


SERVER_URL = os.getenv("SERVER_URL", "").strip()
HOSTSHIP_LOGIN = os.getenv("HOSTSHIP_LOGIN", "").strip()
HOSTSHIP_PASSWORD = os.getenv("HOSTSHIP_PASSWORD", "").strip()

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()

IS_PROXY = os.getenv("IS_PROXY", "false").lower() == "true"
PROXY_SERVER = os.getenv(
    "PROXY_SERVER",
    "socks5://127.0.0.1:1080"
).strip()

MANUAL_RUN = os.getenv(
    "MANUAL_RUN",
    "false"
).lower() == "true"

BJ_TZ = ZoneInfo("Asia/Shanghai")

# 多台服务器之间的等待秒数（可用环境变量 SERVER_INTERVAL 调整）
try:
    SERVER_INTERVAL = max(0, int(os.getenv("SERVER_INTERVAL", "5")))
except ValueError:
    SERVER_INTERVAL = 5

SERVER_URL_PREFIX = "https://panel.host-ship.com/server/"
ACCOUNT_URL = "https://panel.host-ship.com/account"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LOGIN_FAILED = -1


def mask_email(email):
    """a***a@email.com：保留本地部分首尾各一个字符和完整域名。"""
    local, sep, domain = email.strip().partition("@")

    if not sep or not local:
        return "***"

    if len(local) <= 2:
        return f"{local[0]}***@{domain}"

    return f"{local[0]}***{local[-1]}@{domain}"


# 登录账号（脱敏）。登录前先用 HOSTSHIP_LOGIN 兜底，登录后从账号页读取
ACCOUNT = {
    "masked": (
        mask_email(HOSTSHIP_LOGIN)
        if "@" in HOSTSHIP_LOGIN
        else "未知"
    ),
    "fetched": False,
}


def account_text():
    return ACCOUNT["masked"]


def parse_server_urls(raw):
    """SERVER_URL 支持多个地址，用换行 / 空格 / 逗号 / 分号分隔，自动去重。"""
    urls = []

    for item in re.split(r"[\s,;]+", raw.strip()):
        item = item.strip()

        if item and item not in urls:
            urls.append(item)

    return urls


def log(msg):
    print(
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}",
        flush=True
    )


def server_id(url):
    if not url:
        return "未知"

    return url.rstrip("/").split("/")[-1]


def node_status():
    if IS_PROXY:
        return "✅ 已启用"

    return "⚪ 未启用（直连）"


def get_days(text):
    if not text:
        return None

    match = re.search(
        r"(\d+)\s*Days?",
        text,
        re.I
    )

    if match:
        return int(match.group(1))

    return None


def beijing_now():
    return datetime.now(BJ_TZ)


def estimate_renew_date(status):
    days = get_days(status)

    if days is None:
        return None

    return (
        beijing_now().date()
        + timedelta(days=days)
    )


def tg(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        log("⚠️ Telegram 未配置，跳过通知")
        return False

    try:
        proxies = None

        if IS_PROXY:
            proxies = {
                "http": PROXY_SERVER,
                "https": PROXY_SERVER,
            }

        response = requests.post(
            (
                "https://api.telegram.org/"
                f"bot{TG_BOT_TOKEN}/sendMessage"
            ),
            json={
                "chat_id": TG_CHAT_ID,
                "text": text,
            },
            timeout=20,
            proxies=proxies,
        )

        if response.ok:
            log("✅ Telegram 通知发送成功")
            return True

        log(
            "❌ Telegram 通知失败: "
            + response.text
        )

        return False

    except Exception as exc:
        log(
            f"❌ Telegram 通知异常: {exc}"
        )
        return False


def current_ip():
    try:
        proxies = None

        if IS_PROXY:
            proxies = {
                "http": PROXY_SERVER,
                "https": PROXY_SERVER,
            }

        response = requests.get(
            "https://api.ipify.org",
            timeout=15,
            proxies=proxies,
        )

        if response.ok:
            return response.text.strip()

        return "获取失败"

    except Exception:
        return "获取失败"


def build_check_message(sid, status, ip):
    days = get_days(status)
    renew_date = estimate_renew_date(status)
    now = beijing_now()

    lines = [
        "⏳ Host-Ship 检查完成",
        "",
        f"🖥️ 服务器：#{sid}",
        f"👤 账号：{account_text()}",
        f"🌐 节点状态：{node_status()}",
        f"📍 出口IP：{ip}",
        f"🕗 检查时间：{now.strftime('%Y/%m/%d %H:%M')}",
        "",
        "🔒 当前状态：未到续期时间",
    ]

    if days is not None:
        lines.append(
            f"⏱️ 距离续期：约 {days} 天"
        )

    if renew_date is not None:
        lines.append(
            "📆 预计可续期："
            + renew_date.strftime("%Y/%m/%d")
        )

    if days is None:
        lines.append(
            f"📅 面板状态：{status}"
        )

    lines.append(
        "⏰ 自动检查：每天 08:00（北京时间）"
    )

    return "\n".join(lines)


def build_success_message(sid, before, after, ip):
    before_days = get_days(before)
    after_days = get_days(after)
    now = beijing_now()

    lines = [
        "🎉 Host-Ship 续期成功",
        "",
        f"🖥️ 服务器：#{sid}",
        f"👤 账号：{account_text()}",
        f"🌐 节点状态：{node_status()}",
        f"📍 出口IP：{ip}",
        f"🕗 续期时间：{now.strftime('%Y/%m/%d %H:%M')}",
        "",
    ]

    if before_days is not None:
        lines.append(
            f"📅 续期前：约 {before_days} 天"
        )
    else:
        lines.append(
            f"📅 续期前：{before}"
        )

    if after_days is not None:
        lines.append(
            f"✅ 续期后：约 {after_days} 天"
        )
    else:
        lines.append(
            f"✅ 续期后：{after}"
        )

    lines.append(
        "⏰ 自动检查：每天 08:00（北京时间）"
    )

    return "\n".join(lines)


def build_error_message(sid, title, reason, ip):
    now = beijing_now()

    return (
        f"{title}\n\n"
        f"🖥️ 服务器：#{sid}\n"
        f"👤 账号：{account_text()}\n"
        f"🌐 节点状态：{node_status()}\n"
        f"📍 出口IP：{ip}\n"
        f"🕗 检查时间：{now.strftime('%Y/%m/%d %H:%M')}\n\n"
        f"⚠️ 原因：{reason}"
    )


def first_visible(page, selectors):
    for selector in selectors:
        locator = page.locator(
            selector
        ).first

        try:
            if (
                locator.count()
                and locator.is_visible()
            ):
                return locator

        except Exception:
            pass

    return None


def goto_retry(page, url, tries=3):
    """打开页面，网络抖动时自动重试。"""
    for attempt in range(1, tries + 1):
        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            return

        except Exception as exc:
            if attempt == tries:
                raise

            log(
                f"⚠️ 打开页面失败（第 {attempt} 次）：{exc}，"
                "5 秒后重试"
            )
            time.sleep(5)


def login_if_needed(page, url):
    goto_retry(page, url)

    time.sleep(2)

    body = page.locator(
        "body"
    ).inner_text().lower()

    if (
        "/server/" in page.url
        and "password" not in body
    ):
        return True

    email = first_visible(
        page,
        [
            'input[name="email"]',
            'input[type="email"]',
            'input[name="username"]',
            'input[autocomplete="username"]',
        ],
    )

    password = first_visible(
        page,
        [
            'input[name="password"]',
            'input[type="password"]',
            'input[autocomplete="current-password"]',
        ],
    )

    if not email or not password:
        log(
            "❌ 没找到登录框，"
            f"当前页面: {page.url}"
        )
        return False

    if (
        not HOSTSHIP_LOGIN
        or not HOSTSHIP_PASSWORD
    ):
        log(
            "❌ 缺少 HOSTSHIP_LOGIN "
            "/ HOSTSHIP_PASSWORD"
        )
        return False

    log("🔐 正在登录 Host-Ship...")

    email.fill(HOSTSHIP_LOGIN)
    password.fill(HOSTSHIP_PASSWORD)

    submit = first_visible(
        page,
        [
            'button[type="submit"]',
            'button:has-text("Login")',
            'button:has-text("Sign in")',
            'button:has-text("Log in")',
        ],
    )

    if not submit:
        log("❌ 没找到登录按钮")
        return False

    submit.click()

    page.wait_for_timeout(3000)

    text = page.locator(
        "body"
    ).inner_text().lower()

    challenge_words = [
        "captcha",
        "verify you are human",
        "security check",
        "cloudflare",
    ]

    if any(
        word in text
        for word in challenge_words
    ):
        log(
            "⚠️ 检测到验证码/"
            "安全验证，需要手动处理"
        )
        return False

    goto_retry(page, url)

    page.wait_for_timeout(2000)

    return "/server/" in page.url


def get_renewal_text(page):
    text = page.locator(
        "body"
    ).inner_text()

    patterns = [
        r"Renewal\s+in\s+\d+\s+Days?",
        r"Renew\s+in\s+\d+\s+Days?",
        r"\d+\s+Days?\s+until\s+renewal",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.I,
        )

        if match:
            return match.group(0)

    if re.search(
        r"Renew\s+Limit\s+Reached",
        text,
        re.I,
    ):
        return "Renew Limit Reached"

    return "未识别"


def find_renew_button(page):
    candidates = [
        page.get_by_role(
            "button",
            name=re.compile(
                r"^Renew(?:\s+Now|\s+Server)?$",
                re.I,
            ),
        ),
        page.get_by_role(
            "link",
            name=re.compile(
                r"^Renew(?:\s+Now|\s+Server)?$",
                re.I,
            ),
        ),
        page.locator(
            'button:has-text("Renew")'
        ),
        page.locator(
            'a:has-text("Renew")'
        ),
    ]

    for group in candidates:
        try:
            count = group.count()

            for i in range(count):
                item = group.nth(i)

                if item.is_visible():
                    return item

        except Exception:
            pass

    return None


def confirm_renewal(page):
    """Wait for the renewal dialog and click the real submit button."""
    title = page.get_by_text(
        re.compile(
            r"Confirm\s+server\s+renewal",
            re.I,
        )
    ).first

    try:
        title.wait_for(
            state="visible",
            timeout=8000,
        )
    except Exception:
        log("❌ 点击 Renew 后未出现续期确认弹窗")
        return False

    confirm_buttons = [
        page.get_by_role(
            "dialog"
        ).last.get_by_role(
            "button",
            name=re.compile(
                r"^Renew\s+now$",
                re.I,
            ),
        ),
        page.get_by_role(
            "button",
            name=re.compile(
                r"^Renew\s+now$",
                re.I,
            ),
        ),
        page.locator(
            'button:has-text("Renew now")'
        ),
    ]

    for group in confirm_buttons:
        try:
            count = group.count()

            for i in range(count):
                button = group.nth(i)

                if (
                    button.is_visible()
                    and button.is_enabled()
                ):
                    log(
                        "✅ 确认弹窗已打开，"
                        "点击 Renew now..."
                    )
                    button.click()
                    return True

        except Exception:
            pass

    log("❌ 确认弹窗中未找到可点击的 Renew now")
    return False


def renewal_succeeded(before, after, body_text):
    text = body_text.lower()
    success_words = [
        "renewed successfully",
        "renewal successful",
        "successfully renewed",
        "renew limit reached",
    ]

    if any(word in text for word in success_words):
        return True

    before_days = get_days(before)
    after_days = get_days(after)

    return (
        before_days is not None
        and after_days is not None
        and after_days > before_days
    )


def wait_for_renewal_result(page, before):
    """Poll once, then reload to avoid reading a stale SPA state."""
    after = get_renewal_text(page)

    for attempt in range(5):
        body_text = page.locator(
            "body"
        ).inner_text()
        after = get_renewal_text(page)

        if renewal_succeeded(
            before,
            after,
            body_text,
        ):
            return True, after

        page.wait_for_timeout(2000)

        if attempt == 1:
            page.reload(
                wait_until="domcontentloaded",
                timeout=60000,
            )
            page.wait_for_timeout(2000)

    return False, after


def fetch_account_email(page):
    """打开账号页，读取邮箱输入框里的邮箱；失败返回 None。"""
    try:
        goto_retry(page, ACCOUNT_URL)

        try:
            page.wait_for_function(
                "() => [...document.querySelectorAll('input')]"
                ".some(i => (i.value || '').includes('@'))",
                timeout=10000,
            )
        except Exception:
            pass

        values = page.eval_on_selector_all(
            "input",
            "els => els.map(e => e.value || '')",
        )

        for value in values:
            value = value.strip()

            if EMAIL_RE.match(value):
                return value

    except Exception as exc:
        log(f"⚠️ 读取账号邮箱失败：{exc}")

    return None


def notify_not_due(sid, status, ip):
    """未到续期时间：仅手动运行时发 Telegram。"""
    if MANUAL_RUN:
        tg(build_check_message(sid, status, ip))


def process_server(page, url, sid, ip):
    """处理单台服务器，返回 0 成功/无需操作，1 失败，LOGIN_FAILED 登录失败。"""
    if not login_if_needed(page, url):
        page.screenshot(
            path=f"hostship_{sid}_login_fail.png",
            full_page=True,
        )

        tg(
            build_error_message(
                sid,
                "❌ Host-Ship 登录失败",
                "登录失败或遇到安全验证",
                ip,
            )
        )

        return LOGIN_FAILED

    if not ACCOUNT["fetched"]:
        ACCOUNT["fetched"] = True

        email = fetch_account_email(page)

        if email:
            ACCOUNT["masked"] = mask_email(email)
            log(f"👤 登录账号：{ACCOUNT['masked']}")
        else:
            log("⚠️ 未能从账号页读取邮箱，使用兜底值")

        # 回到服务器页面继续
        goto_retry(page, url)
        page.wait_for_timeout(2000)

    log("✅ 页面已就绪")

    before = get_renewal_text(page)

    log(f"📅 当前续期状态：{before}")

    body = page.locator("body").inner_text()

    if re.search(r"Renew\s+Limit\s+Reached", body, re.I):
        log("⏳ 目前未到续期时间，不进行操作")

        notify_not_due(sid, before, ip)

        return 0

    button = find_renew_button(page)

    if not button:
        page.screenshot(
            path=f"hostship_{sid}_no_renew_button.png",
            full_page=True,
        )

        tg(
            build_error_message(
                sid,
                "⚠️ Host-Ship 需要检查",
                f"没有找到可用的 Renew 按钮；{before}",
                ip,
            )
        )

        return 1

    try:
        disabled = button.is_disabled()
    except Exception:
        disabled = False

    if disabled:
        log("⏳ Renew 按钮当前不可点击")

        notify_not_due(sid, before, ip)

        return 0

    log("🔄 已到续期窗口，点击 Renew...")

    button.click()

    if not confirm_renewal(page):
        page.screenshot(
            path=f"hostship_{sid}_confirm_fail.png",
            full_page=True,
        )

        tg(
            build_error_message(
                sid,
                "❌ Host-Ship 续期确认失败",
                "点击第一层 Renew 后，未能点击确认弹窗中的 Renew now",
                ip,
            )
        )

        return 1

    success, after = wait_for_renewal_result(page, before)

    if success:
        log(f"✅ 续期成功：{before} -> {after}")

        tg(build_success_message(sid, before, after, ip))

        return 0

    page.screenshot(
        path=f"hostship_{sid}_renew_uncertain.png",
        full_page=True,
    )

    log("⚠️ 已点击续期，但无法确认结果")

    tg(
        build_error_message(
            sid,
            "⚠️ Host-Ship 续期结果需要检查",
            f"续期前：{before}；续期后：{after}",
            ip,
        )
    )

    return 1


def main():
    urls = parse_server_urls(SERVER_URL)

    if not urls:
        log("❌ 未配置 SERVER_URL")

        tg(
            "❌ Host-Ship 配置错误\n"
            "未配置 SERVER_URL"
        )

        return 1

    bad = [u for u in urls if not u.startswith(SERVER_URL_PREFIX)]

    if bad:
        log(f"❌ SERVER_URL 不正确：{bad}")

        tg(
            "❌ Host-Ship 配置错误\n"
            f"有 {len(bad)} 个地址不是服务器详情页地址"
        )

        return 1

    log("======================================")
    log(" Host-Ship Free Auto Renew")
    log(f" 服务器数量：{len(urls)}")
    log("======================================")

    log(f"🌐 节点状态：{node_status()}")

    ip = current_ip()

    log(f"📍 当前出口IP：{ip}")

    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy={"server": PROXY_SERVER} if IS_PROXY else None,
            args=["--no-sandbox"],
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000,
            },
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        try:
            for index, url in enumerate(urls, start=1):
                sid = server_id(url)

                log(f"━━ [{index}/{len(urls)}] 服务器 #{sid} ━━")

                try:
                    code = process_server(page, url, sid, ip)

                except Exception as exc:
                    log(f"❌ 运行异常：{exc}")

                    try:
                        page.screenshot(
                            path=f"hostship_{sid}_error.png",
                            full_page=True,
                        )
                    except Exception:
                        pass

                    tg(
                        build_error_message(
                            sid,
                            "❌ Host-Ship 自动续期异常",
                            str(exc),
                            ip,
                        )
                    )

                    code = 1

                results[sid] = code

                # 登录/验证码问题对同一账号的所有服务器都一样，不再继续
                if code == LOGIN_FAILED:
                    for rest in urls[index:]:
                        results[server_id(rest)] = LOGIN_FAILED

                    log("⛔ 登录失败，跳过剩余服务器")
                    break

                if index < len(urls) and SERVER_INTERVAL:
                    log(f"⏱️ 等待 {SERVER_INTERVAL} 秒后处理下一台...")
                    time.sleep(SERVER_INTERVAL)

        finally:
            browser.close()

    failed = [sid for sid, code in results.items() if code != 0]

    log("======================================")
    log(f" 完成：成功/无需操作 {len(results) - len(failed)}，失败 {len(failed)}")

    for sid, code in results.items():
        log(f"   #{sid}: {'OK' if code == 0 else 'FAIL'}")

    log("======================================")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
