from scripts.python_duplicate_code_inventory import (
    DuplicateCodeChunk,
    DuplicateCodeHotspot,
    collect_duplicate_code_hotspots,
    render_markdown,
)


def test_collect_duplicate_code_hotspots_groups_identical_functions(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "\n".join(
            [
                "def duplicate_a():",
                '    """same body"""',
                "    value = 1",
                "    value += 2",
                "    return value",
                "",
                "def duplicate_b():",
                '    """same body"""',
                "    marker = 1",
                "    marker += 2",
                "    return marker",
            ]
        ),
        encoding="utf-8",
    )

    hotspots = collect_duplicate_code_hotspots(["sample.py"], root=tmp_path, min_lines=3)

    assert len(hotspots) == 1
    assert hotspots[0].count == 2
    assert hotspots[0].lines == 3
    assert [chunk.qualified_name for chunk in hotspots[0].chunks] == ["duplicate_a", "duplicate_b"]


def test_collect_duplicate_code_hotspots_respects_min_lines(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "\n".join(["def too_short():", "    return 1", "", "def also_short():", "    return 2"]),
        encoding="utf-8",
    )

    hotspots = collect_duplicate_code_hotspots(["sample.py"], root=tmp_path, min_lines=4)

    assert hotspots == []


def test_render_markdown_reports_duplicate_counts_and_locations():
    output = render_markdown(
        [
            DuplicateCodeHotspot(
                lines=5,
                count=2,
                chunks=(
                    DuplicateCodeChunk(
                        path="app/api/endpoints/sample.py",
                        qualified_name="handler_a",
                        start_line=10,
                        end_line=20,
                        lines=5,
                    ),
                    DuplicateCodeChunk(
                        path="app/services/sample.py",
                        qualified_name="service_a",
                        start_line=40,
                        end_line=50,
                        lines=5,
                    ),
                ),
            )
        ],
        limit=5,
    )

    assert "| Duplicate hotspot groups | 1 |" in output
    assert "| Duplicate functions/methods | 2 |" in output
    assert "| 1 | 2 | 5 | 2 | `app/api/endpoints/sample.py:10-20`<br>`app/services/sample.py:40-50` |" in output
