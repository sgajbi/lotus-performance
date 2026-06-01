from pathlib import Path

from scripts.python_function_size_inventory import collect_function_sizes, render_markdown


def test_collect_function_sizes_orders_largest_functions_first(tmp_path: Path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "\n".join(
            [
                "def small():",
                "    return 1",
                "",
                "class Service:",
                "    def larger(self):",
                "        value = 1",
                "        value += 1",
                "        return value",
            ]
        ),
        encoding="utf-8",
    )

    functions = collect_function_sizes(["sample.py"], root=tmp_path)

    assert [function.qualified_name for function in functions] == ["Service.larger", "small"]
    assert [function.lines for function in functions] == [4, 2]


def test_collect_function_sizes_handles_async_and_nested_functions(tmp_path: Path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "\n".join(
            [
                "async def outer():",
                "    def inner():",
                "        return 1",
                "    return inner()",
            ]
        ),
        encoding="utf-8",
    )

    functions = collect_function_sizes(["sample.py"], root=tmp_path)

    assert [function.qualified_name for function in functions] == ["outer", "outer.inner"]
    assert [function.lines for function in functions] == [4, 2]


def test_render_markdown_includes_ranked_function_locations(tmp_path: Path):
    sample = tmp_path / "sample.py"
    sample.write_text("def sample():\n    return 1\n", encoding="utf-8")

    [function] = collect_function_sizes(["sample.py"], root=tmp_path)

    assert render_markdown([function]) == "\n".join(
        [
            "| Rank | Function | File | Lines |",
            "| ---: | --- | --- | ---: |",
            "| 1 | `sample` | `sample.py:1` | 2 |",
        ]
    )
