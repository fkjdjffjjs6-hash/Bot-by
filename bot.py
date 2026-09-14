#!/usr/bin/env python3
"""
Telegram Bot — Cloud Run Deployer (Final Complete Version)
- يخدم بلا Console
- معالجة Verify it's you
- Chrome Profile (يتخطى التحقق)
- لقطة شاشة عند كل خطوة
"""

import os
import sys
import re
import logging
import asyncio
import urllib.parse
import json
import time
from pathlib import Path

# ══════════════════════════════════════════════════════
#  ✅ إخفاء Console (Windows)
# ══════════════════════════════════════════════════════
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, 0)
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)
from playwright.async_api import async_playwright

# ══════════════════════════════════════════════════════
#  ⚙️ الإعدادات
# ══════════════════════════════════════════════════════
TELEGRAM_TOKEN = "8997125952:AAEywtOhE4s7XIQZfMLibGBtXMJNDss9NHI"
ADMIN_IDS = [6532494160]

SERVICE_NAME = "Mo7a-dx"
DOCKER_IMAGE = "docker.io/mo7adv/mo7a-dx:latest"

PREFERRED_REGIONS = [
    "us-central1", "us-east1", "us-west1",
    "europe-west1", "europe-west4",
    "asia-east1", "asia-southeast1", "australia-southeast1",
]

# ✅ مسار Chrome Profile (مهم للتحقق)
# خطوات:
# 1. افتح Chrome عادي
# 2. سجّل دخول بالحساب student-XX@qwiklabs.net
# 3. حل الـ verification يدوياً مرة واحدة
# 4. سكر Chrome تماماً
# 5. حط المسار تحت (Windows):
CHROME_USER_DATA = r"C:\Users\One\AppData\Local\Google\Chrome\User Data"
USE_CHROME_PROFILE = False  # ← خليها True باش يستعمل الـ profile

# ✅ المسارات
if sys.platform == "win32":
    BASE_DIR = Path(os.path.expanduser("~")) / "Desktop"
else:
    BASE_DIR = Path.home()

SHOTS_DIR = BASE_DIR / "bot_screenshots"
SHOTS_DIR.mkdir(exist_ok=True, parents=True)

COOKIES_FILE = BASE_DIR / "google_cookies.json"
LOG_FILE = BASE_DIR / "bot.log"

# ══════════════════════════════════════════════════════
#  ✅ Logging
# ══════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(str(LOG_FILE), encoding="utf-8")],
)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("playwright").setLevel(logging.WARNING)

log = logging.getLogger(__name__)

bot_data = {}
pending_data = {}  # ✅ للأرقام والأكواد


# ══════════════════════════════════════════════════════
#  helpers
# ══════════════════════════════════════════════════════
def extract_project_id(url):
    for pat in [r"project[=%]3D([a-z0-9-]+)", r"project=([a-z0-9-]+)",
                r"qwiklabs-gcp-[0-9a-f-]+"]:
        m = re.search(pat, urllib.parse.unquote(url))
        if m:
            pid = m.group(1) if "(" in pat else m.group(0)
            if "qwiklabs" in pid:
                return pid
    return None


def extract_email_from_url(url):
    decoded = urllib.parse.unquote(url)
    for pat in [r"Email[=%]3D([^&%#]+@[^&%#]+)",
                r"(student-[0-9a-f-]+@qwiklabs\.net)",
                r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"]:
        m = re.search(pat, decoded)
        if m and "@" in m.group(1) and len(m.group(1)) < 100:
            return m.group(1)
    return None


def is_sso_url(text):
    return any(k in text for k in [
        "skills.google", "google_sso",
        "console.cloud.google.com", "cloudshell",
    ])


async def send_screenshot(bot, chat_id, page, caption=""):
    try:
        path = SHOTS_DIR / f"shot_{int(time.time() * 1000)}.png"
        await page.screenshot(path=str(path), full_page=False)
        with open(path, "rb") as f:
            await bot.send_photo(chat_id=chat_id, photo=f,
                                 caption=caption[:1024] if caption else "📸")
        try:
            os.remove(path)
        except Exception:
            pass
    except Exception as e:
        log.error(f"Screenshot: {e}")


# ══════════════════════════════════════════════════════
#  Keyboards
# ══════════════════════════════════════════════════════
def region_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 تلقائي", callback_data="region:auto"),
         InlineKeyboardButton("🌍 عشوائي", callback_data="region:random")],
        [InlineKeyboardButton("🇺🇸 us-central1", callback_data="region:us-central1"),
         InlineKeyboardButton("🇺🇸 us-east1", callback_data="region:us-east1")],
        [InlineKeyboardButton("🇪🇺 europe-west1", callback_data="region:europe-west1"),
         InlineKeyboardButton("🌏 asia-east1", callback_data="region:asia-east1")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="region:cancel")],
    ])


def confirm_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأكيد وتشغيل", callback_data="confirm:yes")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="confirm:no")],
    ])


# ══════════════════════════════════════════════════════
#  Playwright helpers
# ══════════════════════════════════════════════════════
async def dismiss_dialogs(page):
    for txt in ["I understand", "Agree and continue", "Got it",
                "Accept", "Dismiss", "Close"]:
        try:
            btn = page.locator(f"button:has-text('{txt}')").first
            if await btn.is_visible(timeout=1500):
                await btn.click(timeout=3000)
                await asyncio.sleep(0.5)
        except Exception:
            pass
    try:
        close = page.locator("button[aria-label='Close']").first
        if await close.is_visible(timeout=1000):
            await close.click()
    except Exception:
        pass


async def write_angular_input(page, value, selectors, field_name="field"):
    for attempt in range(5):
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if not await el.is_visible(timeout=3000):
                    continue

                try:
                    await el.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass

                try:
                    await el.click(timeout=5000)
                except Exception:
                    await el.click(force=True, timeout=5000)

                await asyncio.sleep(0.5)

                try:
                    await el.press("Control+A")
                    await asyncio.sleep(0.2)
                    await el.press("Delete")
                    await asyncio.sleep(0.3)
                except Exception:
                    pass

                try:
                    await el.type(value, delay=40, timeout=10000)
                except Exception:
                    try:
                        await el.fill(value, timeout=5000)
                    except Exception:
                        pass

                await asyncio.sleep(0.5)

                try:
                    await el.press("Tab")
                except Exception:
                    pass

                await asyncio.sleep(0.5)

                try:
                    current = await el.input_value(timeout=2000)
                    if current and value in current:
                        return True
                except Exception:
                    pass

                break
            except Exception:
                continue

        await asyncio.sleep(2)

    return False


async def wait_fields_filled(page, bot, chat_id, status_cb):
    for check in range(30):
        await asyncio.sleep(2)

        try:
            img_val = ""
            for sel in [
                "input[placeholder*='Container image URL' i]",
                "input[formcontrolname='image']",
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=1000):
                        img_val = await el.input_value(timeout=2000)
                        if img_val:
                            break
                except Exception:
                    pass

            name_val = ""
            for sel in [
                "input[name='service-name']",
                "input[formcontrolname='serviceName']",
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=1000):
                        name_val = await el.input_value(timeout=2000)
                        if name_val:
                            break
                except Exception:
                    pass

            try:
                body = await page.locator("body").inner_text(timeout=3000)
                has_img_err = "Container image URL is required" in body
                has_name_err = "Service name is required" in body
            except Exception:
                has_img_err = False
                has_name_err = False

            if img_val and name_val and not has_img_err and not has_name_err:
                return True

        except Exception:
            pass

    return False


async def get_project_number(page, project_id):
    try:
        await page.goto(
            f"https://console.cloud.google.com/home/dashboard?project={project_id}",
            wait_until="domcontentloaded", timeout=30000,
        )
        await asyncio.sleep(3)
        await dismiss_dialogs(page)
        await asyncio.sleep(2)

        try:
            txt = await page.locator("text=Project number").locator(
                "xpath=following-sibling::*[1]"
            ).inner_text(timeout=5000)
            if txt.strip().isdigit() and len(txt.strip()) >= 10:
                return txt.strip()
        except Exception:
            pass

        body = await page.locator("body").inner_text(timeout=8000)
        m = re.search(r"Project number\s*\n?\s*(\d{10,})", body)
        if m:
            return m.group(1)

        html = await page.content()
        for pat in [r'"projectNumber":\s*"(\d{10,})"']:
            m2 = re.search(pat, html)
            if m2:
                return m2.group(1)
    except Exception:
        pass
    return None


async def try_fill_email(page, email):
    for sel in ["input[type='email']", "input[name='identifier']",
                "input#identifierId"]:
        try:
            inp = page.locator(sel).first
            if await inp.is_visible(timeout=2000):
                await inp.click(timeout=3000)
                await asyncio.sleep(0.3)
                await inp.fill(email, timeout=5000)
                await asyncio.sleep(1)
                for ns in ["button:has-text('Next')", "button[type='submit']"]:
                    try:
                        btn = page.locator(ns).first
                        if await btn.is_visible(timeout=2000):
                            await btn.click(timeout=5000)
                            await asyncio.sleep(3)
                            return True
                    except Exception:
                        pass
        except Exception:
            pass
    return False


async def try_fill_password(page, password):
    for sel in ["input[type='password']", "input[name='Passwd']"]:
        try:
            inp = page.locator(sel).first
            if await inp.is_visible(timeout=3000):
                await inp.click(timeout=3000)
                await asyncio.sleep(0.3)
                await inp.fill(password, timeout=5000)
                await asyncio.sleep(1)
                for ns in ["button:has-text('Next')", "button[type='submit']"]:
                    try:
                        btn = page.locator(ns).first
                        if await btn.is_visible(timeout=2000):
                            await btn.click(timeout=5000)
                            await asyncio.sleep(3)
                            return True
                    except Exception:
                        pass
        except Exception:
            pass
    return False


# ══════════════════════════════════════════════════════
#  ✅ معالجة التحقق (Verify it's you)
# ══════════════════════════════════════════════════════
async def handle_verification(page, bot, chat_id):
    try:
        await asyncio.sleep(3)
        body = await page.locator("body").inner_text(timeout=5000)

        needs_verify = (
            "Verify it's you" in body
            or "Enter a phone number" in body
            or "verification code" in body.lower()
            or "confirm it's you" in body.lower()
        )

        if not needs_verify:
            return True

        await send_screenshot(bot, chat_id, page, "⚠️ Google طلبت التحقق")
        await bot.send_message(
            chat_id,
            "⚠️ *Google طلبت التحقق*\n\n"
            "أرسل:\n"
            "• `/phone +213xxxxxxxxx` — لرقم هاتفك\n"
            "• `/code 123456` — إذا وصلك SMS\n"
            "• `/skip` — لتخطيها\n\n"
            "⏱️ _عندك 5 دقائق_",
            parse_mode="Markdown",
        )

        for _ in range(60):
            await asyncio.sleep(5)
            data = pending_data.get(chat_id, {})

            if data.get("phone"):
                phone = data.pop("phone")
                try:
                    inp = page.locator(
                        "input[type='tel'], input[name='phoneNumber'], input[type='text']"
                    ).first
                    if await inp.is_visible(timeout=3000):
                        await inp.fill(phone)
                        await asyncio.sleep(1)
                        for btn_txt in ["Next", "Continue", "Send"]:
                            try:
                                btn = page.locator(f"button:has-text('{btn_txt}')").first
                                if await btn.is_visible(timeout=2000):
                                    await btn.click()
                                    break
                            except Exception:
                                pass
                        await asyncio.sleep(3)
                        await send_screenshot(bot, chat_id, page, "✅ تم إرسال الرقم")
                except Exception as e:
                    log.error(f"Phone error: {e}")
                break

            if data.get("code"):
                code = data.pop("code")
                try:
                    inp = page.locator(
                        "input[type='tel'], input[name='code'], input[type='text']"
                    ).first
                    if await inp.is_visible(timeout=3000):
                        await inp.fill(code)
                        await asyncio.sleep(1)
                        for btn_txt in ["Next", "Verify", "Continue"]:
                            try:
                                btn = page.locator(f"button:has-text('{btn_txt}')").first
                                if await btn.is_visible(timeout=2000):
                                    await btn.click()
                                    break
                            except Exception:
                                pass
                        await asyncio.sleep(3)
                        await send_screenshot(bot, chat_id, page, "✅ تم إرسال الكود")
                except Exception as e:
                    log.error(f"Code error: {e}")
                break

            if data.get("skip"):
                data.pop("skip")
                await bot.send_message(chat_id, "⏭️ تم التخطي")
                break

        await asyncio.sleep(3)
        body = await page.locator("body").inner_text(timeout=5000)
        if "Verify it's you" in body:
            return False
        return True

    except Exception as e:
        log.error(f"Verification error: {e}")
        return True


# ══════════════════════════════════════════════════════
#  Login
# ══════════════════════════════════════════════════════
async def login_to_lab(page, sso_url, status_cb, bot, chat_id):
    email = extract_email_from_url(sso_url)

    await page.goto(sso_url, timeout=300000, wait_until="domcontentloaded")

    email_asked = False
    pwd_asked_count = 0

    for attempt in range(120):
        try:
            cur = page.url
        except Exception:
            cur = ""

        if "console.cloud.google.com" in cur and "signin" not in cur:
            await send_screenshot(bot, chat_id, page, "✅ تم الدخول")
            try:
                cookies = await page.context.cookies()
                with open(COOKIES_FILE, "w") as f:
                    json.dump(cookies, f)
            except Exception:
                pass
            return {"success": True}

        if "signin/rejected" in cur:
            await asyncio.sleep(3)
            try:
                await page.goto(sso_url, timeout=300000, wait_until="domcontentloaded")
            except Exception:
                pass
            continue

        if "accounts.google.com" in cur and "accountchooser" in cur:
            try:
                acc = page.locator("div[data-identifier], li[data-identifier]").first
                if await acc.is_visible(timeout=2000):
                    await acc.click(timeout=5000)
                    await asyncio.sleep(3)
                    continue
            except Exception:
                pass

        if "accounts.google.com" in cur and ("identifier" in cur or "signin/v2" in cur):
            if not email:
                if not email_asked:
                    email_asked = True
                    bot_data.setdefault(chat_id, {})
                    bot_data[chat_id]["waiting_email"] = True
                    await send_screenshot(bot, chat_id, page, "⚠️ محتاج الإيميل")
                    await status_cb("⚠️ *أرسل الإيميل*")
                    for _ in range(18):
                        await asyncio.sleep(5)
                        if bot_data.get(chat_id, {}).get("manual_email"):
                            email = bot_data[chat_id]["manual_email"]
                            bot_data[chat_id]["manual_email"] = None
                            break
                if not email:
                    continue
            if await try_fill_email(page, email):
                await asyncio.sleep(3)
                continue

        if "accounts.google.com" in cur and ("pwd" in cur or "challenge/pwd" in cur):
            pwd = bot_data.get(chat_id, {}).get("manual_password")
            if pwd:
                bot_data[chat_id]["manual_password"] = None
                if await try_fill_password(page, pwd):
                    pwd_asked_count += 1
                    if pwd_asked_count > 3:
                        await send_screenshot(bot, chat_id, page, "❌ كلمة السر خاطئة")
                        return {"success": False, "error": "كلمة السر خاطئة"}
                    await asyncio.sleep(3)
                    continue

            bot_data.setdefault(chat_id, {})
            bot_data[chat_id]["waiting_password"] = True
            await send_screenshot(bot, chat_id, page, "🔐 أرسل كلمة السر")
            await status_cb("🔐 *أرسل كلمة السر*")
            for _ in range(60):
                await asyncio.sleep(5)
                pwd = bot_data.get(chat_id, {}).get("manual_password")
                if pwd:
                    bot_data[chat_id]["manual_password"] = None
                    if await try_fill_password(page, pwd):
                        pwd_asked_count += 1
                        await asyncio.sleep(3)
                    break
            continue

        for btn_txt in ["I understand", "Agree and continue", "Got it",
                        "Accept", "Continue", "Allow", "Confirm", "Next"]:
            try:
                btn = page.locator(f"button:has-text('{btn_txt}')").first
                if await btn.is_visible(timeout=800):
                    await btn.click(timeout=3000)
                    await asyncio.sleep(1)
            except Exception:
                pass

        await asyncio.sleep(1.5)

    await send_screenshot(bot, chat_id, page, "❌ فشل الدخول")
    return {"success": False, "error": f"فشل الدخول. {page.url[:100]}"}


# ══════════════════════════════════════════════════════
#  extract_url
# ══════════════════════════════════════════════════════
async def extract_url(page):
    pat = re.compile(r"https://[a-z0-9][a-z0-9-]*-\d{6,}\.[a-z0-9-]+\.run\.app")
    try:
        for link in await page.locator("a[href*='run.app']").all():
            href = await link.get_attribute("href")
            if href:
                m = pat.search(href)
                if m:
                    return m.group(0).rstrip("/")
    except Exception:
        pass
    try:
        body = await page.locator("body").inner_text(timeout=6000)
        m = pat.search(body)
        if m:
            return m.group(0).rstrip("/")
    except Exception:
        pass
    try:
        html = await page.content()
        m = pat.search(html)
        if m:
            return m.group(0).rstrip("/")
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════
#  accept_tos
# ══════════════════════════════════════════════════════
async def accept_tos(page, bot, chat_id):
    try:
        clicked_cb = False
        for sel in ["input[type='checkbox']", "mat-checkbox", "div[role='checkbox']"]:
            try:
                cbs = await page.locator(sel).all()
                for cb in cbs:
                    try:
                        is_checked = False
                        try:
                            is_checked = await cb.is_checked(timeout=1000)
                        except Exception:
                            pass
                        if not is_checked:
                            await cb.click(timeout=5000)
                            clicked_cb = True
                            await asyncio.sleep(0.5)
                            break
                    except Exception:
                        try:
                            await cb.click(timeout=5000)
                            clicked_cb = True
                            break
                        except Exception:
                            pass
            except Exception:
                pass
            if clicked_cb:
                break

        await asyncio.sleep(1)
        for sel in ["button:has-text('Agree and continue')",
                    "button:has-text('Agree')",
                    "button:has-text('Accept')"]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    if not await btn.is_disabled():
                        await btn.click(timeout=5000)
                        await asyncio.sleep(3)
                        return True
            except Exception:
                pass
    except Exception:
        pass
    return False


# ══════════════════════════════════════════════════════
#  wait_for_create_page
# ══════════════════════════════════════════════════════
async def wait_for_create_page(page, bot, chat_id, project_id, status_cb, max_wait=240):
    create_url = f"https://console.cloud.google.com/run/create?enableapi=true&project={project_id}"
    start = time.time()
    screenshot_sent = False

    while time.time() - start < max_wait:
        elapsed = int(time.time() - start)

        try:
            await page.goto(create_url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass

        await asyncio.sleep(4)
        await dismiss_dialogs(page)

        try:
            body = await page.locator("body").inner_text(timeout=5000)
            if "Google Cloud Platform Terms of Service" in body or "Welcome student" in body:
                await accept_tos(page, bot, chat_id)
                await asyncio.sleep(3)
                continue
        except Exception:
            pass

        try:
            body = await page.locator("body").inner_text(timeout=5000)
            if "Failed to load" in body or "There was an error" in body:
                try:
                    retry = page.locator("button:has-text('Retry')").first
                    if await retry.is_visible(timeout=2000):
                        await retry.click(timeout=5000)
                        await asyncio.sleep(3)
                except Exception:
                    pass
                if not screenshot_sent and elapsed > 40:
                    await send_screenshot(bot, chat_id, page, f"⏳ API ({elapsed}s)")
                    screenshot_sent = True
                await asyncio.sleep(3)
                continue
        except Exception:
            pass

        try:
            img_ready = False
            for sel in ["input[placeholder*='Container image URL' i]",
                        "input[formcontrolname='image']"]:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=2000):
                        img_ready = True
                        break
                except Exception:
                    pass

            name_ready = False
            for sel in ["input[name='service-name']",
                        "input[formcontrolname='serviceName']"]:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=2000):
                        name_ready = True
                        break
                except Exception:
                    pass

            if img_ready and name_ready:
                await send_screenshot(bot, chat_id, page, "📸 النموذج جاهز")
                return True

        except Exception:
            pass

        if not screenshot_sent and elapsed > 60:
            await send_screenshot(bot, chat_id, page, f"⏳ ({elapsed}s)")
            screenshot_sent = True

        await asyncio.sleep(3)

    await send_screenshot(bot, chat_id, page, f"❌ فشل بعد {max_wait}s")
    return False


# ══════════════════════════════════════════════════════
#  build_vmess_link
# ══════════════════════════════════════════════════════
def build_vmess_link(url):
    import base64
    host = url.replace("https://", "").rstrip("/")
    cfg = {
        "v": "2", "ps": f"GCP-{host.split('.')[0][-12:]}",
        "add": host, "port": "443",
        "id": "27848739-7e62-4138-9fd3-098a63964b6b",
        "aid": "0", "scy": "auto", "net": "ws", "type": "none",
        "host": host, "path": "/", "tls": "tls", "sni": host,
        "alpn": "", "fp": "",
    }
    return f"vmess://{base64.b64encode(json.dumps(cfg, separators=(',', ':')).encode()).decode()}"


# ══════════════════════════════════════════════════════
#  🚀 النشر
# ══════════════════════════════════════════════════════
async def deploy_service(sso_url, preferred_region, status_cb, bot, chat_id):
    project_id = extract_project_id(sso_url)
    if not project_id:
        return {"success": False, "url": "", "region": "", "error": "ما لقيتش Project ID"}

    result_url = ""
    result_region = preferred_region
    project_number = None

    async with async_playwright() as pw:
        browser = None
        context = None

        # ✅ إذا حبيت Chrome Profile (يتخطى التحقق)
        if USE_CHROME_PROFILE:
            try:
                context = await pw.chromium.launch_persistent_context(
                    user_data_dir=CHROME_USER_DATA,
                    channel='chrome',
                    headless=True,
                    args=[
                        "--no-sandbox", "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage", "--disable-gpu",
                        "--window-size=1366,768",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-infobars",
                        "--disable-features=IsolateOrigins,site-per-process",
                    ],
                    viewport={"width": 1366, "height": 768},
                    locale="en-US",
                    timezone_id="Africa/Algiers",
                )
                log.warning("✅ Using Chrome Profile")
            except Exception as e:
                log.warning(f"Chrome Profile failed: {e}, falling back")
                context = None

        # ✅ إذا فشل Profile، نستعمل Chromium عادي
        if context is None:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox", "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage", "--disable-gpu",
                    "--window-size=1366,768",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1366, "height": 768},
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/131.0.0.0 Safari/537.36"),
                locale="en-US",
                timezone_id="Africa/Algiers",
                java_script_enabled=True,
            )

        if COOKIES_FILE.exists():
            try:
                with open(COOKIES_FILE) as f:
                    cookies = json.load(f)
                await context.add_cookies(cookies)
            except Exception:
                pass

        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined, configurable: true,
            });
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            window.chrome = {runtime: {id: 'random-id'}, loadTimes: function(){}, csi: function(){}};
            const origQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (p) =>
                p.name === 'notifications'
                    ? Promise.resolve({state: Notification.permission})
                    : origQuery(p);
        """)

        page = await context.new_page()

        try:
            await status_cb("⏳ جاري الدخول إلى اللاب...")
            login_result = await login_to_lab(page, sso_url, status_cb, bot, chat_id)
            if not login_result["success"]:
                await context.close()
                return {"success": False, "url": "", "region": result_region,
                        "error": login_result["error"]}

            await status_cb("✅ تم الدخول!")

            # ✅ معالجة التحقق
            await status_cb("🔐 فحص التحقق...")
            await handle_verification(page, bot, chat_id)

            project_number = await get_project_number(page, project_id)

            await status_cb("⏳ تحميل صفحة Create Service...")

            form_ready = await wait_for_create_page(
                page, bot, chat_id, project_id, status_cb, max_wait=240
            )

            if not form_ready:
                await page.goto(
                    f"https://console.cloud.google.com/run/create?enableapi=true&project={project_id}",
                    wait_until="domcontentloaded", timeout=60000,
                )
                await asyncio.sleep(15)
                await dismiss_dialogs(page)

            await status_cb("📝 جاري ملء النموذج...")
            await asyncio.sleep(2)

            for sel in [
                "label:has-text('Deploy one revision from an existing container image')",
                "mat-radio-button:has-text('existing container image')",
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=3000):
                        await el.click(timeout=5000)
                        await asyncio.sleep(2)
                        break
                except Exception:
                    pass

            await asyncio.sleep(3)
            img_ok = await write_angular_input(
                page, DOCKER_IMAGE,
                selectors=[
                    "input[placeholder*='Container image URL' i]",
                    "input[aria-label*='Container image URL' i]",
                    "input[formcontrolname='image']",
                    "input[placeholder*='gcr.io' i]",
                ],
                field_name="Image URL"
            )
            await asyncio.sleep(3)
            await send_screenshot(bot, chat_id, page,
                f"📸 Image {'✅' if img_ok else '❌'}")

            name_ok = await write_angular_input(
                page, SERVICE_NAME,
                selectors=[
                    "input[name='service-name']",
                    "input[formcontrolname='serviceName']",
                    "input[aria-label*='Service name' i]",
                    "input[placeholder*='service name' i]",
                ],
                field_name="Service name"
            )
            await asyncio.sleep(3)
            await send_screenshot(bot, chat_id, page,
                f"📸 Name {'✅' if name_ok else '❌'}")

            for sel in ["mat-select[formcontrolname='region']",
                        "mat-select[aria-label*='Region' i]"]:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=3000):
                        await el.click(timeout=5000)
                        await asyncio.sleep(2)
                        opt = page.locator(f"mat-option:has-text('{preferred_region}')").first
                        if await opt.is_visible(timeout=2000):
                            await opt.click(timeout=5000)
                            result_region = preferred_region
                        else:
                            opts = await page.locator("mat-option:not([aria-disabled='true'])").all()
                            if opts:
                                txt = await opts[0].inner_text()
                                await opts[0].click(timeout=5000)
                                m = re.search(r"([a-z]+-[a-z]+\d+)", txt)
                                if m:
                                    result_region = m.group(1)
                        break
                except Exception:
                    pass

            await asyncio.sleep(2)

            try:
                body = await page.locator("body").inner_text(timeout=5000)
                m = re.search(r"https://[a-z0-9-]+-\d+\.[a-z0-9-]+\.run\.app", body)
                if m:
                    result_url = m.group(0).rstrip("/")
            except Exception:
                pass

            for sel in [
                "mat-radio-button:has-text('Allow unauthenticated')",
                "mat-radio-button:has-text('Allow public access')",
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=3000):
                        await el.click(timeout=5000)
                        break
                except Exception:
                    pass
            await asyncio.sleep(1)

            try:
                el = page.locator("mat-radio-button:has-text('Instance-based')").first
                if await el.is_visible(timeout=3000):
                    await el.click(timeout=5000)
            except Exception:
                pass
            await asyncio.sleep(1)

            await status_cb("🔍 نتأكد من الحقول...")
            fields_ok = await wait_fields_filled(page, bot, chat_id, status_cb)

            if not fields_ok:
                await send_screenshot(bot, chat_id, page, "⚠️ نحاول مرة أخرى")

                await write_angular_input(
                    page, DOCKER_IMAGE,
                    selectors=[
                        "input[placeholder*='Container image URL' i]",
                        "input[formcontrolname='image']",
                    ],
                    field_name="Image retry"
                )
                await asyncio.sleep(2)
                await write_angular_input(
                    page, SERVICE_NAME,
                    selectors=[
                        "input[name='service-name']",
                        "input[formcontrolname='serviceName']",
                    ],
                    field_name="Name retry"
                )
                await asyncio.sleep(3)
                fields_ok = await wait_fields_filled(page, bot, chat_id, status_cb)

            await send_screenshot(bot, chat_id, page,
                f"📸 قبل Create ({'✅' if fields_ok else '⚠️'})")

            await status_cb("🚀 Create...")

            created = False
            for try_create in range(5):
                for sel in [
                    "button:has-text('Create'):not([disabled])",
                    "button[type='submit']:has-text('Create')",
                ]:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible(timeout=5000) and not await btn.is_disabled():
                            await btn.click(timeout=10000)
                            created = True
                            break
                    except Exception:
                        pass
                if created:
                    break

                if not created:
                    try:
                        for btn in await page.locator("button").all():
                            txt = (await btn.inner_text()).strip().lower()
                            if txt == "create" and not await btn.is_disabled():
                                await btn.click(timeout=10000)
                                created = True
                                break
                    except Exception:
                        pass

                if created:
                    break

                await asyncio.sleep(5)

            if not created:
                await send_screenshot(bot, chat_id, page, "❌ Create")
                await context.close()
                return {"success": False, "url": result_url, "region": result_region,
                        "error": "لم أتمكن من الضغط على Create."}

            await status_cb("⏳ انتظار إنشاء الخدمة...")

            for _ in range(20):
                await asyncio.sleep(5)
                extracted = await extract_url(page)
                if extracted:
                    result_url = extracted
                    await send_screenshot(bot, chat_id, page, "📸 لقينا الرابط")
                    break

            if not result_url and project_number:
                result_url = f"https://{SERVICE_NAME}-{project_number}.{result_region}.run.app"

            await context.close()

            if result_url:
                return {"success": True, "url": result_url, "region": result_region, "error": ""}

            return {"success": False, "url": "", "region": result_region,
                    "error": "ما لقيناش الرابط."}

        except Exception as e:
            log.exception("Deploy error")
            try:
                await send_screenshot(bot, chat_id, page, f"❌ {str(e)[:150]}")
            except Exception:
                pass
            try:
                await context.close()
            except Exception:
                pass
            if result_url:
                return {"success": True, "url": result_url, "region": result_region, "error": ""}
            return {"success": False, "url": "", "region": result_region, "error": str(e)}


# ══════════════════════════════════════════════════════
#  Telegram handlers
# ══════════════════════════════════════════════════════
async def cmd_start(update, ctx):
    name = update.effective_user.first_name or "مستخدم"
    await update.message.reply_text(
        f"👋 مرحباً {name}!\n\n"
        "🔗 أرسل رابط Google Cloud Console أو Cloud Shell.\n\n"
        "📸 *اختبار:* /test\n"
        "📊 *الحالة:* /status",
        parse_mode="Markdown",
    )


async def cmd_status(update, ctx):
    has_cookies = COOKIES_FILE.exists()
    chrome_ok = os.path.exists(CHROME_USER_DATA) if USE_CHROME_PROFILE else False
    await update.message.reply_text(
        f"📊 *حالة البوت:*\n\n"
        f"🍪 Cookies: {'✅ محفوظة' if has_cookies else '❌ ما كانش'}\n"
        f"🌐 Chrome Profile: {'✅ مفعل' if USE_CHROME_PROFILE else '❌ غير مفعل'}\n"
        f"🤖 البوت: ✅ خدام",
        parse_mode="Markdown",
    )


async def cmd_test(update, ctx):
    msg = await update.message.reply_text("📸 جاري اختبار Chromium...")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36"),
        )
        page = await context.new_page()
        try:
            await msg.edit_text("📸 فتح Google...")
            await page.goto("https://www.google.com", timeout=30000)
            await asyncio.sleep(2)
            await send_screenshot(ctx.bot, update.effective_chat.id, page,
                "✅ Google خدام")

            await msg.edit_text("📸 فتح Skills...")
            await page.goto("https://www.skills.google", timeout=30000)
            await asyncio.sleep(3)
            await send_screenshot(ctx.bot, update.effective_chat.id, page,
                "✅ Skills خدام" if "skills.google" in page.url
                else f"⚠️ URL: {page.url[:60]}")

            await msg.edit_text("✅ *الاختبار تم!*", parse_mode="Markdown")
        except Exception as e:
            await msg.edit_text(f"❌ خطأ: {str(e)[:300]}")
        finally:
            await browser.close()


async def cmd_clearcookies(update, ctx):
    try:
        if COOKIES_FILE.exists():
            COOKIES_FILE.unlink()
        await update.message.reply_text("✅ تم مسح الـ cookies")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


async def cmd_phone(update, ctx):
    text = update.message.text or ""
    m = re.match(r"^/phone\s+(.+)$", text)
    if m:
        phone = m.group(1).strip()
        chat_id = update.effective_chat.id
        pending_data.setdefault(chat_id, {})["phone"] = phone
        await update.message.reply_text(f"✅ تم استلام الرقم: `{phone}`", parse_mode="Markdown")


async def cmd_code(update, ctx):
    text = update.message.text or ""
    m = re.match(r"^/code\s+(.+)$", text)
    if m:
        code = m.group(1).strip()
        chat_id = update.effective_chat.id
        pending_data.setdefault(chat_id, {})["code"] = code
        await update.message.reply_text(f"✅ تم استلام الكود: `{code}`", parse_mode="Markdown")


async def cmd_skip(update, ctx):
    chat_id = update.effective_chat.id
    pending_data.setdefault(chat_id, {})["skip"] = True
    await update.message.reply_text("⏭️ تم التخطي")


async def handle_message(update, ctx):
    text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id

    if not text:
        return

    if bot_data.get(chat_id, {}).get("waiting_email"):
        bot_data[chat_id]["manual_email"] = text
        bot_data[chat_id]["waiting_email"] = False
        await update.message.reply_text(f"✅ الإيميل: `{text}`", parse_mode="Markdown")
        return

    if bot_data.get(chat_id, {}).get("waiting_password"):
        bot_data[chat_id]["manual_password"] = text
        bot_data[chat_id]["waiting_password"] = False
        await update.message.reply_text("✅ تم استلام كلمة السر")
        return

    if not is_sso_url(text):
        await update.message.reply_text("❓ أرسل رابط صالح.")
        return

    ctx.user_data["sso_url"] = text
    ctx.user_data.pop("region", None)

    email = extract_email_from_url(text)
    pid = extract_project_id(text)
    display = ""
    if pid:
        display += f"\n📁 `{pid}`"
    if email:
        display += f"\n📧 `{email}`"

    await update.message.reply_text(
        f"🌐 اختر المنطقة:{display}",
        reply_markup=region_keyboard(),
        parse_mode="Markdown",
    )


async def handle_region(update, ctx):
    q = update.callback_query
    await q.answer()
    _, region = q.data.split(":", 1)

    if region == "cancel":
        ctx.user_data.clear()
        await q.edit_message_text("❌ إلغاء.")
        return

    ctx.user_data["region"] = region
    sso_url = ctx.user_data.get("sso_url", "")
    rd = region if region not in ("auto", "random") else f"تلقائي ({region})"

    await q.edit_message_text(
        f"🚀 تأكيد:\n🌐 `{sso_url[:80]}...`\n📍 **{rd}**",
        reply_markup=confirm_keyboard(),
        parse_mode="Markdown",
    )


async def handle_confirm(update, ctx):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "confirm:no":
        ctx.user_data.clear()
        await q.edit_message_text("❌ إلغاء.")
        return

    sso_url = ctx.user_data.get("sso_url", "")
    region = ctx.user_data.get("region", "auto")

    if not sso_url:
        await q.edit_message_text("❌ ما لقيتش الرابط.")
        return

    status_msg = await q.edit_message_text("⏳ جاري الدخول...")

    async def status_cb(text):
        try:
            await status_msg.edit_text(text, parse_mode="Markdown")
        except Exception:
            pass

    bot_data.setdefault(update.effective_chat.id, {})

    result = await deploy_service(sso_url, region, status_cb,
                                  ctx.bot, update.effective_chat.id)

    if result["success"] and result["url"]:
        url = result["url"]
        reg = result["region"]
        vmess = build_vmess_link(url)
        await status_msg.edit_text(
            "🎉 **تم النشر!**\n\n"
            f"🚀 `{url}`\n\n"
            f"📍 `{reg}`\n\n"
            f"🔗 *V2Ray:*\n`{vmess}`",
            parse_mode="Markdown",
        )
    else:
        err = result.get("error", "خطأ")
        partial = result.get("url", "")
        msg = f"❌ **فشل**\n\n{err}"
        if partial:
            msg += f"\n\n🔗 المتوقع: `{partial}`"
        await status_msg.edit_text(msg, parse_mode="Markdown")

    ctx.user_data.clear()


# ══════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════
def main():
    log.warning("=" * 60)
    log.warning("Bot starting...")
    log.warning(f"Log: {LOG_FILE}")
    log.warning("=" * 60)

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("clearcookies", cmd_clearcookies))
    app.add_handler(CommandHandler("phone", cmd_phone))
    app.add_handler(CommandHandler("code", cmd_code))
    app.add_handler(CommandHandler("skip", cmd_skip))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_region, pattern=r"^region:"))
    app.add_handler(CallbackQueryHandler(handle_confirm, pattern=r"^confirm:"))

    log.warning("Bot started successfully.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
