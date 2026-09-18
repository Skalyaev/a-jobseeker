"""HTML helpers shared by scrapers."""

import re

from bs4 import BeautifulSoup
from bs4.element import Comment, Tag

BLOCK_TAGS = frozenset({"p", "div", "ul", "ol", "h1", "h2", "h3", "h4"})


def html_to_text(node: Tag) -> str:
    """Flatten rich HTML into readable plain text, keeping lists and paragraphs."""
    out: list[str] = []

    def walk(element: Tag) -> None:
        for child in element.children:
            if not isinstance(child, Tag):
                if not isinstance(child, Comment):
                    out.append(str(child))
            elif child.name == "br":
                out.append("\n")
            elif child.name == "li":
                # Paragraphs nested in list items would break the "- item" line.
                out.append("\n- " + " ".join(html_to_text(child).split()))
            elif child.name in BLOCK_TAGS:
                out.append("\n")
                walk(child)
                out.append("\n")
            else:
                walk(child)

    walk(node)
    lines = [" ".join(line.split()) for line in "".join(out).splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_fragment_to_text(html: str | None) -> str:
    """Convert an HTML fragment (e.g. a rich text API field) to plain text."""
    if not html:
        return ""
    return html_to_text(BeautifulSoup(html, "html.parser"))
