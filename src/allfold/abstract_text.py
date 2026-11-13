"""Safe text for new persistent abstracts, independent of legacy comparison rules."""
from html.parser import HTMLParser
from html import escape
import re


_BLOCKS = {'p', 'div', 'section', 'sec', 'title', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
           'li', 'blockquote', 'abstract'}
_HEADINGS = {'abstract', 'summary', 'background', 'objectives', 'objective', 'methods',
             'results', 'conclusions', 'conclusion'}
_INLINE = {'a', 'b', 'strong', 'i', 'em', 'span', 'sub', 'sup', 'u', 'italic', 'bold', 'xref'}
_VOID = {'br', 'hr', 'img', 'wbr'}
_MARKUP = _BLOCKS | _INLINE | _VOID | {'script', 'style', 'template'}
_TAGS = re.compile(r'</?([A-Za-z][A-Za-z0-9:_.-]*)(?:\s[^<>]*?)?/?>')
_EMPTY_NOTICE = re.compile(
    r'(?:no abstract(?: available)?|abstract (?:unavailable|not available)|'
    r'please (?:log|sign) in(?: to (?:view|read) (?:the )?abstract)?)[.!]?|'
    r'(?:read|show|view)\s+(?:more|full(?:\s+abstract)?)[\s.…]*', re.I)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.excluded = [], 0

    def handle_starttag(self, tag, attrs):
        tag = tag.rsplit(':', 1)[-1]
        if tag in {'script', 'style', 'template'}:
            self.excluded += 1
        elif not self.excluded and (tag in _BLOCKS or tag in {'br', 'hr'}):
            self.parts.append('\n')
        elif not self.excluded and tag not in _INLINE | _VOID:
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        tag = tag.rsplit(':', 1)[-1]
        if tag in {'script', 'style', 'template'}:
            self.excluded = max(0, self.excluded - 1)
        elif not self.excluded and tag in _BLOCKS:
            self.parts.append('\n')
        elif not self.excluded and tag not in _INLINE | _VOID:
            self.parts.append('</' + tag + '>')

    def handle_data(self, data):
        if not self.excluded:
            self.parts.append(data)


def normalize_abstract_text(value: str | None) -> str | None:
    """Remove explicit markup/wrappers while retaining scientific text and lines."""
    if value is None:
        return None
    tags = '|'.join(sorted(_MARKUP))
    if (re.match(r'\s*<(?:[\w-]+:)?(?:' + tags + r')(?:\s|/?>)', value, re.I)
            or re.search(r'</(?:[\w-]+:)?(?:' + tags + r')\s*>|<!--|<!DOCTYPE', value, re.I)):
        parser = _Text()
        # Literal scientific angle notation is text, including original case.
        parser.feed(_TAGS.sub(lambda match: match[0] if match[1].casefold().rsplit(':', 1)[-1] in _MARKUP
            else escape(match[0], quote=False), value))
        parser.close()
        text = ''.join(parser.parts)
    else:
        text = value
    lines = [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line and line.casefold().rstrip(':').strip() not in {'abstract', 'summary'}]
    if not any(line.casefold().rstrip(':').strip() not in _HEADINGS for line in lines):
        return None
    text = '\n'.join(lines)
    if re.fullmatch(r'[\s.…-]+', text) or _EMPTY_NOTICE.fullmatch(re.sub(r'\s+', ' ', text)):
        return None
    return text or None
