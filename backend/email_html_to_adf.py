"""Convert an HTML email body into Atlassian Document Format (ADF) block nodes.

Built on the stdlib html.parser rather than a third-party HTML library: email
HTML from Outlook/Gmail is inconsistently well-formed, but the structural
subset we care about (paragraphs, bold/italic, links, lists, line breaks) is
small enough that a purpose-built walker is simpler than adding a dependency.
Anything outside that subset (div/span/font wrappers, tables, images) is
unwrapped -- its text still flows through, just without special styling.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

_MARK_TAGS = {
    "b": "strong",
    "strong": "strong",
    "i": "em",
    "em": "em",
}

_LIST_TAGS = {"ul": "bulletList", "ol": "orderedList"}


class _EmailHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, Any]] = []
        self._paragraph: list[dict[str, Any]] = []
        self._mark_stack: list[dict[str, Any]] = []
        # Top of stack is where a just-finished paragraph/list gets appended --
        # the document root, or a listItem's content when inside <li>...</li>.
        self._container_stack: list[list[dict[str, Any]]] = [self.blocks]

    def _flush_paragraph(self) -> None:
        if self._paragraph:
            self._container_stack[-1].append({"type": "paragraph", "content": self._paragraph})
            self._paragraph = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("p", "div"):
            self._flush_paragraph()
        elif tag == "br":
            self._paragraph.append({"type": "hardBreak"})
        elif tag in _MARK_TAGS:
            self._mark_stack.append({"type": _MARK_TAGS[tag]})
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._mark_stack.append({"type": "link", "attrs": {"href": href}})
        elif tag in _LIST_TAGS:
            self._flush_paragraph()
            list_node: dict[str, Any] = {"type": _LIST_TAGS[tag], "content": []}
            self._container_stack[-1].append(list_node)
            self._container_stack.append(list_node["content"])
        elif tag == "li":
            self._flush_paragraph()
            item_node: dict[str, Any] = {"type": "listItem", "content": []}
            self._container_stack[-1].append(item_node)
            self._container_stack.append(item_node["content"])

    def handle_endtag(self, tag: str) -> None:
        if tag in ("p", "div"):
            self._flush_paragraph()
        elif tag in _MARK_TAGS:
            self._pop_mark(_MARK_TAGS[tag])
        elif tag == "a":
            self._pop_mark("link")
        elif tag in _LIST_TAGS or tag == "li":
            self._flush_paragraph()
            if len(self._container_stack) > 1:
                self._container_stack.pop()

    def _pop_mark(self, mark_type: str) -> None:
        for index in range(len(self._mark_stack) - 1, -1, -1):
            if self._mark_stack[index]["type"] == mark_type:
                del self._mark_stack[index]
                return

    def handle_data(self, data: str) -> None:
        if not data:
            return
        node: dict[str, Any] = {"type": "text", "text": data}
        if self._mark_stack:
            node["marks"] = list(self._mark_stack)
        self._paragraph.append(node)

    def close(self) -> None:
        super().close()
        self._flush_paragraph()


def _sanitize_list_nesting(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ADF requires bulletList/orderedList content to consist solely of
    listItem nodes. Word/Outlook HTML exports sometimes emit a nested <ol>
    directly inside another <ol> with no intervening <li> -- valid-ish HTML
    browsers tolerate, but Jira's ADF validator rejects a list that directly
    contains another list outright (confirmed against HRD-1299/McMorris,
    where this failed ticket creation with "not valid Atlassian Document
    Format (ADF) content" -- and since that happens before an issue key
    exists, no ticket and no .eml audit copy got created either). Wrap any
    non-listItem child of a list node in a synthetic listItem.
    """
    sanitized: list[dict[str, Any]] = []
    for node in nodes:
        node = dict(node)
        if "content" in node:
            node["content"] = _sanitize_list_nesting(node["content"])
        if node.get("type") in ("bulletList", "orderedList"):
            node["content"] = [
                child if child.get("type") == "listItem" else {"type": "listItem", "content": [child]}
                for child in node["content"]
            ]
        sanitized.append(node)
    return sanitized


def html_to_adf_nodes(html: str) -> list[dict[str, Any]]:
    """Parse an HTML email body into a list of ADF block nodes."""
    parser = _EmailHtmlParser()
    parser.feed(html)
    parser.close()
    return _sanitize_list_nesting(parser.blocks)


def adf_text_length(nodes: list[dict[str, Any]]) -> int:
    """Total length of the visible text across a list of ADF block nodes."""
    total = 0
    for node in nodes:
        if node.get("type") == "text":
            total += len(node.get("text", ""))
        elif "content" in node:
            total += adf_text_length(node["content"])
    return total
