"""File-based email templates with typed data.

Each template is a folder holding a subject and at least one body::

    templates/
        _layouts/base.html          shared layout, used with {% extends %}
        welcome/
            subject.txt             required
            body.html               html body (autoescaped)
            body.txt                optional; generated from body.html when missing

Templates are rendered by Jinja2 in a sandbox, with HTML autoescaping on and undefined
variables treated as errors, so a missing value fails loudly instead of sending a broken email.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

import jinja2
from jinja2.sandbox import SandboxedEnvironment

from mailingkit._html_text import html_to_text
from mailingkit.errors import (
    TemplateDataError,
    TemplateNotFoundError,
    TemplateRenderError,
)

__all__ = ["RenderedTemplate", "Template", "TemplateRenderer"]

T = TypeVar("T")

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*$")


@dataclass(frozen=True, slots=True)
class Template(Generic[T]):
    """A named template, optionally bound to a data model.

    The model can be a dataclass or a Pydantic model. When it is set, MailingKit checks the
    data against it before rendering::

        @dataclass
        class WelcomeData:
            name: str
            login_url: str

        WELCOME = Template("welcome", WelcomeData)
    """

    name: str
    model: type[T] | None = None

    def __post_init__(self) -> None:
        if not _NAME.match(self.name) or ".." in self.name.split("/"):
            raise ValueError(f"Invalid template name: {self.name!r}")


@dataclass(frozen=True, slots=True)
class RenderedTemplate:
    """The output of rendering a template: what the recipient will see."""

    subject: str
    html: str | None
    text: str | None


def _is_pydantic_model(model: type[Any]) -> bool:
    return hasattr(model, "model_validate") and hasattr(model, "model_fields")


def _fields_of(instance: object) -> dict[str, Any]:
    """Shallow field dict, so nested objects keep their attributes inside the template."""
    if dataclasses.is_dataclass(instance) and not isinstance(instance, type):
        return {f.name: getattr(instance, f.name) for f in dataclasses.fields(instance)}
    if _is_pydantic_model(type(instance)):
        return {name: getattr(instance, name) for name in type(instance).model_fields}  # type: ignore[attr-defined]
    raise TemplateDataError(
        f"Template data must be a mapping, a dataclass or a Pydantic model, "
        f"got {type(instance).__name__}"
    )


def _build_model(template: Template[Any], model: type[Any], data: Mapping[str, Any]) -> Any:
    if dataclasses.is_dataclass(model):
        init_fields = [f for f in dataclasses.fields(model) if f.init]
        required = {
            f.name
            for f in init_fields
            if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
        }
        missing = sorted(required - data.keys())
        unknown = sorted(data.keys() - {f.name for f in init_fields})
        problems = []
        if missing:
            problems.append(f"missing required fields: {', '.join(missing)}")
        if unknown:
            problems.append(f"unknown fields: {', '.join(unknown)}")
        if problems:
            raise TemplateDataError(
                f"Template {template.name!r} data is invalid: {'; '.join(problems)}"
            )
    try:
        if _is_pydantic_model(model):
            return model.model_validate(dict(data))
        return model(**data)
    except (TypeError, ValueError) as exc:
        raise TemplateDataError(f"Template {template.name!r} data is invalid: {exc}") from exc


def template_context(template: Template[Any], data: object | None) -> dict[str, Any]:
    """Check ``data`` against the template's model and return the render context."""
    model = template.model
    if data is None:
        data = {}
    if model is not None and not isinstance(data, model):
        if not isinstance(data, Mapping):
            raise TemplateDataError(
                f"Template {template.name!r} expects {model.__name__} or a mapping, "
                f"got {type(data).__name__}"
            )
        data = _build_model(template, model, data)
    if isinstance(data, Mapping):
        return dict(data)
    return _fields_of(data)


class TemplateRenderer:
    """Loads templates from one or more directories and renders them.

    Pass ``environment`` to bring your own configured Jinja2 environment (custom filters,
    a different loader). Its autoescape and undefined settings are then your responsibility.
    """

    def __init__(
        self,
        directory: str | Path | Sequence[str | Path] | None = None,
        *,
        environment: jinja2.Environment | None = None,
        globals: Mapping[str, Any] | None = None,
    ) -> None:
        if environment is None:
            if directory is None:
                raise ValueError("Pass a template directory or a Jinja2 environment")
            directories = [directory] if isinstance(directory, (str, Path)) else list(directory)
            environment = SandboxedEnvironment(
                loader=jinja2.FileSystemLoader([str(d) for d in directories]),
                autoescape=jinja2.select_autoescape(
                    enabled_extensions=("html", "htm", "xml"), default_for_string=False
                ),
                undefined=jinja2.StrictUndefined,
            )
        if globals:
            environment.globals.update(globals)
        self.environment = environment

    def _load(self, path: str) -> jinja2.Template | None:
        try:
            return self.environment.get_template(path)
        except jinja2.TemplateNotFound:
            return None
        except jinja2.TemplateSyntaxError as exc:
            raise TemplateRenderError(
                f"Syntax error in {path} line {exc.lineno}: {exc.message}"
            ) from exc

    def _render_part(self, name: str, part: jinja2.Template, context: Mapping[str, Any]) -> str:
        try:
            return part.render(context)
        except jinja2.UndefinedError as exc:
            raise TemplateDataError(f"Template {name!r} is missing data: {exc.message}") from exc
        except jinja2.TemplateError as exc:
            raise TemplateRenderError(f"Template {name!r} failed to render: {exc}") from exc

    def exists(self, name: str) -> bool:
        return self._load(f"{name}/subject.txt") is not None

    def render(self, template: Template[Any] | str, data: object | None = None) -> RenderedTemplate:
        """Render a template. Raises a :class:`TemplateError` subclass on any problem."""
        if isinstance(template, str):
            template = Template(template)
        name = template.name
        context = template_context(template, data)

        subject_part = self._load(f"{name}/subject.txt")
        html_part = self._load(f"{name}/body.html")
        text_part = self._load(f"{name}/body.txt")
        if subject_part is None:
            raise TemplateNotFoundError(f"Template {name!r} not found: expected {name}/subject.txt")
        if html_part is None and text_part is None:
            raise TemplateNotFoundError(
                f"Template {name!r} has no body: expected {name}/body.html or {name}/body.txt"
            )

        # Collapsing whitespace also removes any line break that came in through the data.
        subject = " ".join(self._render_part(name, subject_part, context).split())
        html = self._render_part(name, html_part, context) if html_part else None
        text = self._render_part(name, text_part, context) if text_part else None
        if text is None and html is not None:
            text = html_to_text(html)
        return RenderedTemplate(subject=subject, html=html, text=text)
