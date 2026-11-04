"""The scripts in fsmart/static look up markup by id and class; a restyle that renames one breaks the app silently."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / 'fsmart' / 'static'
# Looked up with an existence check (`if ($('runtime-hint'))`), so markup may omit them.
OPTIONAL_IDS = {'runtime-hint'}


def _sources():
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    scripts = '\n'.join(path.read_text(encoding='utf-8') for path in sorted(STATIC.glob('*.js')))
    return html, scripts


def _selectors(scripts):
    return re.findall(r"(?:querySelector(?:All)?|closest)\('([^']+)'\)", scripts)


def test_every_id_the_scripts_use_exists():
    html, scripts = _sources()
    defined = set(re.findall(r'\bid="([^"]+)"', html))
    defined |= set(re.findall(r'\bid="([^"$]+)"', scripts))  # markup injected from template strings
    defined |= set(re.findall(r"\.id\s*=\s*'([^']+)'", scripts))
    used = set(re.findall(r"(?:\$|getElementById)\('([\w-]+)'\)", scripts))
    used |= {name for selector in _selectors(scripts) for name in re.findall(r'#([\w-]+)', selector)}
    assert sorted(used - defined - OPTIONAL_IDS) == []


def test_every_class_the_scripts_select_exists():
    html, scripts = _sources()
    defined = {name for value in re.findall(r'\bclass="([^"]+)"', html) for name in value.split()}
    defined |= {name for value in re.findall(r'\bclass="([^"$]+)"', scripts) for name in value.split()}
    defined |= {name for value in re.findall(r"\bel\('\w+',\s*[`']([^`'$]+)", scripts) for name in value.split()}
    used = {name for selector in _selectors(scripts) for name in re.findall(r'\.([a-zA-Z][\w-]*)', selector)}
    assert sorted(used - defined) == []


def test_ids_in_page_markup_are_unique():
    html, _ = _sources()
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert sorted({name for name in ids if ids.count(name) > 1}) == []


def test_linked_assets_exist_and_tokens_load_first():
    html, _ = _sources()
    sheets = re.findall(r'<link rel="stylesheet" href="/static/([^"?]+)', html)
    scripts = re.findall(r'<script src="/static/([^"?]+)', html)
    assert sheets[:2] == ['fonts.css', 'theme.css']
    assert [name for name in sheets + scripts if not (STATIC / name).is_file()] == []
