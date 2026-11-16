"""Current HTML response evidence; no fetching, browser handoff or client state."""
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit


class _AccessHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.title = self.h1 = self.h2 = ''
        self.content = self.body_text = self.verification_prompt = False
        self.password = self.frame = self.captcha = False
        self.options = self.orchestrator = self.anubis = False

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        inert = any(item[0] in {'template', 'noscript'} for item in self.stack)
        hidden = (inert or any(item[1] for item in self.stack) or 'hidden' in attrs
            or attrs.get('aria-hidden', '').lower() == 'true'
            or bool(re.search(r'(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse)|opacity\s*:\s*0(?:[;\s]|$))', attrs.get('style', ''), re.I)))
        if tag == 'script' and not inert:
            self.orchestrator |= bool(re.search(r'/cdn-cgi/challenge-platform/[^\s"\'<>]*orchestrate/chl_page/', attrs.get('src', '')))
            self.anubis |= attrs.get('id') == 'anubis_challenge' and attrs.get('type') == 'application/json'
        if tag == 'iframe' and not hidden:
            self.frame = True
            url = urlsplit(attrs.get('src', ''))
            self.captcha |= (bool(re.search(r'(^|\.)(hcaptcha\.com|recaptcha\.net|google\.com)$', url.hostname or ''))
                and 'captcha' in url.path)
        if tag == 'input' and not hidden and attrs.get('type', '').lower() == 'password':
            self.password = True
        if tag not in {'input', 'meta', 'link', 'img', 'br', 'hr', 'embed', 'source', 'base', 'area', 'wbr', 'param', 'col'}:
            self.stack.append((tag, hidden))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        tags = [tag for tag, _ in self.stack]
        if any(tag in tags for tag in ('template', 'noscript')):
            return
        if 'script' in tags:
            self.options |= bool(re.search(r'\b_cf_chl_opt\s*=\s*\{', data))
            return
        if 'title' in tags:
            self.title += data
        if any(hidden for _, hidden in self.stack) or any(tag in tags for tag in ('style', 'head', 'title', 'iframe')):
            return
        if 'h1' in tags:
            self.h1 += data
        elif 'h2' in tags:
            self.h2 += data
        if data.strip():
            self.verification_prompt |= bool(re.match(r'^(?:please\s+)?(?:complete (?:the )?(?:security check|captcha)|verify (?:that )?you are human)\b', data.strip(), re.I))
            self.body_text = True
            if 'article' in tags or 'main' in tags:
                self.content = True


def html_access(body: str, status: int = 200) -> str | None:
    """Conservative fallback when no authoritative response header is available."""
    parser = _AccessHTML()
    try:
        parser.feed(body)
    except (ValueError, RecursionError):
        return None
    titles = (parser.title.strip(), (parser.h1 or parser.h2).strip())
    named = lambda pattern: any(re.match(pattern, value, re.I) for value in titles)
    cloudflare_title = named(r'^(Just a moment|Attention Required)(?:[.!…\s]|$)')
    if (cloudflare_title and (status >= 400 or parser.options or parser.orchestrator)
            or parser.options and parser.orchestrator and not parser.content):
        return 'cloudflare'
    if parser.anubis and named(r'^Making sure you.re not a bot'):
        return 'anubis'
    verification = named(r'^(Verify you are human|Are you a robot|Human verification|Security check|Checking your browser)')
    if (parser.frame and verification or parser.captcha
            and (not parser.body_text or parser.verification_prompt and not parser.content)):
        return 'verification'
    if parser.password and named(r'^(Sign in|Log in|Login|Authentication)\b'):
        return 'login'
    return None
