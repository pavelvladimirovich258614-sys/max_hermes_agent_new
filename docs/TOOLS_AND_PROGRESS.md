# Tools and Progress Messages

## Tools via MAX

When you use a role route (e.g., `/dev`), the agent has access to Hermes tools:

| Tool | What it does |
|------|-------------|
| `terminal` | Execute shell commands |
| `browser` | Navigate web pages, take screenshots |
| `write_file` | Create/modify files (in allowed paths) |
| `search` | Web search via SearXNG or configured backend |

These tools run on the **server where Hermes is installed**, not in MAX.

## Progress Messages

When the agent uses a tool, you see progress messages in MAX chat:

```text
terminal: python3 --version
terminal: Python 3.11.15
browser_navigate: https://python.org
write_file: /tmp/hermes-max-tool-smoke/result.txt
Working...
```

These appear as edit-appended messages (not separate messages) with a rate limit.

## Smoke Test

To verify all tools work from MAX:

```text
/dev Сделай безопасный tool-smoke тест. Используй terminal, search/browser и write_file. Ничего не меняй в проектах. Terminal: проверь версию Python и текущую директорию. Search/browser: найди официальную страницу Python. Write_file: создай только файл /tmp/hermes-max-tool-smoke/result.txt с кратким отчётом. В финале напиши, какие tools использовал и где файл.
```

## Safety

- Tools run with the permissions of the Hermes process user
- File writes are restricted by Hermes security settings
- The agent cannot access your MAX bot token
- Progress messages never include raw API responses with secrets

## Rate Limiting

- Progress append: max 1 per 3 seconds
- Long responses: split into ~500 char chunks
- Markdown is converted to plain text for MAX compatibility
