#!/usr/bin/env python3
"""Run an HTTP request from a .http (or Markdown) file using curl.

Driven by .zed/tasks.json:
    run_http.py <file> <row>     run the request at 1-based line <row>
    run_http.py <file> --all     run every request in the file
    add --confirm                preview the request and ask before sending
    add --pretty                 pretty-print a JSON response body with jq
    add --timeout <seconds>      max time per request (default 120)

Request format (REST Client / httpyac style). Requests are delimited by '###'
lines, ``` fences, or the next method line:

    ### optional name
    GET https://example.com/health HTTP/1.1
    Accept: application/json

    { optional body }

In Markdown files, requests live inside ```http fenced code blocks. Variables
${NAME} and {{NAME}} are substituted from in-file '@name = value' definitions, a
.env file (in ZED_WORKTREE_ROOT or the file's directory), then the process
environment, in that order of precedence.
"""

import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"}
VAR_RE = re.compile(r"\$\{\s*(\w+)\s*\}|\{\{\s*(\w+)\s*\}\}")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*([^\s`~]*)")


def die(msg):
    print(f"run_http: {msg}", file=sys.stderr)
    raise SystemExit(1)


def is_delim(line):
    return line.lstrip().startswith("###")


def is_fence(line):
    s = line.lstrip()
    return s.startswith("```") or s.startswith("~~~")


def is_method_line(line):
    """True for a request line like 'GET https://…' or 'POST {{host}}/x'."""
    toks = line.split()
    if len(toks) < 2 or toks[0].upper() not in METHODS:
        return False
    t = toks[1]
    return t.startswith(("http://", "https://", "/", "{{", "${")) or "://" in t or "." in t.split("/")[0]


def request_ranges(lines):
    """List of (start, end) content ranges, one per request. A request begins at
    a '###' line, after a ``` fence, or at a method line — so requests are found
    with or without '###' separators. (A method-looking line inside a body can
    rarely cause an extra split; add '###' to be explicit.)"""
    ranges = []
    start = None
    have_method = False

    def flush(end):
        nonlocal start, have_method
        if start is not None and any(lines[j].strip() for j in range(start, end)):
            ranges.append((start, end))
        start, have_method = None, False

    for i, line in enumerate(lines):
        if is_fence(line):            # hard boundary; the fence line is not content
            flush(i)
        elif is_delim(line):          # ### starts a new request (### kept as a comment)
            flush(i)
            start = i
        elif is_method_line(line):
            if have_method:           # a second method line => the next request
                flush(i)
            if start is None:
                start = i
            have_method = True
        elif start is None:           # leading comments/@vars before a method line
            start = i
    flush(len(lines))
    return ranges


def http_fences(lines):
    """List of (content_start, content_end) ranges for ```http blocks in Markdown."""
    ranges = []
    marker = None
    for i, line in enumerate(lines):
        m = FENCE_RE.match(line)
        if marker is None:
            if m:
                marker, lang, cstart = m.group(1), m.group(2).lower(), i + 1
        elif m and m.group(1)[0] == marker[0] and len(m.group(1)) >= len(marker) and not m.group(2):
            if lang == "http":
                ranges.append((cstart, i))
            marker = None
    return ranges


def compute_ranges(lines, is_md):
    """All request ranges; in Markdown, only those inside ```http fences."""
    if not is_md:
        return request_ranges(lines)
    out = []
    for cs, ce in http_fences(lines):
        out += [(cs + s, cs + e) for s, e in request_ranges(lines[cs:ce])]
    return out


def pick_block(lines, ranges, row, is_md):
    """The (start, end) range for the request containing 1-based `row`."""
    r = row - 1
    if is_md:
        fence = next(((cs, ce) for cs, ce in http_fences(lines) if cs <= r < ce), None)
        if fence is None:
            die(f"line {row} is not inside a ```http block")
        ranges = [(s, e) for s, e in ranges if fence[0] <= s < fence[1]]
    chosen = None
    for s, e in ranges:
        if s <= r < e:
            return s, e
        if s <= r:
            chosen = (s, e)  # nearest request starting at/before the cursor
    if chosen:
        return chosen
    if ranges:
        return ranges[0]
    die(f"no HTTP request found at line {row}")


def load_env_file(path):
    vars = {}
    try:
        text = path.read_text()
    except OSError:
        return vars
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        k, v = line.split("=", 1)
        if k.strip():
            vars[k.strip()] = v.strip().strip('"').strip("'")
    return vars


def collect_inline_vars(lines):
    """Read '@name = value' / '@name value' definitions from http content lines."""
    vars = {}
    for raw in lines:
        s = raw.strip()
        if not s.startswith("@"):
            continue
        rest = s[1:]
        k, _, v = rest.partition("=") if "=" in rest else rest.partition(" ")
        if k.strip():  # strip surrounding quotes so the grammar-native @x = "v" runs too
            vars[k.strip()] = v.strip().strip('"').strip("'")
    return vars


def collect_vars(file_path, inline_vars):
    merged = dict(os.environ)
    root = os.environ.get("ZED_WORKTREE_ROOT")
    if root:
        merged.update(load_env_file(Path(root) / ".env"))
    merged.update(load_env_file(file_path.parent / ".env"))
    merged.update(inline_vars)
    return merged


def substitute(text, vars):
    def repl(m):
        name = m.group(1) or m.group(2)
        if name in vars:
            return vars[name]
        print(f"run_http: warning: undefined variable {name!r}", file=sys.stderr)
        return m.group(0)
    return VAR_RE.sub(repl, text)


def parse_request(block):
    """Parse a block into (method, url, headers, body), or None if no request."""
    n = len(block)
    i = 0
    while i < n:
        s = block[i].strip()
        if s and not s.startswith(("#", "//", "@")):
            break
        i += 1
    if i >= n:
        return None
    tokens = block[i].split()
    if tokens[0].upper() in METHODS:
        method, url = tokens[0].upper(), (tokens[1] if len(tokens) > 1 else "")
    else:
        method, url = "GET", tokens[0]
    i += 1
    if not url:
        return None
    headers = []
    while i < n:
        s = block[i].strip()
        i += 1
        if not s:
            break
        if s.startswith(("#", "//")):
            continue
        if ":" in s:
            k, v = s.split(":", 1)
            headers.append((k.strip(), v.strip()))
    body = "\n".join(block[i:]).strip()
    return method, url, headers, body


def preview(method, url, headers, body, cmd):
    print(f"About to send:\n▶ {method} {url}")
    for k, v in headers:
        print(f"  {k}: {v}")
    if body:
        print()
        for line in body.splitlines():
            print(f"  {line}")
    print("\n$ " + shlex.join(cmd))


def confirm_prompt():
    """Ask on the terminal. Enter/y = run, n = skip, EOF = skip, Ctrl+C aborts."""
    try:
        ans = input("Run this request? [Y/n] ").strip().lower()
    except EOFError:
        print()
        return False
    return ans in ("", "y", "yes")


def pretty_body(body):
    """Return `body` reformatted by `jq .`, or unchanged if it isn't valid JSON."""
    if not body.strip():
        return body
    jq = subprocess.run(["jq", "."], input=body, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return jq.stdout if jq.returncode == 0 and jq.stdout.strip() else body


def run_curl_pretty(cmd):
    """Run curl capturing output, then print headers verbatim and prettify a JSON body."""
    proc = subprocess.run(cmd, stdout=subprocess.PIPE)
    out = proc.stdout
    sep = out.find(b"\r\n\r\n")  # curl -i: header block ends at the first blank line
    if sep == -1:
        sys.stdout.buffer.write(out)
    else:
        sys.stdout.buffer.write(out[:sep + 4])
        sys.stdout.buffer.write(pretty_body(out[sep + 4:]))
    sys.stdout.buffer.flush()
    return proc.returncode


def run_request(req, vars, confirm=False, label=None, pretty=False, timeout="120"):
    method, url, headers, body = req
    url = substitute(url, vars)
    headers = [(k, substitute(v, vars)) for k, v in headers]
    body = substitute(body, vars) if body else ""
    cmd = ["curl", "-sS", "-i", "--max-time", str(timeout), "-X", method, url]
    for k, v in headers:
        cmd += ["-H", f"{k}: {v}"]
    if body:
        cmd += ["--data-raw", body]
    if label:
        print(f"=== {label} ===")
    if confirm:
        preview(method, url, headers, body, cmd)
        if not confirm_prompt():
            print("skipped.\n")
            return 0
    else:
        print(f"# {method} {url}")
        print("$ " + shlex.join(cmd) + "\n")
    sys.stdout.flush()  # show the banner before curl writes to the same fd
    start = time.perf_counter()
    try:
        rc = run_curl_pretty(cmd) if pretty else subprocess.run(cmd).returncode
    except FileNotFoundError:
        die("curl not found on PATH")
    print(f"\n# elapsed: {(time.perf_counter() - start) * 1000:.0f} ms\n")
    return rc


def take_value(args, name, default):
    """Pull `--name V` or `--name=V` out of args; return (value, remaining args)."""
    out, val, i = [], default, 0
    while i < len(args):
        a = args[i]
        if a == name:
            if i + 1 >= len(args):
                die(f"{name} requires a value")
            val, i = args[i + 1], i + 2
        elif a.startswith(name + "="):
            val, i = a[len(name) + 1:], i + 1
        else:
            out.append(a)
            i += 1
    return val, out


def main(argv):
    rest = argv[1:]
    confirm = "--confirm" in rest
    pretty = "--pretty" in rest
    timeout, rest = take_value(rest, "--timeout", "120")
    try:
        float(timeout)
    except ValueError:
        die(f"invalid --timeout: {timeout!r}")
    args = [a for a in rest if a not in ("--confirm", "--pretty")]
    if len(args) < 2:
        die("usage: run_http.py <file> <row|--all> [--confirm] [--pretty] [--timeout <seconds>]")
    if pretty and not shutil.which("jq"):
        print("run_http: warning: --pretty requested but jq not found; showing raw output", file=sys.stderr)
        pretty = False
    file_path = Path(args[0])
    selector = args[1]
    try:
        lines = file_path.read_text().splitlines()
    except OSError as e:
        die(f"cannot read {file_path}: {e}")
    is_md = file_path.suffix.lower() in {".md", ".markdown"}

    if is_md:
        http_lines = [l for s, e in http_fences(lines) for l in lines[s:e]]
    else:
        http_lines = lines
    vars = collect_vars(file_path, collect_inline_vars(http_lines))

    ranges = compute_ranges(lines, is_md)
    if selector == "--all":
        reqs = [r for s, e in ranges if (r := parse_request(lines[s:e]))]
        if not reqs:
            die("no HTTP requests found")
        rc = 0
        for idx, req in enumerate(reqs, 1):
            rc |= run_request(req, vars, confirm=confirm, pretty=pretty, timeout=timeout, label=f"request {idx}/{len(reqs)}")
        return rc

    try:
        row = int(selector)
    except ValueError:
        die(f"invalid row: {selector!r}")
    s, e = pick_block(lines, ranges, row, is_md)
    req = parse_request(lines[s:e])
    if not req:
        die(f"no HTTP request found at line {row}")
    return run_request(req, vars, confirm=confirm, pretty=pretty, timeout=timeout)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        print("\naborted.", file=sys.stderr)
        sys.exit(130)
