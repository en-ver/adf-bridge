from copy import deepcopy

import pytest

from adf_bridge import (
    AdfConversionError,
    AdfValidationError,
    Diagnostic,
    LossyConversionError,
    adf_to_markdown,
    markdown_image_urls,
    markdown_to_adf,
    validate_adf,
)


def test_markdown_to_adf_produces_valid_representative_document() -> None:
    result = markdown_to_adf(
        "# Title\n\nTom &amp; Jerry &copy &copy;: [a **bold** c](https://example.test)."
    )

    assert result.diagnostics == ()
    assert result.value["content"][0] == {
        "type": "heading",
        "attrs": {"level": 1},
        "content": [{"type": "text", "text": "Title"}],
    }
    inline = result.value["content"][1]["content"]
    assert inline[0]["text"] == "Tom & Jerry &copy ©: "
    linked = [node for node in inline if node.get("marks")]
    linked[0]["marks"][0]["attrs"]["href"] = "https://changed.test"
    assert linked[1]["marks"][0]["attrs"]["href"] == "https://example.test"
    validate_adf(result.value)
    with pytest.raises(AdfConversionError, match="empty Markdown links"):
        markdown_to_adf('[](https://example.test "title")')


def test_markdown_image_nested_under_bullet_text_is_block_media() -> None:
    result = markdown_to_adf(
        "- Bullet text\n\n  ![diagram](https://images.test/diagram.png)"
    )

    assert result.value["content"] == [
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Bullet text"}],
                        },
                        {
                            "type": "mediaSingle",
                            "attrs": {"layout": "center"},
                            "content": [
                                {
                                    "type": "media",
                                    "attrs": {
                                        "type": "external",
                                        "url": "https://images.test/diagram.png",
                                        "alt": "diagram",
                                    },
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    ]


def test_adf_to_markdown_escapes_literals_and_serializes_marks() -> None:
    literal_starts = [
        "# Title",
        "- item",
        "+ item",
        "* item",
        "> quote",
        "1. item",
        "1) item",
        "---",
        "===",
        "~~~lang",
        "    code",
    ]
    document = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Title"}],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "a", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": "b", "marks": [{"type": "strong"}]},
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": " ", "marks": [{"type": "strong"}]}
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "https://plain.test "
                            "https://one.test/?next=https://two.test,"
                            "https://three.test "
                        ),
                    },
                    {
                        "type": "text",
                        "text": "https://linked.test",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {"href": "https://target.test"},
                            }
                        ],
                    },
                ],
            },
            *[
                {"type": "paragraph", "content": [{"type": "text", "text": text}]}
                for text in literal_starts
            ],
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "a\n# heading"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "foo\n==="}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "& <img src=x>"}],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "hardBreak"},
                    {"type": "text", "text": "x"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "y"},
                ],
            },
        ],
    }

    markdown = adf_to_markdown(document).value
    assert all(
        fragment in markdown
        for fragment in (
            "\\# Title",
            "\\- item",
            "\\+ item",
            "\\* item",
            "&gt; quote",
            "1\\. item",
            "1\\) item",
            "\\---",
            "\\===",
            "\\~\\~\\~lang",
            "&#32;&#32;&#32;&#32;code",
            "a&#10;# heading",
            "foo&#10;===",
            "&amp; &lt;img src=x&gt;",
            (
                "https&#58;//plain.test https&#58;//one.test/?next="
                "https&#58;//two.test,https&#58;//three.test&#32;"
                "[&#104;ttps://linked.test](<https://target.test>)"
            ),
        )
    )
    reparsed = markdown_to_adf(markdown).value["content"]
    assert reparsed[0]["type"] == "heading"
    assert all(block["type"] == "paragraph" for block in reparsed[1:])
    assert reparsed[1]["content"] == [
        {"type": "text", "text": "ab", "marks": [{"type": "strong"}]}
    ]
    assert reparsed[3]["content"] == [
        {
            "type": "text",
            "text": (
                "https://plain.test "
                "https://one.test/?next=https://two.test,https://three.test "
            ),
        },
        {
            "type": "text",
            "text": "https://linked.test",
            "marks": [{"type": "link", "attrs": {"href": "https://target.test"}}],
        },
    ]
    assert markdown_to_adf("https://markdown.test").value["content"][0]["content"] == [
        {
            "type": "text",
            "text": "https://markdown.test",
            "marks": [{"type": "link", "attrs": {"href": "https://markdown.test"}}],
        }
    ]
    assert reparsed[-1]["content"] == [
        {"type": "hardBreak"},
        {"type": "text", "text": "x"},
        {"type": "hardBreak"},
        {"type": "text", "text": "y"},
    ]
    trailing_hash_heading = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": "Title ###"}],
            }
        ],
    }
    assert adf_to_markdown(trailing_hash_heading).value == "# Title &#35;&#35;&#35;"
    assert (
        markdown_to_adf(adf_to_markdown(trailing_hash_heading).value).value
        == trailing_hash_heading
    )
    bare_hash_heading = deepcopy(trailing_hash_heading)
    bare_hash_heading["content"][0]["content"][0]["text"] = "#"
    assert adf_to_markdown(bare_hash_heading).value == "# &#35;"
    assert (
        markdown_to_adf(adf_to_markdown(bare_hash_heading).value).value
        == bare_hash_heading
    )
    paragraph_hash = deepcopy(trailing_hash_heading)
    paragraph_hash["content"][0]["type"] = "paragraph"
    paragraph_hash["content"][0].pop("attrs")
    assert adf_to_markdown(paragraph_hash).value == "Title ###"

    terminal_heading = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [
                    {"type": "text", "text": "x"},
                    {"type": "hardBreak"},
                    {"type": "hardBreak"},
                ],
            },
            {"type": "paragraph", "content": [{"type": "text", "text": "after"}]},
        ],
    }
    terminal_result = adf_to_markdown(terminal_heading)
    assert terminal_result.value == "# x\n\nafter"
    assert [(item.code, item.path) for item in terminal_result.diagnostics] == [
        ("adf.terminal_hard_break_discarded", "/content/0/content/1"),
        ("adf.terminal_hard_break_discarded", "/content/0/content/2"),
    ]
    assert markdown_to_adf(terminal_result.value).value == {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": "x"}],
            },
            {"type": "paragraph", "content": [{"type": "text", "text": "after"}]},
        ],
    }
    with pytest.raises(LossyConversionError) as raised:
        adf_to_markdown(terminal_heading, strict=True)
    assert raised.value.diagnostics == terminal_result.diagnostics

    nonterminal_heading_break = deepcopy(terminal_heading)
    nonterminal_heading_break["content"][0]["content"].append(
        {"type": "text", "text": "y"}
    )
    with pytest.raises(AdfConversionError) as raised:
        adf_to_markdown(nonterminal_heading_break)
    assert raised.value.path == "/content/0/content/1"

    terminal_list = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": "x"},
                                    {"type": "hardBreak"},
                                    {"type": "hardBreak"},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    terminal_quote = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "blockquote",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "x"},
                            {"type": "hardBreak"},
                        ],
                    }
                ],
            }
        ],
    }
    for nested, expected, paths in (
        (
            terminal_list,
            "- x",
            (
                "/content/0/content/0/content/0/content/1",
                "/content/0/content/0/content/0/content/2",
            ),
        ),
        (terminal_quote, "> x", ("/content/0/content/0/content/1",)),
    ):
        nested_result = adf_to_markdown(nested)
        assert nested_result.value == expected
        assert [(item.code, item.path) for item in nested_result.diagnostics] == [
            ("adf.terminal_hard_break_discarded", path) for path in paths
        ]

    adjacent_lists = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "a"}],
                            }
                        ],
                    }
                ],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "b"}],
                            }
                        ],
                    }
                ],
            },
            {
                "type": "orderedList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "c"}],
                            }
                        ],
                    }
                ],
            },
            {
                "type": "orderedList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "d"}],
                            }
                        ],
                    }
                ],
            },
        ],
    }
    adjacent_markdown = adf_to_markdown(adjacent_lists).value
    assert adjacent_markdown == "- a\n\n* b\n\n1. c\n\n1) d"
    assert markdown_to_adf(adjacent_markdown).value == adjacent_lists
    nested_adjacent_lists = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "parent"}],
                            },
                            *deepcopy(adjacent_lists["content"][:2]),
                        ],
                    }
                ],
            }
        ],
    }
    nested_markdown = adf_to_markdown(nested_adjacent_lists).value
    assert nested_markdown == "- parent\n\n  - a\n\n  * b"
    assert markdown_to_adf(nested_markdown).value == nested_adjacent_lists
    overlong_order = deepcopy(adjacent_lists)
    overlong_order["content"] = [
        {
            "type": "orderedList",
            "attrs": {"order": 999_999_999},
            "content": adjacent_lists["content"][2]["content"]
            + adjacent_lists["content"][3]["content"],
        }
    ]
    with pytest.raises(AdfConversionError) as raised:
        adf_to_markdown(overlong_order)
    assert raised.value.path == "/content/0/attrs/order"


def test_inline_fragment_boundaries_preserve_supported_sequences() -> None:
    document = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "!"},
                    {
                        "type": "text",
                        "text": "x",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {"href": "https://x.test"},
                            }
                        ],
                    },
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "a"},
                    {"type": "text", "text": "b", "marks": [{"type": "em"}]},
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "a"},
                    {
                        "type": "text",
                        "text": "!",
                        "marks": [{"type": "strong"}],
                    },
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "`",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {"href": "https://x.test"},
                            }
                        ],
                    },
                    {"type": "text", "text": "a", "marks": [{"type": "code"}]},
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "a", "marks": [{"type": "strong"}]},
                    {
                        "type": "text",
                        "text": "b",
                        "marks": [{"type": "strong"}, {"type": "em"}],
                    },
                ],
            },
        ],
    }

    markdown = adf_to_markdown(document).value
    assert markdown == (
        "&#33;[&#120;](<https://x.test>)\n\n"
        "&#97;_&#98;_\n\n"
        "&#97;**&#33;**\n\n"
        "[&#96;](<https://x.test>)`a`\n\n"
        "**&#97;_&#98;_**"
    )
    assert markdown_to_adf(markdown).value == document

    link_label = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "https://x.test/a*b",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {"href": "https://target.test"},
                            }
                        ],
                    }
                ],
            }
        ],
    }
    assert adf_to_markdown(link_label).value == (
        "[https://x.test/a&#42;b](<https://target.test>)"
    )
    assert markdown_to_adf(adf_to_markdown(link_label).value).value == link_label

    inline_card = deepcopy(link_label)
    inline_card["content"][0]["content"] = [
        {"type": "inlineCard", "attrs": {"url": "https://x.test/a*b"}}
    ]
    assert "\\*" not in adf_to_markdown(inline_card).value
    assert "&#42;" in adf_to_markdown(inline_card).value

    image = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "mediaSingle",
                "attrs": {"layout": "center"},
                "content": [
                    {
                        "type": "media",
                        "attrs": {
                            "type": "external",
                            "url": "https://image.test",
                            "alt": "https://x.test/a*b",
                        },
                    }
                ],
            }
        ],
    }
    image_markdown = adf_to_markdown(image).value
    assert image_markdown == "![https://x.test/a&#42;b](<https://image.test>)"
    assert markdown_to_adf(image_markdown).value == image

    linked_code = deepcopy(link_label)
    linked_code["content"][0]["content"][0]["text"] = "["
    linked_code["content"][0]["content"][0]["marks"].append({"type": "code"})
    with pytest.raises(AdfConversionError) as raised:
        adf_to_markdown(linked_code)
    assert raised.value.path == "/content/0/content/0/text"


def test_literal_boundaries_and_code_normalization_are_explicit() -> None:
    document = {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": " x "}]},
            {"type": "paragraph", "content": [{"type": "text", "text": " "}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "a\nb"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "\r\n"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "x\t"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "\vX\v"}]},
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "\u0085X\u0085"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": " x ", "marks": [{"type": "em"}]}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": " ", "marks": [{"type": "code"}]}],
            },
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "a\r\nb",
                        "marks": [{"type": "code"}],
                    }
                ],
            },
        ],
    }

    result = adf_to_markdown(document)
    assert result.value == (
        "&#32;x&#32;\n\n&#32;\n\na&#10;b\n\n&#13;&#10;\n\nx&#9;\n\n\vX\v\n\n\u0085X\u0085\n\n"
        "_&#32;x&#32;_\n\n` `\n\n`a b`"
    )
    assert result.diagnostics[0].code == "adf.code_span_line_break_normalized"
    assert result.diagnostics[0].path == "/content/9/content/0/text"
    reparsed = markdown_to_adf(result.value).value["content"]
    assert [block["content"][0]["text"] for block in reparsed] == [
        " x ",
        " ",
        "a\nb",
        "\r\n",
        "x\t",
        "\vX\v",
        "\u0085X\u0085",
        " x ",
        " ",
        "a b",
    ]
    assert reparsed[7]["content"][0]["marks"] == [{"type": "em"}]
    assert reparsed[8]["content"][0]["marks"] == [{"type": "code"}]
    unmarked_vertical_tab = {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "\v"}]}],
    }
    assert adf_to_markdown(unmarked_vertical_tab).value == "\v"
    assert markdown_to_adf("\v").value == unmarked_vertical_tab

    list_vertical_tab = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "\v"}],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    list_vertical_tab_result = adf_to_markdown(list_vertical_tab)
    assert list_vertical_tab_result.value == "- \v"
    assert [
        (item.code, item.path) for item in list_vertical_tab_result.diagnostics
    ] == [
        (
            "adf.boundary_whitespace_normalized",
            "/content/0/content/0/content/0/content/0/text",
        )
    ]
    with pytest.raises(LossyConversionError) as raised:
        adf_to_markdown(list_vertical_tab, strict=True)
    assert raised.value.diagnostics == list_vertical_tab_result.diagnostics

    table_boundary_whitespace = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableHeader",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "h"}],
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableCell",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {"type": "text", "text": "\u0085X\u0085"}
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ],
    }
    table_boundary_result = adf_to_markdown(table_boundary_whitespace)
    assert table_boundary_result.value.endswith("| \u0085X\u0085 |")
    assert [(item.code, item.path) for item in table_boundary_result.diagnostics] == [
        (
            "adf.boundary_whitespace_normalized",
            "/content/0/content/1/content/0/content/0/content/0/text",
        )
    ]
    assert markdown_to_adf(table_boundary_result.value).value["content"][0]["content"][
        1
    ]["content"][0]["content"][0]["content"] == [{"type": "text", "text": "X"}]
    with pytest.raises(LossyConversionError) as raised:
        adf_to_markdown(table_boundary_whitespace, strict=True)
    assert raised.value.diagnostics == table_boundary_result.diagnostics

    exact_table_boundary = deepcopy(table_boundary_whitespace)
    exact_table_boundary["content"][0]["content"][1]["content"][0]["content"][0][
        "content"
    ][0]["text"] = "\u00a0X\u00a0"
    exact_table_result = adf_to_markdown(exact_table_boundary)
    assert "&#160;X&#160;" in exact_table_result.value
    assert exact_table_result.diagnostics == ()
    assert markdown_to_adf(exact_table_result.value).value == exact_table_boundary

    form_feed = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "\fX\f", "marks": [{"type": "em"}]}
                ],
            }
        ],
    }
    form_feed_result = adf_to_markdown(form_feed)
    assert form_feed_result.value == "_&#12;X&#12;_"
    assert form_feed_result.diagnostics == ()
    assert markdown_to_adf(form_feed_result.value).value == form_feed

    degraded_presentation = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "\vX\u0085",
                        "marks": [{"type": "strong"}],
                    }
                ],
            }
        ],
    }
    degraded = adf_to_markdown(degraded_presentation)
    assert degraded.value == "\vX\u0085"
    assert [(item.code, item.path) for item in degraded.diagnostics] == [
        ("adf.presentation_mark_degraded", "/content/0/content/0/marks")
    ]
    assert markdown_to_adf(degraded.value).value["content"][0]["content"] == [
        {"type": "text", "text": "\vX\u0085"}
    ]
    with pytest.raises(LossyConversionError) as raised:
        adf_to_markdown(degraded_presentation, strict=True)
    assert raised.value.diagnostics == degraded.diagnostics

    code_block = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "codeBlock",
                "content": [{"type": "text", "text": "x\r\ny"}],
            }
        ],
    }
    normalized_code_block = adf_to_markdown(code_block)
    assert normalized_code_block.value == "```\nx\ny\n```"
    assert [(item.code, item.path) for item in normalized_code_block.diagnostics] == [
        ("adf.code_block_text_normalized", "/content/0/content")
    ]
    assert markdown_to_adf(normalized_code_block.value).value == {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "codeBlock",
                "content": [{"type": "text", "text": "x\ny\n"}],
            }
        ],
    }
    with pytest.raises(LossyConversionError):
        adf_to_markdown(code_block, strict=True)
    canonical_code_block = deepcopy(code_block)
    canonical_code_block["content"][0]["content"][0]["text"] = "x\ny\n"
    assert adf_to_markdown(canonical_code_block).diagnostics == ()
    assert (
        adf_to_markdown(
            {"type": "doc", "version": 1, "content": [{"type": "codeBlock"}]}
        ).value
        == "```\n```"
    )

    with pytest.raises(LossyConversionError) as raised:
        adf_to_markdown(document, strict=True)
    assert raised.value.diagnostics == result.diagnostics


def test_mentions_preserve_opaque_identity_and_canonicalize_label() -> None:
    result = markdown_to_adf("[~ACCOUNTid:557057:User-AbC]")

    mention = result.value["content"][0]["content"][0]
    assert mention == {"type": "mention", "attrs": {"id": "557057:User-AbC"}}
    assert result.diagnostics == ()
    assert adf_to_markdown(result.value).value == "[~accountId:557057:User-AbC]"

    adjacent = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "mention", "attrs": {"id": "a"}},
                    {"type": "mention", "attrs": {"id": "b"}},
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "mention", "attrs": {"id": "a"}},
                    {"type": "text", "text": "(x)"},
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "mention", "attrs": {"id": "a"}},
                    {
                        "type": "text",
                        "text": "x",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {"href": "https://x.test"},
                            }
                        ],
                    },
                ],
            },
        ],
    }
    adjacent_markdown = adf_to_markdown(adjacent).value
    assert adjacent_markdown == (
        "[~accountId:a][~accountId:b]\n\n"
        "[~accountId:a]&#40;x)\n\n"
        "[~accountId:a][&#120;](<https://x.test>)"
    )
    assert markdown_to_adf(adjacent_markdown).value == adjacent

    opaque_id = "<script>&copy;</script>"
    document = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "mention", "attrs": {"id": opaque_id}}],
            }
        ],
    }
    markdown = adf_to_markdown(document).value
    assert markdown == "[~accountId:&lt;script&gt;&amp;copy;&lt;/script&gt;]"
    assert markdown_to_adf(markdown).value["content"][0]["content"][0] == {
        "type": "mention",
        "attrs": {"id": opaque_id},
    }
    assert markdown_to_adf("[~accountId:&amp;lt;]").value["content"][0]["content"][
        0
    ] == {
        "type": "mention",
        "attrs": {"id": "&lt;"},
    }
    with pytest.raises(AdfConversionError):
        markdown_to_adf("[~accountId:&#32;]")
    with pytest.raises(AdfConversionError) as raised:
        markdown_to_adf("[~accountId:a\x00b]")
    assert raised.value.path == ""
    document["content"][0]["content"][0]["attrs"]["id"] = "a\x00b"
    with pytest.raises(AdfConversionError) as raised:
        adf_to_markdown(document)
    assert raised.value.path == "/content/0/content/0/attrs/id"
    document["content"][0]["content"][0]["attrs"]["id"] = "bad id"
    with pytest.raises(AdfConversionError) as raised:
        adf_to_markdown(document)
    assert raised.value.path == "/content/0/content/0/attrs/id"


@pytest.mark.parametrize(
    "markdown",
    (
        "**[~accountId:A]**",
        "*[~accountId:A]*",
        "~~[~accountId:A]~~",
        "***[~accountId:A]***",
    ),
)
def test_formatted_mentions_degrade_to_unmarked_mentions_with_diagnostics(
    markdown: str,
) -> None:
    diagnostic = Diagnostic(
        "markdown.mention_marks_discarded",
        "warning",
        "Formatting around a Jira mention cannot be represented in ADF "
        "and was discarded",
    )
    expected = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "mention", "attrs": {"id": "A"}}],
            }
        ],
    }

    result = markdown_to_adf(markdown)
    assert result.value == expected
    assert result.diagnostics == (diagnostic,)
    assert adf_to_markdown(result.value).value == "[~accountId:A]"
    with pytest.raises(LossyConversionError) as raised:
        markdown_to_adf(markdown, strict=True)
    assert raised.value.diagnostics == result.diagnostics

    discovery = markdown_image_urls(
        f"{markdown}\n\n![diagram](https://image.test/a.png)"
    )
    assert discovery.value == ("https://image.test/a.png",)
    assert discovery.diagnostics == result.diagnostics
    with pytest.raises(LossyConversionError) as raised:
        markdown_image_urls(
            f"{markdown}\n\n![diagram](https://image.test/a.png)", strict=True
        )
    assert raised.value.diagnostics == result.diagnostics


def test_schema_rejection_uses_project_error() -> None:
    with pytest.raises(AdfValidationError) as raised:
        validate_adf(
            {"type": "doc", "version": 1, "content": [{"type": "text", "text": "no"}]}
        )

    assert raised.value.path == "/content/0"
    cyclic: list[object] = []
    cyclic.append(cyclic)
    with pytest.raises(AdfValidationError) as raised:
        validate_adf(cyclic)  # type: ignore[arg-type]
    assert raised.value.path == "/0"


def test_empty_adf_paragraph_profile_by_gfm_owner_context() -> None:
    empty_paragraph = {"type": "paragraph"}
    canonical_empty_root = {"type": "doc", "version": 1, "content": [empty_paragraph]}
    assert adf_to_markdown(canonical_empty_root).value == ""
    assert markdown_to_adf("").value == canonical_empty_root
    assert adf_to_markdown({"type": "doc", "version": 1, "content": []}).value == ""

    for markdown in (
        ">",
        "> ",
        "> \v",
        "> &#11;",
        "> \u0085",
        "> \u00a0",
        "> \\\n> \u00a0",
    ):
        for strict in (False, True):
            with pytest.raises(AdfConversionError):
                markdown_to_adf(markdown, strict=strict)

    quote_cases = (
        ([empty_paragraph], "/content/0/content/0"),
        (
            [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "\v"}],
                }
            ],
            "/content/0/content/0",
        ),
        (
            [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "\u00a0",
                            "marks": [{"type": "strong"}],
                        }
                    ],
                }
            ],
            "/content/0/content/0",
        ),
        (
            [
                {
                    "type": "paragraph",
                    "content": [{"type": "hardBreak"}],
                }
            ],
            "/content/0/content/0",
        ),
        (
            [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "hardBreak"},
                        {"type": "text", "text": "\u00a0"},
                    ],
                }
            ],
            "/content/0/content/0",
        ),
        (
            [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "a"}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "\v"}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "b"}],
                },
            ],
            "/content/0/content/1",
        ),
    )
    for quote_content, path in quote_cases:
        document = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "blockquote", "content": quote_content}],
        }
        for strict in (False, True):
            with pytest.raises(AdfConversionError) as raised:
                adf_to_markdown(document, strict=strict)
            assert raised.value.path == path

    quote_boundary_whitespace = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "blockquote",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "\va"}],
                    },
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "b\v"}],
                    },
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "\vc\v"}],
                    },
                ],
            }
        ],
    }
    quote_boundary_result = adf_to_markdown(quote_boundary_whitespace)
    assert quote_boundary_result.value == "> \va\n>\n> b\v\n>\n> \vc\v"
    assert [(item.code, item.path) for item in quote_boundary_result.diagnostics] == [
        ("adf.boundary_whitespace_normalized", "/content/0/content/0/content/0/text"),
        ("adf.boundary_whitespace_normalized", "/content/0/content/1/content/0/text"),
        ("adf.boundary_whitespace_normalized", "/content/0/content/2/content/0/text"),
    ]
    assert (
        markdown_to_adf(quote_boundary_result.value).value == quote_boundary_whitespace
    )
    with pytest.raises(LossyConversionError) as raised:
        adf_to_markdown(quote_boundary_whitespace, strict=True)
    assert raised.value.diagnostics == quote_boundary_result.diagnostics

    post_hard_break_whitespace = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "blockquote",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "hardBreak"},
                            {"type": "text", "text": "\vvt"},
                            {"type": "hardBreak"},
                            {"type": "text", "text": "\u0085nel"},
                            {"type": "hardBreak"},
                            {"type": "text", "text": "\u00a0nbsp"},
                        ],
                    }
                ],
            }
        ],
    }
    post_hard_break_result = adf_to_markdown(post_hard_break_whitespace)
    assert post_hard_break_result.value == (
        "> \\\n> \vvt\\\n> \u0085nel\\\n> &#160;nbsp"
    )
    assert [(item.code, item.path) for item in post_hard_break_result.diagnostics] == [
        ("adf.boundary_whitespace_normalized", "/content/0/content/0/content/1/text"),
        ("adf.boundary_whitespace_normalized", "/content/0/content/0/content/3/text"),
        ("adf.boundary_whitespace_normalized", "/content/0/content/0/content/5/text"),
    ]
    with pytest.raises(LossyConversionError) as raised:
        adf_to_markdown(post_hard_break_whitespace, strict=True)
    assert raised.value.diagnostics == post_hard_break_result.diagnostics

    root_post_hard_break_whitespace = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "hardBreak"},
                    {
                        "type": "text",
                        "text": "\u00a0nbsp",
                        "marks": [{"type": "em"}],
                    },
                ],
            }
        ],
    }
    root_post_hard_break_result = adf_to_markdown(root_post_hard_break_whitespace)
    assert root_post_hard_break_result.value == "\\\n_&#160;nbsp_"
    assert [
        (item.code, item.path) for item in root_post_hard_break_result.diagnostics
    ] == [
        ("adf.boundary_whitespace_normalized", "/content/0/content/1/text"),
    ]
    assert (
        markdown_to_adf(root_post_hard_break_result.value).value
        == root_post_hard_break_whitespace
    )
    with pytest.raises(LossyConversionError) as raised:
        adf_to_markdown(root_post_hard_break_whitespace, strict=True)
    assert raised.value.diagnostics == root_post_hard_break_result.diagnostics

    documents = (
        (
            {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": []}],
            },
            "/content/0",
        ),
        (
            {
                "type": "doc",
                "version": 1,
                "content": [
                    empty_paragraph,
                    {"type": "paragraph", "content": [{"type": "text", "text": "x"}]},
                ],
            },
            "/content/0",
        ),
    )

    for document, path in documents:
        with pytest.raises(AdfConversionError) as raised:
            adf_to_markdown(document)
        assert raised.value.path == path

    definitions = markdown_to_adf("[r]: /url")
    assert definitions.value == canonical_empty_root
    assert [item.code for item in definitions.diagnostics] == [
        "markdown.reference_definitions_discarded"
    ]
    with pytest.raises(LossyConversionError) as raised:
        markdown_to_adf("[r]: /url", strict=True)
    assert raised.value.diagnostics == definitions.diagnostics


def test_empty_gfm_list_items_and_table_cells_close() -> None:
    cases = {
        "- ": "-",
        "| h |\n|---|\n| |": "| h |\n| --- |\n|  |",
    }

    for markdown, canonical in cases.items():
        document = markdown_to_adf(markdown).value
        rendered = adf_to_markdown(document)
        assert rendered.value == canonical
        assert rendered.diagnostics == ()
        assert markdown_to_adf(rendered.value).value == document


def test_lossy_diagnostic_escalates_in_strict_mode() -> None:
    document = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "status", "attrs": {"text": "Ready", "color": "green"}}
                ],
            }
        ],
    }

    result = adf_to_markdown(document)
    assert result.value == "Ready"
    assert (result.diagnostics[0].code, result.diagnostics[1].path) == (
        "adf.status_degraded",
        "/content/0/content/0/attrs/color",
    )
    with pytest.raises(LossyConversionError) as raised:
        adf_to_markdown(document, strict=True)
    assert raised.value.diagnostics == result.diagnostics


def test_table_and_image_flow_is_parseable_and_diagnosed() -> None:
    document = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableHeader",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "h"}],
                                    }
                                ],
                            },
                            {
                                "type": "tableCell",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "data"}],
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableHeader",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": "a|b",
                                                "marks": [{"type": "code"}],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ],
    }

    table = adf_to_markdown(document)
    assert "| `a\\|b` |  |" in table.value
    reparsed_table = markdown_to_adf(table.value).value["content"][0]
    assert reparsed_table["type"] == "table"
    assert reparsed_table["content"][1]["content"][0]["content"][0]["content"] == [
        {"type": "text", "text": "a|b", "marks": [{"type": "code"}]}
    ]
    nested_syntax = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableHeader",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "h"}],
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableCell",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {
                                                "type": "mention",
                                                "attrs": {"id": "a|b"},
                                            },
                                            {
                                                "type": "text",
                                                "text": "x",
                                                "marks": [
                                                    {
                                                        "type": "link",
                                                        "attrs": {
                                                            "href": "https://x.test",
                                                            "title": "a|b",
                                                        },
                                                    }
                                                ],
                                            },
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ],
    }
    nested_syntax_markdown = adf_to_markdown(nested_syntax)
    assert "[~accountId:a&#124;b]" in nested_syntax_markdown.value
    assert '"a&#124;b"' in nested_syntax_markdown.value
    assert nested_syntax_markdown.diagnostics == ()
    assert markdown_to_adf(nested_syntax_markdown.value).value == nested_syntax

    assert {(item.code, item.path) for item in table.diagnostics} >= {
        ("adf.table_header_normalized", "/content/0/content/0/content/1"),
        ("adf.table_header_normalized", "/content/0/content/1/content/0"),
        ("adf.table_row_padded", "/content/0/content/1"),
    }
    unsupported = deepcopy(document)
    cell_content = unsupported["content"][0]["content"][1]["content"][0]["content"]
    cell_content[0]["content"][0]["text"] = r"a\|b"
    with pytest.raises(AdfConversionError, match="backslash before a pipe") as raised:
        adf_to_markdown(unsupported)
    assert raised.value.path == "/content/0/content/1/content/0/content/0/content/0"
    cell_content[0]["content"] = [
        {"type": "text", "text": "a"},
        {"type": "hardBreak"},
        {"type": "text", "text": "b"},
    ]
    cell_content.append(
        {"type": "paragraph", "content": [{"type": "text", "text": "c"}]}
    )
    flattened = adf_to_markdown(unsupported)
    assert "| a<br>b<br>c |  |" in flattened.value
    assert [item.code for item in flattened.diagnostics].count(
        "adf.table_cell_flattened"
    ) == 1
    assert flattened.diagnostics[0].path == "/content/0/content/1/content/0"
    reparsed_flattened = markdown_to_adf(flattened.value).value
    assert reparsed_flattened["content"][0]["content"][1]["content"][0]["content"][0][
        "content"
    ] == [
        {"type": "text", "text": "a"},
        {"type": "hardBreak"},
        {"type": "text", "text": "b"},
        {"type": "hardBreak"},
        {"type": "text", "text": "c"},
    ]
    with pytest.raises(LossyConversionError):
        adf_to_markdown(unsupported, strict=True)
    noncanonical = markdown_to_adf("| h |\n|---|\n| a<BR>b |")
    assert noncanonical.diagnostics[0].code == "markdown.raw_html"
    assert markdown_to_adf("<br>").diagnostics[0].code == "markdown.raw_html"

    image = markdown_to_adf('![a\nb](https://image.test/a.png "title")')
    assert image.value["content"][0]["type"] == "mediaSingle"
    assert image.value["content"][0]["content"][0]["attrs"]["alt"] == "a b"
    assert image.diagnostics[0].code == "markdown.image_title_discarded"
    assert (
        markdown_to_adf("![a  \nb](https://image.test/a.png)").value["content"][0][
            "content"
        ][0]["attrs"]["alt"]
        == "a b"
    )
    with pytest.raises(LossyConversionError):
        markdown_to_adf('![a\nb](https://image.test/a.png "title")', strict=True)
    with pytest.raises(AdfConversionError):
        markdown_to_adf("# ![alt](https://image.test/a.png)")
    with pytest.raises(AdfConversionError):
        markdown_to_adf("[![alt](https://image.test/a.png)](https://target.test)")


def test_untrusted_values_and_discarded_metadata_are_diagnosed() -> None:
    document = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "link",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {
                                    "href": "https://safe/<img src=x onerror=alert(1)",
                                    "title": "title\x00<script>alert(1)</script>",
                                },
                            }
                        ],
                    },
                    {"type": "hardBreak", "attrs": {"text": "\n"}},
                ],
            },
            {
                "type": "codeBlock",
                "attrs": {"language": "py\n<script>alert(1)</script>"},
                "content": [{"type": "text", "text": "x"}],
            },
        ],
    }

    result = adf_to_markdown(document)
    assert "<img" not in result.value
    assert "<script" not in result.value
    assert "&#60;img" in result.value
    assert result.value.startswith("[link](<https://safe/")
    assert {(item.code, item.path) for item in result.diagnostics} >= {
        ("adf.attribute_discarded", "/content/0/content/1/attrs/text"),
        ("adf.attribute_discarded", "/content/0/content/0/marks/0/attrs/title"),
        ("adf.code_language_discarded", "/content/1/attrs/language"),
    }
    for language in ("c#", "f#", "foo/bar"):
        safe = adf_to_markdown(
            {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "codeBlock",
                        "attrs": {"language": language},
                        "content": [{"type": "text", "text": "x\n"}],
                    }
                ],
            }
        )
        assert safe.value.startswith(f"```{language}\n")
        assert safe.diagnostics == ()
    with pytest.raises(LossyConversionError):
        adf_to_markdown(document, strict=True)

    empty_title = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "link",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {"href": "https://x.test", "title": ""},
                            }
                        ],
                    }
                ],
            }
        ],
    }
    empty_title_result = adf_to_markdown(empty_title)
    assert empty_title_result.value == "[link](<https://x.test>)"
    assert [(item.code, item.path) for item in empty_title_result.diagnostics] == [
        ("adf.attribute_discarded", "/content/0/content/0/marks/0/attrs/title")
    ]
    with pytest.raises(LossyConversionError) as raised:
        adf_to_markdown(empty_title, strict=True)
    assert raised.value.diagnostics == empty_title_result.diagnostics


def test_destinations_titles_and_degraded_text_are_source_safe() -> None:
    document = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "x",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {
                                    "href": "https://x.test/?q=&copy;",
                                    "title": "A &copy;",
                                },
                            }
                        ],
                    },
                    {"type": "hardBreak"},
                    {
                        "type": "status",
                        "attrs": {"text": "# heading", "color": "green"},
                    },
                    {"type": "hardBreak"},
                    {
                        "type": "emoji",
                        "attrs": {"text": "- item", "shortName": ":item:"},
                    },
                    {
                        "type": "inlineCard",
                        "attrs": {"url": "https://x.test/?q=&copy;"},
                    },
                ],
            }
        ],
    }
    result = adf_to_markdown(document)
    assert '[x](<https://x.test/?q=&#38;copy;> "A &amp;copy;")' in result.value
    assert "\\\n\\# heading\\\n\\- ite&#109;" in result.value
    assert (
        "[&#104;ttps://x.test/?q=&amp;copy;](<https://x.test/?q=&#38;copy;>)"
        in result.value
    )
    reparsed = markdown_to_adf(result.value).value["content"][0]["content"]
    assert reparsed[0]["marks"][0]["attrs"] == {
        "href": "https://x.test/?q=&copy;",
        "title": "A &copy;",
    }

    image = markdown_to_adf("![alt](https://x.test/?q=&amp;copy;)").value
    image_markdown = adf_to_markdown(image).value
    assert "![alt](<https://x.test/?q=&#38;copy;>)" in image_markdown
    assert markdown_to_adf(image_markdown).value == image

    ipv6 = deepcopy(document)
    ipv6["content"][0]["content"][0]["marks"][0]["attrs"]["href"] = "https://[::1]/x"
    ipv6_result = adf_to_markdown(ipv6)
    assert "[x](<https://&#91;::1&#93;/x>" in ipv6_result.value
    assert (
        markdown_to_adf(ipv6_result.value).value["content"][0]["content"][0]["marks"][
            0
        ]["attrs"]["href"]
        == "https://[::1]/x"
    )
    reference_markdown = "[x][r]\n\n[r]: <https://[::1]/雪>"
    assert markdown_to_adf(reference_markdown).diagnostics == ()
    assert (
        tuple(
            markdown_to_adf(markdown).value["content"][0]["content"][0]["marks"][0][
                "attrs"
            ]["href"]
            for markdown in (reference_markdown, "<https://[::1]/雪>")
        )
        == ("https://%5B::1%5D/%E9%9B%AA",) * 2
    )

    unrepresentable_href = deepcopy(ipv6)
    unrepresentable_href["content"][0]["content"][0]["marks"][0]["attrs"]["href"] = (
        "https://x.test/\x00"
    )
    with pytest.raises(AdfConversionError) as raised:
        adf_to_markdown(unrepresentable_href)
    assert raised.value.path == "/content/0/content/0/marks/0/attrs/href"

    nul_text = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "a\x00b", "marks": [{"type": "strong"}]},
                    {
                        "type": "status",
                        "attrs": {"text": "c\x00d", "color": "green"},
                    },
                ],
            }
        ],
    }
    nul_result = adf_to_markdown(nul_text)
    assert "\x00" not in nul_result.value
    assert nul_result.value.count("\ufffd") == 2
    assert [(item.code, item.path) for item in nul_result.diagnostics] == [
        ("adf.nul_normalized", "/content/0/content/0/text"),
        ("adf.status_degraded", "/content/0/content/1"),
        ("adf.attribute_discarded", "/content/0/content/1/attrs/color"),
        ("adf.nul_normalized", "/content/0/content/1/attrs/text"),
    ]
    with pytest.raises(LossyConversionError) as raised:
        adf_to_markdown(nul_text, strict=True)
    assert raised.value.diagnostics == nul_result.diagnostics

    markdown_nul = markdown_to_adf("a\x00b")
    assert markdown_nul.value["content"][0]["content"] == [
        {"type": "text", "text": "a\ufffdb"}
    ]
    assert [(item.code, item.path) for item in markdown_nul.diagnostics] == [
        ("markdown.nul_normalized", None)
    ]
    with pytest.raises(LossyConversionError) as raised:
        markdown_to_adf("a\x00b", strict=True)
    assert raised.value.diagnostics == markdown_nul.diagnostics

    managed_media = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "mediaSingle",
                "attrs": {"layout": "center"},
                "content": [
                    {
                        "type": "media",
                        "attrs": {
                            "type": "file",
                            "id": "attachment-id",
                            "collection": "attachments",
                            "alt": "# heading",
                        },
                    }
                ],
            }
        ],
    }
    managed_result = adf_to_markdown(managed_media)
    assert managed_result.value == "\\# heading"
    assert {(item.code, item.path) for item in managed_result.diagnostics} >= {
        ("adf.media_single_degraded", "/content/0"),
        ("adf.media_degraded", "/content/0/content/0"),
    }
    with pytest.raises(LossyConversionError) as raised:
        adf_to_markdown(managed_media, strict=True)
    assert raised.value.diagnostics == managed_result.diagnostics

    status_url = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "status",
                        "attrs": {"text": "https://fallback.test", "color": "green"},
                    }
                ],
            }
        ],
    }
    status_markdown = adf_to_markdown(status_url).value
    assert status_markdown == "https&#58;//fallback.test"
    assert markdown_to_adf(status_markdown).value["content"][0]["content"] == [
        {"type": "text", "text": "https://fallback.test"}
    ]


@pytest.mark.parametrize("media_type", ["file", "link"])
@pytest.mark.parametrize("alt", [None, ""])
def test_managed_media_never_presents_its_id(media_type: str, alt: str | None) -> None:
    media_id = "123e4567-e89b-12d3-a456-426614174000"
    document = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": f"ordinary {media_id}"}],
            },
            {
                "type": "mediaSingle",
                "attrs": {"layout": "center"},
                "content": [
                    {
                        "type": "media",
                        "attrs": {
                            "type": media_type,
                            "id": media_id,
                            "collection": "attachments",
                        },
                    }
                ],
            },
        ],
    }

    if alt is not None:
        document["content"][1]["content"][0]["attrs"]["alt"] = alt

    no_alt = adf_to_markdown(document).value
    assert no_alt == f"ordinary {media_id}\n\nattachment"
    assert no_alt.count(media_id) == 1

    with_alt = deepcopy(document)
    with_alt["content"][1]["content"][0]["attrs"]["alt"] = "# readable"
    rendered_alt = adf_to_markdown(with_alt).value
    assert rendered_alt == f"ordinary {media_id}\n\n\\# readable"
    assert rendered_alt.count(media_id) == 1


@pytest.mark.parametrize(
    "mark",
    [
        {"type": "alignment", "attrs": {"align": "center"}},
        {"type": "indentation", "attrs": {"level": 1}},
    ],
)
def test_supported_block_marks_are_fatal(mark: dict[str, object]) -> None:
    document = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "marks": [mark],
                "content": [{"type": "text", "text": "x"}],
            }
        ],
    }

    for strict in (False, True):
        with pytest.raises(AdfConversionError) as raised:
            adf_to_markdown(document, strict=strict)
        assert raised.value.path == "/content/0/marks/0"


@pytest.mark.parametrize(
    ("mark", "container_mark"),
    [
        ({"type": "dataConsumer", "attrs": {"sources": ["source"]}}, None),
        (
            {
                "type": "annotation",
                "attrs": {"id": "id", "annotationType": "inlineComment"},
            },
            None,
        ),
        ({"type": "border", "attrs": {"size": 1, "color": "#000000"}}, None),
        ({"type": "link", "attrs": {"href": "https://target.test"}}, None),
        (None, {"type": "link", "attrs": {"href": "https://target.test"}}),
        (
            {"type": "link", "attrs": {"href": "https://child.test"}},
            {"type": "link", "attrs": {"href": "https://container.test"}},
        ),
    ],
)
def test_media_context_marks_are_fatal(
    mark: dict[str, object] | None, container_mark: dict[str, object] | None
) -> None:
    media: dict[str, object] = {
        "type": "media",
        "attrs": {"type": "external", "url": "https://image.test"},
    }
    if mark is not None:
        media["marks"] = [mark]
    media_single: dict[str, object] = {
        "type": "mediaSingle",
        "attrs": {"layout": "center"},
        "content": [media],
    }
    if container_mark is not None:
        media_single["marks"] = [container_mark]
    document = {"type": "doc", "version": 1, "content": [media_single]}

    for strict in (False, True):
        with pytest.raises(AdfConversionError) as raised:
            adf_to_markdown(document, strict=strict)
        assert raised.value.path == (
            "/content/0/marks/0"
            if container_mark is not None
            else "/content/0/content/0/marks/0"
        )


@pytest.mark.parametrize(
    "markdown",
    ["> # heading", "> > nested", "> ---", "> | h |\n> |---|\n> | x |"],
)
def test_unsupported_blockquote_children_fail_during_mapping(markdown: str) -> None:
    with pytest.raises(AdfConversionError):
        markdown_to_adf(markdown)

    permitted = markdown_to_adf("> paragraph\n>\n> - item").value["content"][0]
    assert permitted["type"] == "blockquote"
