"""Tests for build.py — the Space blog static site generator."""

import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

# Add project root so `import build` works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal Space blog project skeleton for integration tests."""
    (tmp_path / "posts").mkdir()
    (tmp_path / "pages").mkdir()
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "style.css").write_text("/* css */")
    (tmp_path / "template.html").write_text(
        '<!DOCTYPE html><html><head><base href="{{base}}">'
        '<title>{{title}}</title>'
        '<meta name="description" content="{{description}}">'
        '</head><body>{{body}}</body></html>'
    )
    return tmp_path


def _write_post(posts_dir: Path, slug: str, title: str, date: str,
                body: str = "Hello world.", tags=None, draft: bool = False):
    """Write a markdown post file with YAML frontmatter."""
    lines = ["---", f"title: {title}", f"date: {date}"]
    if tags:
        lines.append(f"tags: {tags}")
    if draft:
        lines.append("draft: true")
    lines.extend(["---", "", body])
    (posts_dir / f"{slug}.md").write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------

class TestParseFrontmatter:

    def test_no_frontmatter(self):
        meta, body = build.parse_frontmatter("Just plain markdown.")
        assert meta == {}
        assert body == "Just plain markdown."

    def test_basic_frontmatter(self):
        text = "---\ntitle: Hello\ndate: 2026-05-01\n---\n\nBody here."
        meta, body = build.parse_frontmatter(text)
        assert meta["title"] == "Hello"
        # YAML auto-parses dates to datetime.date objects
        assert meta["date"].strftime("%Y-%m-%d") == "2026-05-01"
        assert body == "Body here."

    def test_tags_as_list(self):
        text = "---\ntags:\n  - planning\n  - systems\n---\n\nPost."
        meta, body = build.parse_frontmatter(text)
        assert meta["tags"] == ["planning", "systems"]

    def test_tags_as_comma_string(self):
        text = "---\ntags: planning, systems\n---\n\nPost."
        meta, body = build.parse_frontmatter(text)
        assert meta["tags"] == "planning, systems"

    def test_draft_true(self):
        text = "---\ndraft: true\n---\n\nSecret."
        meta, body = build.parse_frontmatter(text)
        assert meta["draft"] is True

    def test_missing_closing_fence(self):
        text = "---\ntitle: No close\nNo body"
        meta, body = build.parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_empty_frontmatter(self):
        text = "---\n---\n\nBody only."
        meta, body = build.parse_frontmatter(text)
        assert meta == {}
        assert body == "Body only."

    def test_invalid_yaml_fallback(self):
        text = "---\ntitle: Bad @ yaml\n---\n\nFallback."
        meta, body = build.parse_frontmatter(text)
        assert "title" in meta

    def test_non_dict_yaml(self):
        text = "---\njust a string\n---\n\nBody."
        meta, body = build.parse_frontmatter(text)
        assert meta == {}


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------

class TestRenderMarkdown:

    def test_basic_paragraph(self):
        result = build.render_markdown("Hello world.")
        assert "<p>Hello world.</p>" in result

    def test_headings(self):
        result = build.render_markdown("# Title\n\n## Subtitle")
        # Pandoc adds id attributes to headings
        assert "<h1" in result
        assert "Title" in result
        assert "<h2" in result
        assert "Subtitle" in result

    def test_code_block(self):
        result = build.render_markdown("```python\nprint('hi')\n```")
        assert "<code" in result

    def test_links(self):
        result = build.render_markdown("[example](https://example.com)")
        assert 'href="https://example.com"' in result

    def test_smart_typography(self):
        result = build.render_markdown("This is --- an em dash.")
        # --- produces em dash with pandoc smart extension
        assert "—" in result


# ---------------------------------------------------------------------------
# extract_description
# ---------------------------------------------------------------------------

class TestExtractDescription:

    def test_plain_paragraph(self):
        html = "<p>This is a description.</p>"
        assert build.extract_description(html) == "This is a description."

    def test_truncation(self):
        long_text = "A" * 200
        html = f"<p>{long_text}</p>"
        result = build.extract_description(html, max_len=160)
        assert len(result) <= 160
        assert result.endswith("…")

    def test_no_paragraph(self):
        assert build.extract_description("<div>no p</div>") == ""

    def test_strips_inner_tags(self):
        html = "<p>This has <strong>bold</strong> text.</p>"
        assert build.extract_description(html) == "This has bold text."


# ---------------------------------------------------------------------------
# extract_excerpt
# ---------------------------------------------------------------------------

class TestExtractExcerpt:

    def test_returns_first_paragraph(self):
        html = "<p>First</p><p>Second</p>"
        assert build.extract_excerpt(html) == "<p>First</p>"

    def test_no_paragraph(self):
        assert build.extract_excerpt("<div>nothing</div>") == ""


# ---------------------------------------------------------------------------
# calc_reading_time
# ---------------------------------------------------------------------------

class TestCalcReadingTime:

    def test_short_text(self):
        assert build.calc_reading_time("<p>Hi</p>") == 1

    def test_longer_text(self):
        words = " ".join(["word"] * 400)
        html = f"<p>{words}</p>"
        assert build.calc_reading_time(html) == 2


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------

class TestSlugify:

    def test_lowercase(self):
        assert build.slugify("Planning") == "planning"

    def test_spaces_to_dashes(self):
        assert build.slugify("Machine Learning") == "machine-learning"

    def test_special_chars(self):
        assert build.slugify("C++ & Rust!") == "c-rust"

    def test_already_slug(self):
        assert build.slugify("engineering") == "engineering"


# ---------------------------------------------------------------------------
# reading_time_label
# ---------------------------------------------------------------------------

class TestReadingTimeLabel:

    def test_format(self):
        assert build.reading_time_label(3) == "3 min read"


# ---------------------------------------------------------------------------
# make_json_ld
# ---------------------------------------------------------------------------

class TestMakeJsonLd:

    def test_basic_structure(self):
        result = build.make_json_ld("Title", "Desc", "https://example.com", "2026-05-01")
        assert '"@type": "BlogPosting"' in result
        assert '"headline": "Title"' in result
        assert '"datePublished": "2026-05-01"' in result
        assert '<script type="application/ld+json">' in result

    def test_no_date(self):
        result = build.make_json_ld("Title", "Desc", "https://example.com")
        assert "datePublished" not in result


# ---------------------------------------------------------------------------
# escape_xml
# ---------------------------------------------------------------------------

class TestEscapeXml:

    def test_ampersand(self):
        assert build.escape_xml("a & b") == "a &amp; b"

    def test_angle_brackets(self):
        assert build.escape_xml("<p>") == "&lt;p&gt;"

    def test_quotes(self):
        assert build.escape_xml('say "hi"') == "say &quot;hi&quot;"
        assert build.escape_xml("it's") == "it&apos;s"

    def test_combined(self):
        assert build.escape_xml('<a href="x&y">it\'s</a>') == (
            "&lt;a href=&quot;x&amp;y&quot;&gt;it&apos;s&lt;/a&gt;"
        )


# ---------------------------------------------------------------------------
# format_date
# ---------------------------------------------------------------------------

class TestFormatDate:

    def test_valid_date(self):
        result = build.format_date("2026-05-01")
        assert "2026" in result
        assert "May" in result

    def test_invalid_date_passthrough(self):
        assert build.format_date("not-a-date") == "not-a-date"

    def test_none_returns_empty(self):
        result = build.format_date(None)
        assert result == ""


# ---------------------------------------------------------------------------
# inject_code_labels
# ---------------------------------------------------------------------------

class TestInjectCodeLabels:

    def test_adds_data_lang(self):
        html = '<pre class="sourceCode python"><code>x = 1</code></pre>'
        result = build.inject_code_labels(html)
        assert 'data-lang="python"' in result
        assert 'class="sourceCode' in result

    def test_no_code_blocks(self):
        html = "<p>No code here.</p>"
        assert build.inject_code_labels(html) == html


# ---------------------------------------------------------------------------
# collect_posts
# ---------------------------------------------------------------------------

class TestCollectPosts:

    def test_excludes_drafts(self, tmp_project, monkeypatch):
        monkeypatch.setattr(build, "POSTS_DIR", tmp_project / "posts")
        _write_post(tmp_project / "posts", "published", "Published", "2026-05-01")
        _write_post(tmp_project / "posts", "draft-post", "Draft", "2026-05-02", draft=True)
        posts, draft_count = build.collect_posts()
        assert len(posts) == 1
        assert posts[0][0] == "published"
        assert draft_count == 1

    def test_draft_string_values(self, tmp_project, monkeypatch):
        monkeypatch.setattr(build, "POSTS_DIR", tmp_project / "posts")
        for slug, val in [("d1", "true"), ("d2", "yes"), ("d3", "1")]:
            text = f"---\ntitle: D{slug}\ndate: 2026-05-01\ndraft: {val}\n---\n\nBody."
            (tmp_project / "posts" / f"{slug}.md").write_text(text)
        posts, draft_count = build.collect_posts()
        assert len(posts) == 0
        assert draft_count == 3

    def test_sorts_by_date_desc(self, tmp_project, monkeypatch):
        monkeypatch.setattr(build, "POSTS_DIR", tmp_project / "posts")
        _write_post(tmp_project / "posts", "older", "Older", "2026-04-01")
        _write_post(tmp_project / "posts", "newer", "Newer", "2026-05-01")
        posts, _ = build.collect_posts()
        assert posts[0][0] == "newer"
        assert posts[1][0] == "older"

    def test_tags_collected(self, tmp_project, monkeypatch):
        monkeypatch.setattr(build, "POSTS_DIR", tmp_project / "posts")
        _write_post(tmp_project / "posts", "tagged", "Tagged", "2026-05-01",
                    tags="planning, systems")
        posts, _ = build.collect_posts()
        assert "planning" in posts[0][4]
        assert "systems" in posts[0][4]

    def test_empty_posts_dir(self, monkeypatch):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            empty = Path(d) / "posts"
            empty.mkdir()
            monkeypatch.setattr(build, "POSTS_DIR", empty)
            posts, draft_count = build.collect_posts()
            assert posts == []
            assert draft_count == 0


# ---------------------------------------------------------------------------
# build_post_list_html
# ---------------------------------------------------------------------------

class TestBuildPostListHtml:

    def test_basic_list(self):
        posts = [
            ("my-post", {"title": "My Post", "date": "2026-05-01"}, "<p>Excerpt</p>", 1, []),
        ]
        html = build.build_post_list_html(posts)
        assert "My Post" in html
        assert "2026-05-01" in html
        assert "1 min read" in html
        assert 'href="posts/my-post.html"' in html

    def test_tags_in_list(self):
        posts = [
            ("tagged", {"title": "T", "date": "2026-05-01"}, "<p>E</p>", 1, ["planning"]),
        ]
        html = build.build_post_list_html(posts)
        assert 'href="tags/planning.html"' in html
        assert "tag-pill" in html

    def test_empty_posts(self):
        assert build.build_post_list_html([]) == ""


# ---------------------------------------------------------------------------
# build_tag_map
# ---------------------------------------------------------------------------

class TestBuildTagMap:

    def test_single_tag(self):
        posts = [
            ("p1", {"title": "T"}, "<p>Body</p>", 1, ["planning"]),
        ]
        tm = build.build_tag_map(posts)
        assert "planning" in tm
        assert len(tm["planning"]) == 1

    def test_multiple_tags_across_posts(self):
        posts = [
            ("p1", {"title": "T1"}, "<p>B1</p>", 1, ["planning", "systems"]),
            ("p2", {"title": "T2"}, "<p>B2</p>", 1, ["planning"]),
        ]
        tm = build.build_tag_map(posts)
        assert len(tm["planning"]) == 2
        assert len(tm["systems"]) == 1

    def test_no_tags(self):
        tm = build.build_tag_map([("p1", {"title": "T"}, "<p>B</p>", 1, [])])
        assert tm == {}


# ---------------------------------------------------------------------------
# build_post_article
# ---------------------------------------------------------------------------

class TestBuildPostArticle:

    def test_basic_article(self):
        article = build.build_post_article(
            "my-post", {"title": "My Post", "date": "2026-05-01"},
            "<p>Hello</p>", 2, [], None, None
        )
        assert "<article" in article
        assert "My Post" in article
        assert "2 min read" in article
        assert "Hello" in article
        assert "post-end" in article

    def test_with_tags(self):
        article = build.build_post_article(
            "my-post", {"title": "T", "date": "2026-05-01"},
            "<p>B</p>", 1, ["planning"], None, None
        )
        assert 'href="/tags/planning.html"' in article
        assert "tag-pill" in article

    def test_prev_next_nav(self):
        article = build.build_post_article(
            "my-post", {"title": "T", "date": "2026-05-01"},
            "<p>B</p>", 1, [],
            ("prev-post", {"title": "Previous"}),
            ("next-post", {"title": "Next"}),
        )
        assert "post-nav-prev" in article
        assert "post-nav-next" in article
        assert "Previous" in article
        assert "Next" in article

    def test_no_nav_when_none(self):
        article = build.build_post_article(
            "p", {"title": "T", "date": "2026-05-01"},
            "<p>B</p>", 1, [], None, None
        )
        assert "post-nav" not in article


# ---------------------------------------------------------------------------
# build_tags_index
# ---------------------------------------------------------------------------

class TestBuildTagsIndex:

    def test_generates_index(self, tmp_project, monkeypatch):
        monkeypatch.setattr(build, "DOCS_DIR", tmp_project / "docs")
        monkeypatch.setattr(build, "TEMPLATE_PATH", tmp_project / "template.html")
        tag_map = {"planning": [("p1", {"title": "P1"}, "<p>B</p>", 1, ["planning"])]}
        build.build_tags_index(tag_map)
        index = tmp_project / "docs" / "tags" / "index.html"
        assert index.exists()
        content = index.read_text()
        assert "planning" in content
        assert "Tags" in content


# ---------------------------------------------------------------------------
# build_tag_pages
# ---------------------------------------------------------------------------

class TestBuildTagPages:

    def test_generates_tag_page(self, tmp_project, monkeypatch):
        monkeypatch.setattr(build, "DOCS_DIR", tmp_project / "docs")
        monkeypatch.setattr(build, "TEMPLATE_PATH", tmp_project / "template.html")
        tag_map = {
            "planning": [("p1", {"title": "P1", "date": "2026-05-01"}, "<p>B</p>", 1, ["planning"])]
        }
        # build_tag_pages relies on tags_dir existing — build_tags_index creates it
        build.build_tags_index(tag_map)
        build.build_tag_pages(tag_map)
        page = tmp_project / "docs" / "tags" / "planning.html"
        assert page.exists()
        content = page.read_text()
        assert "#planning" in content
        assert "P1" in content


# ---------------------------------------------------------------------------
# generate_feed
# ---------------------------------------------------------------------------

class TestGenerateFeed:

    def test_valid_xml(self):
        posts = [
            ("my-post", {"title": "My Post", "date": "2026-05-01"},
             "<p>Content here.</p>", 1, ["test"]),
        ]
        xml = build.generate_feed(posts, "/")
        ElementTree.fromstring(xml)

    def test_contains_expected_elements(self):
        posts = [
            ("my-post", {"title": "My Post", "date": "2026-05-01"},
             "<p>Content here.</p>", 1, []),
        ]
        xml = build.generate_feed(posts, "/")
        assert "<title>Space</title>" in xml
        assert "<title>My Post</title>" in xml
        assert "my-post.html" in xml
        assert "Content here." in xml
        assert "application/atom+xml" in xml

    def test_excludes_drafts(self):
        xml = build.generate_feed([], "/")
        root = ElementTree.fromstring(xml)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        assert len(entries) == 0

    def test_escaped_content(self):
        posts = [
            ("xss", {"title": "<script>alert(1)</script>", "date": "2026-05-01"},
             "<p>A & B < C</p>", 1, []),
        ]
        xml = build.generate_feed(posts, "/")
        assert "<script>" not in xml
        assert "&lt;script&gt;" in xml
        assert "&amp; B" in xml

    def test_feed_with_no_date(self):
        posts = [
            ("no-date", {"title": "No Date"}, "<p>Content.</p>", 1, []),
        ]
        xml = build.generate_feed(posts, "/")
        ElementTree.fromstring(xml)


# ---------------------------------------------------------------------------
# build_template
# ---------------------------------------------------------------------------

class TestBuildTemplate:

    def test_replaces_placeholders(self, tmp_project, monkeypatch):
        monkeypatch.setattr(build, "TEMPLATE_PATH", tmp_project / "template.html")
        result = build.build_template("My Title", "<p>Body</p>",
                                      description="A desc", date="2026-05-01",
                                      base="/space/")
        assert "My Title" in result
        assert "<p>Body</p>" in result
        assert "A desc" in result
        assert "/space/" in result


# ---------------------------------------------------------------------------
# Integration: full build
# ---------------------------------------------------------------------------

class TestFullBuild:

    def test_build_produces_expected_files(self, tmp_project, monkeypatch):
        """Run main() against a temporary project and verify output."""
        monkeypatch.setattr(build, "BASE_DIR", tmp_project)
        monkeypatch.setattr(build, "POSTS_DIR", tmp_project / "posts")
        monkeypatch.setattr(build, "PAGES_DIR", tmp_project / "pages")
        monkeypatch.setattr(build, "ASSETS_DIR", tmp_project / "assets")
        monkeypatch.setattr(build, "TEMPLATE_PATH", tmp_project / "template.html")
        monkeypatch.setattr(build, "DOCS_DIR", tmp_project / "docs")

        _write_post(tmp_project / "posts", "hello", "Hello World", "2026-05-01",
                    "This is my first post.")
        (tmp_project / "pages" / "index.md").write_text(
            "---\ntitle: Space\n---\n\n{{post_list}}"
        )
        (tmp_project / "pages" / "about.md").write_text(
            "---\ntitle: About\n---\n\nAbout this site."
        )

        monkeypatch.setattr(sys, "argv", ["build.py", "--base", "/space/"])
        build.main()

        docs = tmp_project / "docs"
        assert (docs / "index.html").exists()
        assert (docs / "posts" / "hello.html").exists()
        assert (docs / "about.html").exists()
        assert (docs / "feed.xml").exists()
        assert (docs / "sitemap.xml").exists()
        assert (docs / "robots.txt").exists()
        assert (docs / "assets" / "style.css").exists()

    def test_404_page_built(self, tmp_project, monkeypatch):
        """Verify that pages/404.md renders to docs/404.html."""
        monkeypatch.setattr(build, "BASE_DIR", tmp_project)
        monkeypatch.setattr(build, "POSTS_DIR", tmp_project / "posts")
        monkeypatch.setattr(build, "PAGES_DIR", tmp_project / "pages")
        monkeypatch.setattr(build, "ASSETS_DIR", tmp_project / "assets")
        monkeypatch.setattr(build, "TEMPLATE_PATH", tmp_project / "template.html")
        monkeypatch.setattr(build, "DOCS_DIR", tmp_project / "docs")

        (tmp_project / "pages" / "index.md").write_text("---\ntitle: Space\n---\n\n{{post_list}}")
        (tmp_project / "pages" / "404.md").write_text(
            "---\ntitle: Page not found\n---\n\nThis page does not exist."
        )

        monkeypatch.setattr(sys, "argv", ["build.py", "--base", "/space/"])
        build.main()

        f404 = tmp_project / "docs" / "404.html"
        assert f404.exists()
        content = f404.read_text()
        assert "Page not found" in content
        assert "does not exist" in content

    def test_draft_post_excluded_from_all_outputs(self, tmp_project, monkeypatch):
        """A draft post should not appear in HTML, feed, or sitemap."""
        monkeypatch.setattr(build, "BASE_DIR", tmp_project)
        monkeypatch.setattr(build, "POSTS_DIR", tmp_project / "posts")
        monkeypatch.setattr(build, "PAGES_DIR", tmp_project / "pages")
        monkeypatch.setattr(build, "ASSETS_DIR", tmp_project / "assets")
        monkeypatch.setattr(build, "TEMPLATE_PATH", tmp_project / "template.html")
        monkeypatch.setattr(build, "DOCS_DIR", tmp_project / "docs")

        _write_post(tmp_project / "posts", "published", "Published", "2026-05-01",
                    "Public content.")
        _write_post(tmp_project / "posts", "secret", "Secret", "2026-05-02",
                    "Hidden content.", draft=True)
        (tmp_project / "pages" / "index.md").write_text("---\ntitle: Space\n---\n\n{{post_list}}")

        monkeypatch.setattr(sys, "argv", ["build.py", "--base", "/space/"])
        build.main()

        docs = tmp_project / "docs"
        assert not (docs / "posts" / "secret.html").exists()
        assert (docs / "posts" / "published.html").exists()
        feed = ElementTree.fromstring((docs / "feed.xml").read_text())
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        assert len(feed.findall("atom:entry", ns)) == 1
        sitemap = (docs / "sitemap.xml").read_text()
        assert "secret" not in sitemap
        assert "published" in sitemap

    def test_tags_pages_generated(self, tmp_project, monkeypatch):
        """Posts with tags should generate tag index and per-tag pages."""
        monkeypatch.setattr(build, "BASE_DIR", tmp_project)
        monkeypatch.setattr(build, "POSTS_DIR", tmp_project / "posts")
        monkeypatch.setattr(build, "PAGES_DIR", tmp_project / "pages")
        monkeypatch.setattr(build, "ASSETS_DIR", tmp_project / "assets")
        monkeypatch.setattr(build, "TEMPLATE_PATH", tmp_project / "template.html")
        monkeypatch.setattr(build, "DOCS_DIR", tmp_project / "docs")

        _write_post(tmp_project / "posts", "tagged", "Tagged", "2026-05-01",
                    "Content.", tags="planning, systems")
        (tmp_project / "pages" / "index.md").write_text("---\ntitle: Space\n---\n\n{{post_list}}")

        monkeypatch.setattr(sys, "argv", ["build.py", "--base", "/space/"])
        build.main()

        docs = tmp_project / "docs"
        assert (docs / "tags" / "index.html").exists()
        assert (docs / "tags" / "planning.html").exists()
        assert (docs / "tags" / "systems.html").exists()
