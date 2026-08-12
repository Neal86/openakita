from pathlib import Path


"""One-shot helper that makes the parallel-tool regression mandatory in CI."""


def main() -> None:
    path = Path(".github/workflows/ci.yml")
    text = path.read_text("utf-8")
    old = '''      - name: Verify parallel tool execution\n        if: ${{ hashFiles('tests/llm/unit/test_tool_parallel_execution.py') != '' }}\n        run: pytest tests/llm/unit/test_tool_parallel_execution.py -v\n\n      - name: Skip tool_parallel (test file missing)\n        if: ${{ hashFiles('tests/llm/unit/test_tool_parallel_execution.py') == '' }}\n        run: echo "tests/llm/unit/test_tool_parallel_execution.py not found; skipping."\n'''
    new = '''      - name: Verify parallel tool execution\n        run: pytest tests/test_tool_parallel_execution.py -v\n'''
    if old not in text:
        if new in text:
            return
        raise SystemExit("parallel CI marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


if __name__ == "__main__":
    main()
