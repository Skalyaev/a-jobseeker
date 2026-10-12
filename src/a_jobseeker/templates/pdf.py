"""ReportLab helpers shared by PDF templates.

Documents only use the standard PDF fonts and single-column text flows: the text
layer stays in reading order, which keeps files easy to parse for applicant
tracking systems (ATS).
"""

import unicodedata
from xml.sax.saxutils import escape

# Standard PDF fonts are WinAnsi (cp1252) encoded: map what can be mapped.
_FALLBACKS = {
    "\u00a0": " ",
    "\u202f": " ",
    "\u2009": " ",
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2015": "\u2014",
    "\u2212": "-",
    "\u2192": "->",
    "\u2190": "<-",
    "\u2264": "<=",
    "\u2265": ">=",
    "\u2248": "~",
    "\u2713": "",
    "\u2714": "",
}


def plain(text: object) -> str:
    """Return ``text`` restricted to what the standard PDF fonts can draw (cp1252)."""
    out = []
    for char in unicodedata.normalize("NFC", str(text or "")):
        mapped = _FALLBACKS.get(char, char)
        try:
            mapped.encode("cp1252")
        except UnicodeEncodeError:
            decomposed = unicodedata.normalize("NFKD", mapped)
            mapped = decomposed.encode("cp1252", "ignore").decode("cp1252")
        out.append(mapped)
    return "".join(out)


def clean(text: object) -> str:
    """Return ``text`` escaped and encodable for a ReportLab Paragraph in cp1252."""
    return escape(plain(text))


def link(url: str, text: str = "") -> str:
    """Return Paragraph markup for a link showing ``text``, or the URL itself."""
    shown = text or (
        url.removeprefix("https://")
        .removeprefix("http://")
        .removeprefix("www.")
        .rstrip("/")
    )
    return f'<a href="{escape(url, {chr(34): "&quot;"})}">{clean(shown)}</a>'
