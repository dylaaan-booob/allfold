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
        self.password = self.modal_password = self.frame = self.captcha = False
        self.options = self.orchestrator = self.anubis = False

    def handle_starttag(self, tag, attributes):
        attrs = {name: value or '' for name, value in attributes}
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
        modal = attrs.get('aria-modal') == 'true' or tag == 'dialog' and 'open' in attrs or any(item[2] for item in self.stack)
        if tag == 'input' and not hidden and attrs.get('type', '').lower() == 'password':
            self.password = True
            self.modal_password |= modal
        if tag not in {'input', 'meta', 'link', 'img', 'br', 'hr', 'embed', 'source', 'base', 'area', 'wbr', 'param', 'col'}:
            self.stack.append((tag, hidden, modal))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        tags = [item[0] for item in self.stack]
        if any(tag in tags for tag in ('template', 'noscript')):
            return
        if 'script' in tags:
            self.options |= bool(re.search(r'\b_cf_chl_opt\s*=\s*\{', data))
            return
        if 'title' in tags:
            self.title += data
        if any(item[1] for item in self.stack) or any(tag in tags for tag in ('style', 'head', 'title', 'iframe')):
            return
        if 'h1' in tags:
            self.h1 += data
        elif 'h2' in tags:
            self.h2 += data
        if data.strip():
            self.verification_prompt |= bool(re.match(r'^(?:please\s+)?(?:complete (?:the )?(?:security check|captcha)|verify (?:that )?you are human)\b', data.strip(), re.I))
            self.body_text = True
            if ('article' in tags or 'main' in tags) and not any(tag in tags for tag in (
                    'h1', 'h2', 'form', 'button', 'label', 'nav', 'aside', 'footer', 'header', 'dialog')):
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
    if parser.password and (not parser.content or parser.modal_password) and named(r'^(Sign in|Log in|Login|Authentication)\b'):
        return 'login'
    return None
