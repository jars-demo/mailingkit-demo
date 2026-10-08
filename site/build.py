"""Build mailingkit.jishanahmed.in into _site/.

Standard library only, so it runs anywhere Python 3.11+ does (including the Vercel build image).
Run from the repository root: python site/build.py

- Pages live in site/pages/*.html: an HTML fragment with a small header comment, where fenced
  code blocks (```python ... ```) are escaped and highlighted at build time.
- The API reference is generated from the package source with ``ast``, without importing it,
  so it always matches the code and needs no dependencies.
"""

from __future__ import annotations

import ast
import builtins
import html
import io
import keyword
import re
import shutil
import tokenize
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
OUT = ROOT / "_site"
PACKAGE = ROOT / "src" / "mailingkit"
BASE_URL = "https://mailingkit.jishanahmed.in"
REPO_URL = "https://github.com/jars-demo/mailingkit-demo"

VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]

# Sidebar for the docs, in reading order: (group, [(slug, label)]).
DOCS_NAV: list[tuple[str, list[tuple[str, str]]]] = [
    ("Start here", [("docs", "Getting started"), ("docs/architecture", "How it fits")]),
    (
        "Guides",
        [
            ("docs/templates", "Templates"),
            ("docs/providers", "Providers"),
            ("docs/development", "Development mode"),
            ("docs/reliability", "Errors and retries"),
            ("docs/frameworks", "Framework integration"),
            ("docs/testing", "Testing"),
        ],
    ),
    (
        "Reference",
        [
            ("docs/configuration", "Configuration"),
            ("docs/security", "Security"),
            ("docs/api", "API reference"),
        ],
    ),
]


# Syntax highlighting


def _span(kind: str, text: str) -> str:
    return (
        f'<span class="tok-{kind}">{html.escape(text, quote=False)}</span>'
        if kind
        else html.escape(text, quote=False)
    )


_BUILTINS = set(dir(builtins))
_STRING_TOKENS = {tokenize.STRING} | {
    getattr(tokenize, name)
    for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
    if hasattr(tokenize, name)
}


def highlight_python(code: str) -> str:
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return html.escape(code, quote=False)
    lines = code.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    out: list[str] = []
    position = 0
    previous = ""
    for index, token in enumerate(tokens):
        if token.type == tokenize.ENDMARKER:
            break
        start = offsets[token.start[0] - 1] + token.start[1]
        end = offsets[token.end[0] - 1] + token.end[1]
        if start < position:
            continue
        out.append(html.escape(code[position:start], quote=False))
        text = code[start:end]
        following = tokens[index + 1].string if index + 1 < len(tokens) else ""
        kind = ""
        if token.type == tokenize.COMMENT:
            kind = "c"
        elif token.type in _STRING_TOKENS:
            kind = "s"
        elif token.type == tokenize.NUMBER:
            kind = "n"
        elif token.type == tokenize.NAME:
            if previous in {"def", "class"}:
                kind = "f"
            elif previous == "@":
                kind = "d"
            elif keyword.iskeyword(text) or (
                keyword.issoftkeyword(text) and following not in {"=", "(", "."}
            ):
                kind = "k"
            elif text in _BUILTINS:
                kind = "b"
            elif following == "(":
                kind = "fn"
        elif token.type == tokenize.OP and text == "@" and following and following[0].isalpha():
            kind = "d"
        out.append(_span(kind, text))
        position = end
        if token.type not in {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT}:
            previous = text
    out.append(html.escape(code[position:], quote=False))
    return "".join(out)


_SHELL_TOKEN = re.compile(
    r"(?P<c>#.*$)|(?P<s>\"[^\"]*\"|'[^']*')|(?P<v>\$?\b[A-Z][A-Z0-9_]{2,}\b(?==))", re.M
)


def highlight_shell(code: str) -> str:
    out: list[str] = []
    position = 0
    for match in _SHELL_TOKEN.finditer(code):
        if match.group("c") and match.start() > 0 and code[match.start() - 1] not in " \n":
            continue
        out.append(html.escape(code[position : match.start()], quote=False))
        kind = {"c": "c", "s": "s", "v": "k"}[match.lastgroup or "c"]
        out.append(_span(kind, match.group()))
        position = match.end()
    out.append(html.escape(code[position:], quote=False))
    return "".join(out)


_TOML_TOKEN = re.compile(r"(?P<c>#.*$)|(?P<k>^\[[^\]]+\]+)|(?P<s>\"[^\"]*\")", re.M)


def highlight_toml(code: str) -> str:
    out: list[str] = []
    position = 0
    for match in _TOML_TOKEN.finditer(code):
        out.append(html.escape(code[position : match.start()], quote=False))
        out.append(_span(match.lastgroup or "", match.group()))
        position = match.end()
    out.append(html.escape(code[position:], quote=False))
    return "".join(out)


HIGHLIGHTERS = {
    "python": highlight_python,
    "bash": highlight_shell,
    "shell": highlight_shell,
    "env": highlight_shell,
    "toml": highlight_toml,
}


def code_block(language: str, code: str, title: str = "") -> str:
    highlighted = HIGHLIGHTERS.get(language, lambda c: html.escape(c, quote=False))(code)
    label = html.escape(title or language or "text")
    return (
        f'<figure class="code"><figcaption><span>{label}</span>'
        f'<button class="copy" type="button" aria-label="Copy code">Copy</button></figcaption>'
        f'<pre><code class="language-{html.escape(language)}">{highlighted}</code></pre></figure>'
    )


_FENCE = re.compile(
    r"^```(?P<lang>[\w-]*)(?:[ \t]+(?P<title>[^\n]*))?\n(?P<code>.*?)\n```[ \t]*$", re.S | re.M
)


def render_fences(fragment: str) -> str:
    return _FENCE.sub(
        lambda m: code_block(m.group("lang"), m.group("code"), (m.group("title") or "").strip()),
        fragment,
    )


# Pages


@dataclass
class Page:
    slug: str
    title: str
    description: str
    layout: str
    body: str
    toc: list[tuple[int, str, str]] = field(default_factory=list)


_HEADER = re.compile(r"^\s*<!--(?P<meta>.*?)-->", re.S)
_HEADING = re.compile(r"<h(?P<level>[23])(?P<attrs>[^>]*)>(?P<text>.*?)</h(?P=level)>", re.S)


def slugify(text: str) -> str:
    plain = re.sub(r"<[^>]+>", "", html.unescape(text)).lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


def add_heading_ids(body: str) -> tuple[str, list[tuple[int, str, str]]]:
    toc: list[tuple[int, str, str]] = []
    used: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        level, attrs, text = int(match.group("level")), match.group("attrs"), match.group("text")
        existing = re.search(r'id="([^"]+)"', attrs)
        anchor = existing.group(1) if existing else slugify(text)
        base, n = anchor, 2
        while anchor in used:
            anchor, n = f"{base}-{n}", n + 1
        used.add(anchor)
        toc.append((level, anchor, text.strip()))
        if not existing:
            attrs = f'{attrs} id="{anchor}"'
        return (
            f'<h{level}{attrs}><a class="anchor" href="#{anchor}" aria-hidden="true">#</a>'
            f"{text}</h{level}>"
        )

    return _HEADING.sub(replace, body), toc


def load_page(path: Path) -> Page:
    source = path.read_text("utf-8")
    header = _HEADER.match(source)
    if not header:
        raise SystemExit(f"{path} is missing its header comment")
    meta = dict(
        (key.strip(), value.strip())
        for key, _, value in (
            line.partition(":") for line in header.group("meta").strip().splitlines()
        )
    )
    layout = meta.get("layout", "docs")
    body = render_fences(source[header.end() :].replace("{{version}}", VERSION))
    toc: list[tuple[int, str, str]] = []
    if layout != "landing":
        body, toc = add_heading_ids(body)
    return Page(meta["slug"], meta["title"], meta["description"], layout, body, toc)


# API reference


@dataclass
class ApiItem:
    name: str
    kind: str
    signature: str
    doc: str
    bases: list[str] = field(default_factory=list)
    members: list[tuple[str, str, str]] = field(default_factory=list)
    fields: list[tuple[str, str]] = field(default_factory=list)


API_GROUPS: list[tuple[str, str, list[str]]] = [
    ("Client", "The objects your application talks to.", ["MailingKit", "SyncMailingKit"]),
    (
        "Messages",
        "The provider-independent message model.",
        ["EmailMessage", "Address", "Attachment", "Limits"],
    ),
    (
        "Templates",
        "File-based templates with typed data.",
        ["Template", "TemplateRenderer", "RenderedTemplate"],
    ),
    (
        "Providers",
        "The adapter contract and the built-in adapters (import them from mailingkit.providers).",
        [
            "EmailProvider",
            "ProviderResponse",
            "register_provider",
            "ConsoleProvider",
            "FileProvider",
            "MemoryProvider",
            "SmtpProvider",
            "ResendProvider",
        ],
    ),
    (
        "Results and reliability",
        "What a send returns, events for hooks, retries and idempotency.",
        [
            "SendResult",
            "MailEvent",
            "RetryPolicy",
            "IdempotencyStore",
            "InMemoryIdempotencyStore",
            "Secret",
        ],
    ),
    (
        "Errors",
        "Every error MailingKit raises. Provider errors carry retryable, provider and status_code.",
        [
            "MailingKitError",
            "ConfigurationError",
            "ValidationError",
            "InvalidAddressError",
            "MessageTooLargeError",
            "TemplateError",
            "TemplateNotFoundError",
            "TemplateDataError",
            "TemplateRenderError",
            "ProviderError",
            "AuthenticationError",
            "RateLimitError",
            "RecipientRejectedError",
            "TemporaryProviderError",
            "PermanentProviderError",
        ],
    ),
]


def _definitions() -> dict[str, ast.AST]:
    found: dict[str, ast.AST] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if "contrib" in path.parts:
            continue
        for node in ast.parse(path.read_text("utf-8")).body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                found.setdefault(node.name, node)
    return found


def _param(arg: ast.arg, default: ast.expr | None, prefix: str = "") -> str:
    text = prefix + arg.arg
    if arg.annotation is not None:
        text += f": {ast.unparse(arg.annotation)}"
    if default is not None:
        text += (
            f" = {ast.unparse(default)}"
            if arg.annotation is not None
            else f"={ast.unparse(default)}"
        )
    return text


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef, skip_self: bool) -> str:
    """Render parameters like Black would: one line when short, one per line when long."""
    args = node.args
    positional = args.posonlyargs + args.args
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults)) + list(
        args.defaults
    )
    params: list[str] = []
    for index, (arg, default) in enumerate(zip(positional, defaults, strict=True)):
        if index == 0 and skip_self:
            continue
        params.append(_param(arg, default))
        if args.posonlyargs and arg is args.posonlyargs[-1]:
            params.append("/")
    if args.vararg is not None:
        params.append(_param(args.vararg, None, "*"))
    elif args.kwonlyargs:
        params.append("*")
    params.extend(
        _param(arg, default) for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
    )
    if args.kwarg is not None:
        params.append(_param(args.kwarg, None, "**"))
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    one_line = f"({', '.join(params)}){returns}"
    if len(one_line) <= 72:
        return one_line
    return "(\n" + "".join(f"    {p},\n" for p in params) + f"){returns}"


def api_item(name: str, node: ast.AST) -> ApiItem:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        return ApiItem(
            name,
            "function",
            f"{prefix} {name}{_signature(node, False)}",
            ast.get_docstring(node) or "",
        )
    assert isinstance(node, ast.ClassDef)
    bases = [ast.unparse(b) for b in node.bases]
    item = ApiItem(name, "class", "", ast.get_docstring(node) or "", bases=bases)
    for child in node.body:
        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            annotation = ast.unparse(child.annotation)
            if child.target.id.startswith("_") or annotation.startswith("ClassVar"):
                continue
            default = f" = {ast.unparse(child.value)}" if child.value is not None else ""
            if default.startswith(" = field("):
                default = ""
            item.fields.append((child.target.id, f"{annotation}{default}"))
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if child.name == "__init__":
                item.signature = f"{name}{_signature(child, True)}".replace(" -> None", "")
                continue
            if child.name.startswith("_"):
                continue
            decorators = {ast.unparse(d) for d in child.decorator_list}
            prefix = "async " if isinstance(child, ast.AsyncFunctionDef) else ""
            if "property" in decorators:
                returns = f": {ast.unparse(child.returns)}" if child.returns else ""
                item.members.append(
                    (child.name, f"{child.name}{returns}", ast.get_docstring(child) or "")
                )
            else:
                skip = "staticmethod" not in decorators
                item.members.append(
                    (
                        child.name,
                        f"{prefix}{child.name}{_signature(child, skip)}",
                        ast.get_docstring(child) or "",
                    )
                )
    if not item.signature and item.fields:
        item.signature = name + "(" + ", ".join(f"{n}: {t}" for n, t in item.fields) + ")"
    return item


_ROLE = re.compile(r":(?:class|meth|func|attr|mod):`~?([^`]+)`")


def render_doc(doc: str) -> str:
    """Render a docstring: paragraphs, ``code``, roles and ``::`` code blocks."""
    if not doc:
        return ""
    lines = doc.splitlines()
    parts: list[str] = []
    paragraph: list[str] = []
    i = 0
    want_code = False

    def flush() -> None:
        nonlocal want_code
        if paragraph and paragraph[0].lstrip().startswith(">>>"):
            # A doctest: show it as code, exactly as written.
            parts.append(code_block("python", "\n".join(line.strip() for line in paragraph)))
            paragraph.clear()
            return
        if paragraph:
            text = " ".join(line.strip() for line in paragraph)
            want_code = text.endswith("::")
            text = text[:-1] if text.endswith("::") else text
            text = html.escape(text, quote=False)
            text = re.sub(r"``(.+?)``", r"<code>\1</code>", text)
            text = _ROLE.sub(r"<code>\1</code>", text)
            if text.strip() not in {"", ":"}:
                parts.append(f"<p>{text}</p>")
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        if want_code and line.strip() and line.startswith((" ", "\t")):
            block: list[str] = []
            while i < len(lines) and (not lines[i].strip() or lines[i].startswith((" ", "\t"))):
                block.append(lines[i])
                i += 1
            code = "\n".join(block).strip("\n")
            indent = min(len(ln) - len(ln.lstrip()) for ln in code.splitlines() if ln.strip())
            code = "\n".join(ln[indent:] for ln in code.splitlines())
            parts.append(code_block("python", code))
            want_code = False
            continue
        if not line.strip():
            flush()
        else:
            paragraph.append(line)
        i += 1
    flush()
    return "\n".join(parts)


def build_api_page() -> Page:
    definitions = _definitions()
    sections: list[str] = []
    toc: list[tuple[int, str, str]] = []
    for group, intro, names in API_GROUPS:
        anchor = slugify(group)
        toc.append((2, anchor, group))
        cards: list[str] = []
        for name in names:
            node = definitions.get(name)
            if node is None:
                raise SystemExit(f"API reference: {name} not found in the package source")
            item = api_item(name, node)
            toc.append((3, name.lower(), name))
            signature = item.signature or f"class {name}"
            base_note = ""
            if item.bases and item.bases != ["ABC"] and not item.fields:
                bases = ", ".join(f"<code>{html.escape(b)}</code>" for b in item.bases)
                base_note = f'<p class="api-bases">Subclass of {bases}</p>'
            members = ""
            if item.fields:
                rows = "".join(
                    f"<tr><td><code>{html.escape(n)}</code></td>"
                    f"<td><code>{html.escape(t)}</code></td></tr>"
                    for n, t in item.fields
                )
                members += (
                    '<table class="api-fields"><thead><tr><th>Field</th><th>Type</th></tr>'
                    f"</thead><tbody>{rows}</tbody></table>"
                )
            for _member, member_signature, member_doc in item.members:
                members += (
                    '<div class="api-member"><pre class="api-signature">'
                    f"<code>{highlight_python(member_signature)}</code></pre>"
                    f"{render_doc(member_doc)}</div>"
                )
            cards.append(
                f'<section class="api-item" id="{name.lower()}">'
                f'<h3><a class="anchor" href="#{name.lower()}" aria-hidden="true">#</a>'
                f"<code>{name}</code>"
                f'<span class="api-kind">{item.kind}</span></h3>'
                f'<pre class="api-signature"><code>{highlight_python(signature)}</code></pre>'
                f"{base_note}{render_doc(item.doc)}{members}</section>"
            )
        sections.append(
            f'<h2 id="{anchor}"><a class="anchor" href="#{anchor}" aria-hidden="true">#</a>'
            f"{group}</h2>"
            f'<p class="lead-small">{html.escape(intro)}</p>' + "".join(cards)
        )
    body = (
        '<p class="eyebrow">Reference</p><h1>API reference</h1>'
        f'<p class="lead">Generated from the <code>mailingkit</code> {VERSION} source. '
        "Everything here is importable from <code>mailingkit</code>, "
        "except the built-in providers, which live in "
        "<code>mailingkit.providers</code>.</p>" + "".join(sections)
    )
    return Page(
        "docs/api",
        "API reference",
        "Every public class, function and error in MailingKit.",
        "docs",
        body,
        toc,
    )


# Rendering

CURRENT = ' aria-current="page"'


def nav_html(current: str) -> str:
    groups = []
    for group, links in DOCS_NAV:
        items = "".join(
            f'<li><a href="/{slug}/"{CURRENT if slug == current else ""}>{label}</a></li>'
            for slug, label in links
        )
        groups.append(f'<div class="nav-group"><p>{group}</p><ul>{items}</ul></div>')
    return "".join(groups)


def _toc_label(text: str) -> str:
    """Plain heading text, keeping a workshop step number as its own element."""
    step = re.match(r'\s*<span class="step">(\d+)</span>', text)
    plain = re.sub(r"<[^>]+>", "", text[step.end() :] if step else text).strip()
    label = html.escape(html.unescape(plain), quote=False)
    return f'<span class="toc-num">{step.group(1)}</span>{label}' if step else label


def toc_html(toc: list[tuple[int, str, str]]) -> str:
    if not toc:
        return ""
    items = "".join(
        f'<li class="toc-{level}"><a href="#{anchor}">{_toc_label(text)}</a></li>'
        for level, anchor, text in toc
    )
    return f'<nav class="toc" aria-label="On this page"><p>On this page</p><ul>{items}</ul></nav>'


def pager_html(current: str) -> str:
    order = [slug for _, links in DOCS_NAV for slug, _ in links]
    labels = {slug: label for _, links in DOCS_NAV for slug, label in links}
    if current not in order:
        return ""
    i = order.index(current)
    prev_link = (
        f'<a class="pager-prev" href="/{order[i - 1]}/">'
        f"<span>Previous</span>{labels[order[i - 1]]}</a>"
        if i > 0
        else "<span></span>"
    )
    next_link = (
        f'<a class="pager-next" href="/{order[i + 1]}/"><span>Next</span>{labels[order[i + 1]]}</a>'
        if i + 1 < len(order)
        else "<span></span>"
    )
    return f'<nav class="pager" aria-label="Pages">{prev_link}{next_link}</nav>'


def render(page: Page, template: Template) -> str:
    if page.layout == "docs":
        main = (
            '<div class="docs-layout">'
            '<aside class="sidebar"><details class="sidebar-menu" open>'
            f"<summary>Documentation</summary>{nav_html(page.slug)}</details></aside>"
            f'<article class="prose">{page.body}{pager_html(page.slug)}</article>'
            f'<aside class="toc-column">{toc_html([t for t in page.toc if t[0] == 2])}</aside>'
            "</div>"
        )
    elif page.layout == "workshop":
        main = (
            '<div class="docs-layout workshop-layout">'
            '<aside class="sidebar"><details class="sidebar-menu" open><summary>Steps</summary>'
            f"{toc_html([t for t in page.toc if t[0] == 2])}</details></aside>"
            f'<article class="prose">{page.body}</article>'
            "</div>"
        )
    else:
        main = page.body
    path = "/" if page.slug == "" else "/404.html" if page.slug == "404" else f"/{page.slug}/"
    title = (
        "MailingKit: transactional email for Python"
        if page.slug == ""
        else f"{page.title} | MailingKit"
    )
    section = page.slug.split("/")[0] if page.slug else "home"
    return template.substitute(
        title=html.escape(title),
        description=html.escape(page.description),
        canonical=f"{BASE_URL}{path}",
        main=main,
        version=VERSION,
        repo=REPO_URL,
        nav_docs=CURRENT if section == "docs" and page.slug != "docs/api" else "",
        nav_api=CURRENT if page.slug == "docs/api" else "",
        nav_workshop=CURRENT if section == "workshop" else "",
    )


def build() -> None:
    template = Template((SITE / "template.html").read_text("utf-8"))
    # Empty the folder rather than deleting it, so a dev server serving it keeps working.
    OUT.mkdir(exist_ok=True)
    for child in OUT.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    shutil.copytree(SITE / "assets", OUT / "assets")

    pages = [load_page(path) for path in sorted((SITE / "pages").glob("*.html"))]
    pages.append(build_api_page())
    known = {slug for _, links in DOCS_NAV for slug, _ in links}
    missing = known - {p.slug for p in pages}
    if missing:
        raise SystemExit(f"Navigation links to pages that do not exist: {sorted(missing)}")

    for page in pages:
        target = OUT / page.slug / "index.html" if page.slug else OUT / "index.html"
        if page.slug == "404":
            target = OUT / "404.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(page, template), "utf-8", newline="\n")

    urls = "".join(
        f"<url><loc>{BASE_URL}/{p.slug + '/' if p.slug else ''}</loc></url>"
        for p in pages
        if p.slug != "404"
    )
    (OUT / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n',
        "utf-8",
    )
    (OUT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n", "utf-8"
    )
    print(f"Built {len(pages)} pages into {OUT.relative_to(ROOT)}/ (mailingkit {VERSION})")


if __name__ == "__main__":
    build()
