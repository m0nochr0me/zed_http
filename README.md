# Zed HTTP extension

Make HTTP requests from the Zed editor directly out of `.http` files (and `http`
blocks in Markdown), using `curl`.

## Idea

A single `.http` file can hold many requests, separated by `###`. Each one can be
run individually from the editor — via a ▶ run button in the gutter, the command
palette, or a keybinding. It also works inside fenced `http` code blocks in
Markdown, and supports `{{variables}}`.

```http
@host = "https://httpbin.org"

### get example page
GET {{host}}/get?hello=world HTTP/1.1
Accept: application/json
x-custom-header: some-thing

### send post request
POST {{host}}/post HTTP/1.1
Content-Type: application/json
x-custom-header: some-thing
Authorization: Bearer {{SOME_SECRET_TOKEN}}

{
    "pipi": "pupu"
}
```

## Requirements

- Python 3
- `curl`
- `jq` (optional) — only for the `--pretty` JSON formatting

## Status

Working. The pieces:

- **This repo is a Zed extension** providing the `http` language: syntax
  highlighting plus a ▶ "runnable" on each request (`languages/http/`,
  `extension.toml`). The grammar is [rest-nvim/tree-sitter-http][grammar].
- **Global Zed tasks** (`~/.config/zed/tasks.json`) tagged `http-request` (the tag
  the runnable uses) invoke the runner in every project.
- **`scripts/run_http.py`** (standard-library Python, no dependencies) finds the
  request at the cursor, substitutes variables, and runs it with `curl`. It is put
  on `PATH` (see Setup) so the tasks work from any workspace.

## Setup

### 1. Install the extension (highlighting + the ▶ button)

This extension is not in the Zed registry yet, so install it as a dev extension:

1. In Zed → **Extensions**, **disable/uninstall the published `http` extension**
   if you have it. Both register the `http` language for `.http` files and would
   conflict — this one is a superset (same highlighting **plus** the run button).
2. Zed → **Extensions** → **Install Dev Extension** → select this repository
   folder. Zed compiles the tree-sitter grammar (C); no Rust toolchain needed.

### 2. Install the runner (so requests run in every project)

Put `run_http.py` on your `PATH` (a symlink keeps it in sync with the repo):

```sh
chmod +x scripts/run_http.py
ln -s "$PWD/scripts/run_http.py" ~/.local/bin/run_http.py   # any PATH dir
```

Then add the tasks to your **global** Zed tasks at `~/.config/zed/tasks.json`, so
they are available in every project. Each is tagged `http-request` so the ▶ button
finds them:

```json
[
  {
    "label": "Run HTTP Request",
    "command": "run_http.py",
    "args": ["$ZED_FILE", "$ZED_ROW"],
    "tags": ["http-request"],
    "reveal": "always"
  },
  {
    "label": "Run HTTP Request (confirm)",
    "command": "run_http.py",
    "args": ["$ZED_FILE", "$ZED_ROW", "--confirm"],
    "tags": ["http-request"],
    "reveal": "always"
  },
  {
    "label": "Run All HTTP Requests",
    "command": "run_http.py",
    "args": ["$ZED_FILE", "--all"],
    "reveal": "always"
  }
]
```

Prefer per-project tasks? Put the same array in a project's `.zed/tasks.json`
instead (you can reference `$ZED_WORKTREE_ROOT/scripts/run_http.py` directly,
skipping the symlink) — but don't define them both globally and locally, or each
task shows up twice.

## Usage

Put the cursor anywhere inside a request, then either:

- click the **▶** in the gutter on the request's first line, or
- run **`task: spawn`** → "Run HTTP Request", or
- bind a key (in `keymap.json`):

  ```json
  {
    "context": "Editor",
    "bindings": {
      "cmd-enter": ["task::Spawn", { "task_name": "Run HTTP Request" }]
    }
  }
  ```

The response (status, headers, body) appears in a terminal tab, followed by an
`# elapsed: <N> ms` line with the request's wall-clock time.

Tasks available:

- **Run HTTP Request** — run the request at the cursor.
- **Run HTTP Request (confirm)** — show a preview (method, URL, headers, body, and
  the exact `curl` command) and ask before sending; Enter/`y` runs, `n` skips,
  `Ctrl+C` aborts.
- **Run All HTTP Requests** — run every request in the file in order.

### Options

These flags can be added to a task's `args` (after `$ZED_FILE` and the row/`--all`
selector):

- **`--pretty`** — pretty-print a JSON response body with [`jq`][jq]. If `jq` is not
  on `PATH`, the raw body is shown unchanged. Response headers are always left as-is.
- **`--timeout <seconds>`** — maximum time per request, passed to `curl --max-time`.
  Defaults to `120`. Accepts `--timeout 30` or `--timeout=30`.

For example, a "pretty" variant of the run task:

```json
{
  "label": "Run HTTP Request (pretty)",
  "command": "run_http.py",
  "args": ["$ZED_FILE", "$ZED_ROW", "--pretty"],
  "tags": ["http-request"],
  "reveal": "always"
}
```

### Markdown

Requests inside fenced `http` blocks work the same way — the ▶ appears on each
request and the runner targets the request under the cursor.

## Writing requests

For both highlighting and the ▶ to work, use the grammar's syntax:

- **Variables are `{{NAME}}`** (not `${NAME}`).
- **Inline values are quoted:** `@base = "https://api.example.com"`.

```http
@base = "https://httpbin.org"

### uses an inline variable and an environment variable
GET {{base}}/get?hello=world HTTP/1.1
Authorization: Bearer {{TOKEN}}
Accept: application/json
```

`{{NAME}}` is resolved from, in order of precedence:

1. inline `@name = "value"` declarations in the file,
2. a `.env` file (in the Zed worktree root, or next to the file),
3. the process environment.

The runner also tolerates `${NAME}` and unquoted `@name = value` when executing,
but those forms break the grammar, so you lose highlighting and the ▶ for that
file — prefer `{{NAME}}` and quoted values.

## Limitations

- Requests are delimited by a `###` line, a fenced code block boundary, or the
  next method line. A method-looking line inside a body can rarely cause an extra
  split — add `###` to be explicit.
- `curl` does the sending, so behavior matches `curl`.

## External Documentation

- [Developing extensions](https://zed.dev/docs/extensions/developing-extensions)
- [API testing using HTTP files and REST Client](https://devblogs.microsoft.com/ise/api-testing-using-http-files/)
- [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html)

[grammar]: https://github.com/rest-nvim/tree-sitter-http
[jq]: https://jqlang.github.io/jq/
