#!/usr/bin/env python3
"""
aabot — login stealth contra https://adm.autoavaliar.com.br/

Alvo embutido. Rodar sem argumentos = login no site oficial.
`fetch <url>` para qualquer outro site, com escalonamento http -> browser.

Saida: texto por padrao, JSON com --json.
Codigos: 0 ok, 1 erro inesperado, 10 bloqueado, 11 auth falhou,
12 dependencia ausente, 13 config, 14 timeout.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

BASE = "https://adm.autoavaliar.com.br"
LOGIN_URL = BASE + "/loginsession.php"

EXIT = {"ok": 0, "error": 1, "blocked": 10, "auth_failed": 11,
        "dep_missing": 12, "config": 13, "timeout": 14}

VENDORS = {
    "cloudflare": [r"cf-chl", r"_cf_chl_opt", r"just a moment", r"cf-mitigated",
                   r"challenge-platform"],
    "datadome": [r"captcha-delivery\.com", r"datadome", r"dd_cookie_test"],
    "akamai": [r"reference #\d+\.", r"_abck", r"akam/13"],
    "perimeterx": [r"_pxcaptcha", r"px-captcha", r"perimeterx", r"_px3"],
    "imperva": [r"_incapsula_resource", r"incapsula", r"visid_incap"],
    "kasada": [r"kpsdk", r"x-kpsdk"],
    "captcha": [r"g-recaptcha", r"h-captcha", r"cf-turnstile", r"data-sitekey"],
}
INTERACTIVE = {"datadome", "perimeterx", "captcha", "cloudflare"}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
GEO = {
    "BR": ("pt-BR", "pt-BR,pt;q=0.9,en;q=0.8", "America/Sao_Paulo", 180),
    "US": ("en-US", "en-US,en;q=0.9", "America/New_York", 240),
    "DE": ("de-DE", "de-DE,de;q=0.9,en;q=0.8", "Europe/Berlin", -60),
}

# shim do alvo, embutido
SHIM = {
    "login_marker": "login-form",
    "auth_markers": ["sair", "logout", "logoff", "encerrar sessao"],
    "block_markers": ["automação", "automacao", "bloquead", "acesso negado"],
    "fp_cookies": ["fingerprint", "fingerprint_detalhes"],
}


def classify(text: str) -> list[str]:
    if not text:
        return []
    low = text.lower()
    return [v for v, pats in VENDORS.items()
            if any(re.search(p, low) for p in pats)]


def fnv1a(s: str) -> str:
    h = 0x811C9DC5
    for ch in s:
        h = ((h ^ ord(ch)) * 0x01000193) & 0xFFFFFFFF
    return format(h, "x")


@dataclass
class Profile:
    country: str = "BR"
    seed: int = field(default_factory=lambda: random.randrange(1 << 31))
    proxy: str | None = None
    headed: bool = False

    def __post_init__(self):
        lang, accept, tz, off = GEO.get(self.country.upper(), GEO["BR"])
        self.ua, self.lang, self.accept_lang = UA, lang, accept
        self.tz, self.tz_offset = tz, off
        rnd = random.Random(self.seed)
        self.screen = rnd.choice([(1920, 1080), (1536, 864), (2560, 1440)])
        self.cores = rnd.choice([8, 12, 16])
        self.platform, self.depth = "Win32", 24

    def fp(self) -> str:
        return fnv1a("|".join([self.ua, self.lang, self.platform, str(self.cores),
                               f"{self.screen[0]}x{self.screen[1]}", str(self.depth),
                               str(self.tz_offset), str(self.seed)]))

    def fp_details(self) -> str:
        return json.dumps({
            "language": self.lang, "platform": self.platform,
            "hardwareConcurrency": self.cores,
            "screenWidth": self.screen[0], "screenHeight": self.screen[1],
            "colorDepth": self.depth, "timezoneOffset": self.tz_offset,
            "canvasHash": fnv1a(f"autoavaliar-fp|{self.seed}"),
        })

    def headers(self, referer: str | None = None) -> dict:
        h = {
            "User-Agent": self.ua, "Accept-Language": self.accept_lang,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Upgrade-Insecure-Requests": "1",
            "Sec-CH-UA": '"Chromium";v="141", "Google Chrome";v="141", "Not?A_Brand";v="24"',
            "Sec-CH-UA-Platform": '"Windows"', "Sec-CH-UA-Mobile": "?0",
            "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin" if referer else "none",
            "Sec-Fetch-User": "?1",
        }
        if referer:
            p = urlparse(referer)
            h["Referer"] = referer
            h["Origin"] = f"{p.scheme}://{p.netloc}"
        return h


def result(ok, *, engine, url, status=0, html="", final_url="", vendors=None,
           authenticated=None, notes=None, cookies=None, elapsed_ms=0) -> dict:
    return {"ok": ok, "engine": engine, "url": url, "final_url": final_url or url,
            "status": status, "vendors": vendors or [],
            "needs_interactive": bool(set(vendors or []) & INTERACTIVE),
            "authenticated": authenticated, "notes": notes or [],
            "cookies": cookies or {}, "elapsed_ms": elapsed_ms,
            "html_bytes": len(html or ""), "html_head": (html or "")[:4000]}


def emit(p: dict, as_json: bool, code: int) -> int:
    if as_json:
        print(json.dumps(p, indent=2, ensure_ascii=False))
    else:
        print(f"[{'OK' if p.get('ok') else 'FALHA'}] {p.get('engine')} "
              f"status={p.get('status')} {p.get('final_url')}")
        if p.get("vendors"):
            print("  anti-bot: " + ", ".join(p["vendors"]))
        for n in p.get("notes", []):
            print("  " + n)
    return code


class Jar:
    def __init__(self, path: str | None = None):
        self.path = Path(path) if path else None
        self.data: dict[str, str] = {}
        if self.path and self.path.exists():
            self.data = json.loads(self.path.read_text())

    def save(self):
        if self.path:
            self.path.write_text(json.dumps(self.data, indent=2))

    def apply(self, session, host: str):
        for k, v in self.data.items():
            session.cookies.set(k, v, domain=host, path="/")

    def absorb(self, cookies):
        try:
            for c in cookies.jar:
                self.data[c.name] = c.value
        except Exception:
            pass


def http_call(url, profile: Profile, jar: Jar, *, method="GET", data=None,
              referer=None, timeout=30):
    from curl_cffi import requests as creq
    host = urlparse(url).netloc
    s = creq.Session(impersonate="chrome", timeout=timeout)
    s.headers.update(profile.headers(referer))
    jar.apply(s, host)
    if profile.proxy:
        s.proxies = {"http": profile.proxy, "https": profile.proxy}
    try:
        r = s.request(method, url, data=data, allow_redirects=True)
        jar.absorb(s.cookies)
        jar.save()
        return r.status_code, r.text, str(r.url), dict(r.headers)
    finally:
        s.close()


async def _wait_clear(html_fn, timeout):
    deadline = time.monotonic() + timeout
    html = ""
    while time.monotonic() < deadline:
        html = await html_fn()
        if not classify(html):
            return html, True
        await asyncio.sleep(1.5)
    return html, False


def _args(p: Profile) -> list[str]:
    a = ["--lang=" + p.lang, f"--window-size={p.screen[0]},{p.screen[1]}",
         "--disable-blink-features=AutomationControlled",
         "--no-first-run", "--no-default-browser-check"]
    if p.proxy:
        a.append(f"--proxy-server={p.proxy}")
    return a


async def browser_visit(url, profile, engine, timeout, cookies, act=None):
    t0 = time.monotonic()
    if engine == "pydoll":
        from pydoll.browser import Chrome
        from pydoll.browser.options import ChromiumOptions
        opts = ChromiumOptions()
        opts.headless = not profile.headed
        for a in _args(profile):
            opts.add_argument(a)
        async with Chrome(options=opts) as b:
            page = await b.new_page()
            await page.go_to(url)
            try:
                await page.mouse.move(180, 260)
            except Exception:
                pass
            html, cleared = await _wait_clear(lambda: page.page_source, timeout)
            if act:
                await act(page, "pydoll")
            final = page.url
            try:
                got = {c.name: c.value for c in await page.get_cookies()}
            except Exception:
                got = {}
    else:
        from patchright.async_api import async_playwright
        async with async_playwright() as p:
            br = await p.chromium.launch(channel="chrome",
                                         headless=not profile.headed,
                                         args=_args(profile))
            ctx = await br.new_context(
                user_agent=profile.ua, locale=profile.lang, timezone_id=profile.tz,
                viewport={"width": profile.screen[0], "height": profile.screen[1]},
                screen={"width": profile.screen[0], "height": profile.screen[1]})
            if cookies:
                await ctx.add_cookies([{"name": k, "value": v,
                                        "domain": urlparse(url).netloc, "path": "/"}
                                       for k, v in cookies.items()])
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded",
                            timeout=timeout * 1000)
            await page.mouse.move(180, 260)
            html, cleared = await _wait_clear(lambda: page.content(), timeout)
            if act:
                await act(page, "patchright")
            final = page.url
            got = {c["name"]: c["value"] for c in await ctx.cookies()}
            await br.close()
    return html, final, got, cleared, int((time.monotonic() - t0) * 1000)


def _auth_ok(html: str, final_url: str) -> bool:
    low = (html or "").lower()
    if SHIM["login_marker"] in low:
        return False
    if any(m in low for m in SHIM["auth_markers"]):
        return True
    return "login" not in urlparse(final_url).path.lower()


def _blocked_note(html: str) -> list[str]:
    return [f"mensagem do site: '{m}'"
            for m in SHIM["block_markers"] if m in (html or "").lower()]


# --------------------------------------------------------------- login alvo

def cmd_login(a) -> int:
    user = a.user or os.getenv("AABOT_USER") or os.getenv("USER")
    pw = a.password or os.getenv("AABOT_PASS") or os.getenv("PASSWORD")
    if not user:
        user = input("usuario: ").strip()
    if not pw:
        import getpass
        pw = getpass.getpass("senha: ")
    if not (user and pw):
        return emit({"ok": False, "notes": ["credenciais ausentes"]}, a.json,
                    EXIT["config"])

    profile = Profile(a.country, proxy=a.proxy, headed=a.headed)
    jar = Jar(a.session)
    t0 = time.monotonic()

    jar.data["fingerprint"] = profile.fp()
    jar.data["fingerprint_detalhes"] = profile.fp_details()

    payload = base64.b64encode(
        json.dumps({"s": [], "i": 1}, separators=(",", ":")).encode()).decode()
    fields = {"usuario": user, "senha": pw, "login": "login", "__aa_auto": payload}

    try:
        http_call(BASE + "/", profile, jar, referer=BASE + "/", timeout=a.timeout)
        status, html, final, _ = http_call(LOGIN_URL, profile, jar, method="POST",
                                           data=fields, referer=BASE + "/",
                                           timeout=a.timeout)
    except Exception as e:
        status, html, final = 0, "", LOGIN_URL
        print(f"aviso: camada HTTP falhou: {e}", file=sys.stderr)

    if status and _auth_ok(html, final):
        return emit(result(True, engine="http", url=LOGIN_URL, status=status,
                           html=html, final_url=final, authenticated=True,
                           cookies=jar.data,
                           elapsed_ms=int((time.monotonic() - t0) * 1000)),
                    a.json, EXIT["ok"])

    if a.no_escalate:
        return emit(result(False, engine="http", url=LOGIN_URL, status=status,
                           html=html, final_url=final, authenticated=False,
                           vendors=classify(html), notes=_blocked_note(html)
                           + ["login HTTP nao autenticou"]),
                    a.json, EXIT["auth_failed"])

    async def act(page, kind):
        for name in ("usuario", "senha"):
            sel = f"[name='{name}']"
            if kind == "patchright":
                if await page.locator(sel).count():
                    await page.locator(sel).click()
                    await page.locator(sel).type(
                        user if name == "usuario" else pw, delay=90)
            else:
                try:
                    el = await page.find(name=name, timeout=8)
                    await el.click(humanize=True)
                    await el.type_text(user if name == "usuario" else pw,
                                       humanize=True)
                except Exception:
                    pass
        await asyncio.sleep(0.4)
        if kind == "patchright":
            await page.locator("button[type='submit']").first.click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(2500)
        else:
            await page.find(tag_name="button", timeout=8).then(
                lambda b: b.click(humanize=True))
            await asyncio.sleep(3)

    for eng in ("patchright", "pydoll"):
        try:
            html, final, got, cleared, ms = asyncio.run(
                browser_visit(BASE + "/", profile, eng, a.timeout, jar.data, act))
        except ImportError as e:
            print(f"aviso: {eng} ausente: {e}", file=sys.stderr)
            continue
        jar.data.update(got)
        jar.save()
        ok = _auth_ok(html, final)
        out = result(ok, engine=eng, url=LOGIN_URL, status=200, html=html,
                     final_url=final, authenticated=ok, cookies=jar.data,
                     vendors=classify(html), notes=_blocked_note(html),
                     elapsed_ms=ms)
        if not cleared:
            out["notes"].append("challenge nao resolvido; tente --headed")
        if ok:
            return emit(out, a.json, EXIT["ok"])
    return emit(result(False, engine="none", url=LOGIN_URL, authenticated=False,
                       notes=["todas as camadas falharam"]), a.json,
                EXIT["auth_failed"])


# --------------------------------------------------------------- fetch livre

def _dump(a, html):
    if getattr(a, "out", None) and html:
        Path(a.out).write_text(html, encoding="utf-8")
        return [f"html completo salvo em {a.out}"]
    return []


def cmd_fetch(a) -> int:
    profile = Profile(a.country, proxy=a.proxy, headed=a.headed)
    jar = Jar(a.session)
    t0 = time.monotonic()
    if a.engine in ("auto", "http"):
        try:
            status, html, final, hd = http_call(a.url, profile, jar,
                                                referer=a.referer,
                                                timeout=a.timeout)
        except Exception as e:
            status, html, final, hd = 0, "", a.url, {}
        vendors = classify(html) + (["cloudflare"] if hd.get("cf-mitigated") else [])
        if status and status < 400 and not vendors:
            return emit(result(True, engine="http", url=a.url, status=status,
                               html=html, final_url=final, cookies=jar.data,
                               notes=_dump(a, html),
                               elapsed_ms=int((time.monotonic() - t0) * 1000)),
                        a.json, EXIT["ok"])
        if a.engine == "http":
            return emit(result(False, engine="http", url=a.url, status=status,
                               html=html, final_url=final, vendors=vendors),
                        a.json, EXIT["blocked"])
    for eng in (["patchright", "pydoll"] if a.engine == "auto" else [a.engine]):
        try:
            html, final, got, cleared, ms = asyncio.run(
                browser_visit(a.url, profile, eng, a.timeout, jar.data))
        except ImportError:
            continue
        jar.data.update(got)
        jar.save()
        vendors = classify(html)
        out = result(not vendors, engine=eng, url=a.url, status=200, html=html,
                     final_url=final, vendors=vendors, cookies=jar.data,
                     notes=[] if cleared else ["challenge nao resolvido"],
                     elapsed_ms=ms)
        out["notes"] += _dump(a, html)
        if not vendors:
            return emit(out, a.json, EXIT["ok"])
        if not out["needs_interactive"]:
            return emit(out, a.json, EXIT["blocked"])
    return emit(result(False, engine="none", url=a.url), a.json, EXIT["blocked"])


def cmd_selfcheck(a) -> int:
    checks = {}
    for mod in ("curl_cffi", "pydoll", "patchright"):
        try:
            __import__(mod)
            checks[mod] = "ok"
        except ImportError:
            checks[mod] = "AUSENTE"
    chrome = any(p and Path(p).exists() for p in (
        "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")))
    checks["chrome_sistema"] = "ok" if chrome else "AUSENTE"
    checks["alvo"] = BASE
    bad = [k for k, v in checks.items() if v == "AUSENTE"]
    return emit({"ok": not bad, "checks": checks}, a.json,
                EXIT["ok"] if not bad else EXIT["dep_missing"])


def _load_env():
    # .env autoritativo (cwd, depois dir do script); sem python-dotenv
    for base in (Path.cwd(), Path(__file__).resolve().parent):
        f = base / ".env"
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ[k.strip()] = v.strip().strip('"').strip("'")
        return


def main() -> int:
    _load_env()
    ap = argparse.ArgumentParser(prog="aabot")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--country", default="BR")
    ap.add_argument("--proxy")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--session", default=".aabot-cookies.json")
    ap.add_argument("--timeout", type=int, default=45)
    sub = ap.add_subparsers(dest="cmd")

    l = sub.add_parser("login")
    l.add_argument("--user")
    l.add_argument("--password")
    l.add_argument("--no-escalate", action="store_true")
    l.set_defaults(fn=cmd_login)

    f = sub.add_parser("fetch")
    f.add_argument("url")
    f.add_argument("--engine", default="auto",
                   choices=["auto", "http", "pydoll", "patchright"])
    f.add_argument("--referer")
    f.add_argument("--out", help="salva o HTML completo neste arquivo")
    f.set_defaults(fn=cmd_fetch)

    sub.add_parser("selfcheck").set_defaults(fn=cmd_selfcheck)

    a = ap.parse_args()
    if not a.cmd:
        a.cmd, a.user, a.password, a.no_escalate = "login", None, None, False
        a.fn = cmd_login
    try:
        return a.fn(a)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        return emit({"ok": False, "engine": a.cmd, "notes": ["interrompido"]},
                    a.json, EXIT["error"])
    except Exception as e:
        # contrato: --json sempre parseavel, mesmo em falha nao prevista
        # (Chrome nao sobe, --session corrompido, stdin fechado em prompt...)
        return emit({"ok": False, "engine": a.cmd,
                     "notes": [f"erro inesperado: {type(e).__name__}: {e}"]},
                    a.json, EXIT["error"])


if __name__ == "__main__":
    sys.exit(main())