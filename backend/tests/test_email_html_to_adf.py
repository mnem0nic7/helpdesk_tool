"""Tests for the email HTML -> ADF converter used by the AskHR bot connector."""
from __future__ import annotations

from email_html_to_adf import adf_text_length, html_to_adf_nodes


def test_adf_text_length_counts_text_across_paragraphs_and_lists():
    nodes = html_to_adf_nodes("<p>ab</p><ul><li>cde</li></ul>")
    assert adf_text_length(nodes) == 5


def test_plain_paragraph_becomes_a_single_text_node():
    nodes = html_to_adf_nodes("<p>Hello there</p>")
    assert nodes == [
        {"type": "paragraph", "content": [{"type": "text", "text": "Hello there"}]}
    ]


def test_unordered_list_becomes_a_bullet_list():
    nodes = html_to_adf_nodes("<ul><li>first item</li><li>second item</li></ul>")
    assert nodes == [
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "first item"}]}],
                },
                {
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "second item"}]}],
                },
            ],
        }
    ]


def test_divs_become_separate_paragraphs():
    nodes = html_to_adf_nodes("<div>Hello,</div><div>Thanks,</div><div>Saige</div>")
    assert nodes == [
        {"type": "paragraph", "content": [{"type": "text", "text": "Hello,"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "Thanks,"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "Saige"}]},
    ]


def test_br_becomes_a_hard_break_within_one_paragraph():
    nodes = html_to_adf_nodes("<p>line one<br>line two</p>")
    assert nodes == [
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "line one"},
                {"type": "hardBreak"},
                {"type": "text", "text": "line two"},
            ],
        }
    ]


def test_span_and_font_and_table_wrappers_are_unwrapped_to_flowing_text():
    nodes = html_to_adf_nodes(
        '<table><tbody><tr><td><div><span style="color:red">'
        '<font face="Calibri">wrapped text</font></span></div></td></tr></tbody></table>'
    )
    assert nodes == [{"type": "paragraph", "content": [{"type": "text", "text": "wrapped text"}]}]


def test_real_world_outlook_markup_from_hrd_1333_yields_readable_paragraphs():
    """HRD-1333's stored description was the literal raw HTML below (see the
    2026-09-04 Rachel Brady email report). This is a trimmed fragment of that
    real payload -- heavy inline `revert!important` styling on tables/divs,
    a caution-banner table, and nested div/font/span wrappers around the
    sender's actual message. The converter must not choke on it and must
    surface the sender's real text as plain readable paragraphs.
    """
    html = (
        '<table style="width:100%!important"><tbody><tr>'
        '<td style="color:revert!important">ignored banner cell</td>'
        "</tr></tbody></table>"
        '<div><div style="padding:2pt"><div style="background-color:#FFEB9C">'
        '<font face="Calibri,sans-serif" size="2"><span style="font-size:11pt">'
        '<b>CAUTION:</b><span> This email originated outside the company.</span>'
        "</span></font></div></div>"
        "<div><div>Hello, <div dir=\"auto\"><br></div>"
        '<div dir="auto">Attached is the receipt for the shipment of my equipment.</div>'
        '<div dir="auto"><br></div><div dir="auto">Thank you,</div>'
        '<div dir="auto"><br></div><div dir="auto">Saige Melson</div></div></div>'
    )

    nodes = html_to_adf_nodes(html)

    def flatten_text(node: dict) -> str:
        if node.get("type") == "text":
            return node.get("text", "")
        return "".join(flatten_text(child) for child in node.get("content", []))

    full_text = "".join(flatten_text(node) for node in nodes)
    assert "ignored banner cell" in full_text
    assert "CAUTION: This email originated outside the company." in full_text
    assert "Attached is the receipt for the shipment of my equipment." in full_text
    assert "Saige Melson" in full_text
    # No raw markup should have leaked into the text content.
    assert "<" not in full_text and ">" not in full_text
    assert "revert!important" not in full_text
    # The CAUTION line keeps its bold mark.
    caution_node = next(n for n in nodes[1]["content"] if n.get("text") == "CAUTION:")
    assert caution_node["marks"] == [{"type": "strong"}]


def test_ordered_list_becomes_an_ordered_list():
    nodes = html_to_adf_nodes("<ol><li>step one</li></ol>")
    assert nodes == [
        {
            "type": "orderedList",
            "content": [
                {
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "step one"}]}],
                },
            ],
        }
    ]


def test_anchor_becomes_a_link_mark():
    nodes = html_to_adf_nodes('<p>see <a href="https://example.com">this page</a> please</p>')
    assert nodes == [
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "see "},
                {
                    "type": "text",
                    "text": "this page",
                    "marks": [{"type": "link", "attrs": {"href": "https://example.com"}}],
                },
                {"type": "text", "text": " please"},
            ],
        }
    ]


def test_bold_and_italic_become_marks():
    nodes = html_to_adf_nodes("<p>plain <b>bold</b> and <i>italic</i> text</p>")
    assert nodes == [
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "plain "},
                {"type": "text", "text": "bold", "marks": [{"type": "strong"}]},
                {"type": "text", "text": " and "},
                {"type": "text", "text": "italic", "marks": [{"type": "em"}]},
                {"type": "text", "text": " text"},
            ],
        }
    ]
