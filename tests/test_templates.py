from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import BaseModel

from mailingkit import (
    Template,
    TemplateDataError,
    TemplateNotFoundError,
    TemplateRenderer,
    TemplateRenderError,
)

TEMPLATES = Path(__file__).parent / "fixtures" / "templates"


@dataclass
class WelcomeData:
    name: str
    login_url: str
    product: str = "Acme"


class ReceiptData(BaseModel):
    number: int
    total: str


WELCOME = Template("welcome", WelcomeData)
RECEIPT = Template("receipt", ReceiptData)


@pytest.fixture
def renderer() -> TemplateRenderer:
    return TemplateRenderer(TEMPLATES)


def test_render_fills_subject_html_and_generated_text(renderer: TemplateRenderer) -> None:
    rendered = renderer.render(WELCOME, WelcomeData(name="Ada", login_url="https://acme.test/in"))

    assert rendered.subject == "Welcome to Acme, Ada"
    assert "<h1>Hi Ada</h1>" in (rendered.html or "")
    assert "Sign in (https://acme.test/in)" in (rendered.text or "")


def test_render_builds_dataclass_from_mapping(renderer: TemplateRenderer) -> None:
    rendered = renderer.render(WELCOME, {"name": "Ada", "login_url": "https://acme.test"})

    assert rendered.subject == "Welcome to Acme, Ada"


def test_render_reports_every_missing_dataclass_field(renderer: TemplateRenderer) -> None:
    with pytest.raises(TemplateDataError, match="missing required fields: login_url, name"):
        renderer.render(WELCOME, {})


def test_render_reports_unknown_dataclass_fields(renderer: TemplateRenderer) -> None:
    with pytest.raises(TemplateDataError, match="unknown fields: nmae"):
        renderer.render(WELCOME, {"name": "Ada", "login_url": "x", "nmae": "typo"})


def test_render_validates_mapping_with_pydantic_model(renderer: TemplateRenderer) -> None:
    with pytest.raises(TemplateDataError, match="number"):
        renderer.render(RECEIPT, {"number": "not-a-number", "total": "$5"})


def test_render_uses_hand_written_text_body_when_present(renderer: TemplateRenderer) -> None:
    rendered = renderer.render(RECEIPT, ReceiptData(number=7, total="$5"))

    assert rendered.text == "Total: $5"


def test_render_rejects_data_of_the_wrong_type(renderer: TemplateRenderer) -> None:
    with pytest.raises(TemplateDataError, match="expects WelcomeData"):
        renderer.render(WELCOME, ReceiptData(number=1, total="$1"))


def test_render_escapes_html_in_data(renderer: TemplateRenderer) -> None:
    data = WelcomeData(name="<script>alert(1)</script>", login_url="https://acme.test")

    rendered = renderer.render(WELCOME, data)

    assert "<script>" not in (rendered.html or "")
    assert "&lt;script&gt;" in (rendered.html or "")


def test_render_does_not_escape_plain_text_bodies(renderer: TemplateRenderer) -> None:
    rendered = renderer.render("plain", {"name": "Tom & Jerry"})

    assert rendered.text == "Hello Tom & Jerry"


def test_render_collapses_line_breaks_from_data_in_subject(renderer: TemplateRenderer) -> None:
    rendered = renderer.render("plain", {"name": "Ada\r\nBcc: victim@example.com"})

    assert rendered.subject == "Plain Ada Bcc: victim@example.com"


def test_render_fails_on_undefined_variable_for_untyped_template(
    renderer: TemplateRenderer,
) -> None:
    with pytest.raises(TemplateDataError, match="name"):
        renderer.render("plain", {})


def test_render_raises_not_found_for_unknown_template(renderer: TemplateRenderer) -> None:
    with pytest.raises(TemplateNotFoundError, match="missing-template"):
        renderer.render("missing-template")


def test_render_raises_not_found_when_template_has_no_body(renderer: TemplateRenderer) -> None:
    with pytest.raises(TemplateNotFoundError, match="no body"):
        renderer.render("no-body")


def test_render_wraps_syntax_errors(renderer: TemplateRenderer) -> None:
    with pytest.raises(TemplateRenderError, match="Syntax error"):
        renderer.render("broken")


@pytest.mark.parametrize("name", ["../secrets", "welcome/../../etc", "/abs", ""])
def test_template_rejects_path_traversal_names(name: str) -> None:
    with pytest.raises(ValueError, match="Invalid template name"):
        Template(name)


def test_render_blocks_unsafe_attribute_access_in_sandbox(tmp_path) -> None:  # type: ignore[no-untyped-def]
    folder = tmp_path / "evil"
    folder.mkdir()
    (folder / "subject.txt").write_text("x")
    (folder / "body.txt").write_text("{{ ''.__class__.__mro__ }}")

    with pytest.raises(TemplateRenderError):
        TemplateRenderer(tmp_path).render("evil")
