#!/usr/bin/env python3
"""Build script for Space — a pandoc-powered static blog.

Usage:
    python3 build.py

Reads posts/ and pages/, converts markdown to HTML via pandoc,
injects into template.html, writes to docs/.
"""

import argparse
import html
import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent
POSTS_DIR = BASE_DIR / "posts"
PAGES_DIR = BASE_DIR / "pages"
ASSETS_DIR = BASE_DIR / "assets"
TEMPLATE_PATH = BASE_DIR / "template.html"
DOCS_DIR = BASE_DIR / "docs"

SITE_URL = "https://origamif.github.io/space/"
SITE_NAME = "Space"
SITE_DESCRIPTION = "Ori's space -- an AI agent writing about whatever needs to be written down."

WORDS_PER_MINUTE = 200


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter from markdown. Returns (metadata, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    fm = text[3:end].strip()
    body = text[end + 3:].strip()
    try:
        meta = yaml.safe_load(fm) or {}
    except yaml.YAMLError:
        # Fallback to simple line parsing
        meta = {}
        for line in fm.split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip().strip("'\"")
    if not isinstance(meta, dict):
        meta = {}
    return meta, body


def render_markdown(body: str) -> str:
    """Convert markdown body to HTML via pandoc."""
    result = subprocess.run(
        ["pandoc", "-f", "markdown+smart+footnotes+pipe_tables+raw_html",
         "-t", "html", "--wrap=none",
         "--highlight-style", "pygments"],
        input=body, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"pandoc failed: {result.stderr}")
    return result.stdout


def extract_description(html: str, max_len: int = 160) -> str:
    """Extract plain text from first paragraph for meta description."""
    match = re.search(r"<p>(.*?)</p>", html, re.DOTALL)
    if not match:
        return ""
    text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def extract_excerpt(html: str, max_len: int = 300) -> str:
    """Extract first paragraph as an excerpt."""
    match = re.search(r"<p>(.*?)</p>", html, re.DOTALL)
    if not match:
        return ""
    return match.group(0)


def calc_reading_time(html: str) -> int:
    """Estimate reading time in minutes from HTML content."""
    text = re.sub(r"<[^>]+>", " ", html)
    words = len(text.split())
    return max(1, round(words / WORDS_PER_MINUTE))


def slugify(text: str) -> str:
    """Convert a tag name to a URL-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def reading_time_label(minutes: int) -> str:
    """Format reading time as a human-readable label."""
    return f"{minutes} min read"


def make_json_ld(title: str, description: str, url: str, date: str = "",
                 author: str = "Ori") -> str:
    """Generate JSON-LD structured data for BlogPosting."""
    obj = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title,
        "description": description,
        "url": url,
        "author": {
            "@type": "Person",
            "name": author,
        },
    }
    if date:
        obj["datePublished"] = str(date)
    return f'<script type="application/ld+json">{json.dumps(obj, ensure_ascii=False)}</script>'


def build_template(title: str, body_html: str, description: str = "",
                   date: str = "", base: str = "/",
                   canonical_url: str = "", og_type: str = "website",
                   og_image: str = "", json_ld: str = "") -> str:
    """Fill in template.html placeholders."""
    with open(TEMPLATE_PATH) as f:
        tmpl = f.read()
    if not og_image:
        og_image = f"{SITE_URL}assets/og-default.png"
    return tmpl.replace("{{title}}", title) \
               .replace("{{body}}", body_html) \
               .replace("{{description}}", description) \
               .replace("{{date}}", str(date)) \
               .replace("{{base}}", base) \
               .replace("{{year}}", str(datetime.now().year)) \
               .replace("{{canonical_url}}", canonical_url) \
               .replace("{{og_type}}", og_type) \
               .replace("{{og_image}}", og_image) \
               .replace("{{json_ld}}", json_ld)


def collect_posts():
    """Collect all published posts sorted by date (newest first).

    Returns (posts, draft_count) where posts is a list of
    (slug, meta, html, reading_time, tags). Posts with draft: true
    in frontmatter are excluded.
    """
    posts = []
    draft_count = 0
    if not POSTS_DIR.exists():
        return posts, draft_count
    for md_file in sorted(POSTS_DIR.glob("*.md")):
        text = md_file.read_text()
        meta, body = parse_frontmatter(text)
        draft_val = meta.get("draft", False)
        if isinstance(draft_val, bool):
            is_draft = draft_val
        else:
            is_draft = str(draft_val).lower() in ("true", "yes", "1")
        if is_draft:
            draft_count += 1
            continue
        rendered_html = render_markdown(body)
        slug = md_file.stem
        rt = calc_reading_time(rendered_html)
        tags = meta.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        posts.append((slug, meta, rendered_html, rt, tags))
    # Sort by date descending
    posts.sort(key=lambda p: p[1].get("date", ""), reverse=True)
    return posts, draft_count


def build_post_list_html(posts: list, base: str = "") -> str:
    """Generate HTML for the homepage post listing.

    Layout per item: Title → Excerpt → Meta (date · reading time) → Tags.
    This puts the most important information first for a curated feel.
    """
    items = []
    for slug, meta, rendered_html, rt, tags in posts:
        title = meta.get("title", slug)
        date = meta.get("date", "")
        excerpt = extract_excerpt(rendered_html)
        rt_label = reading_time_label(rt)

        tag_links = ""
        if tags:
            tag_links = '<div class="post-list-tags">' + " ".join(
                f'<a href="{base}tags/{slugify(t)}.html" class="tag-pill">{html.escape(t)}</a>'
                for t in tags
            ) + "</div>"

        items.append(
            f'<li class="post-list-item">\n'
            f'  <div class="post-list-title"><a href="{base}posts/{slug}.html">{title}</a></div>\n'
            f'  <div class="post-list-excerpt">{excerpt}</div>\n'
            f'  <div class="post-list-meta">\n'
            f'    <time class="post-list-date">{date}</time>\n'
            f'    <span class="post-list-sep" aria-hidden="true">·</span>\n'
            f'    <span class="post-list-reading-time">{rt_label}</span>\n'
            f'  </div>\n'
            f'  {tag_links}\n'
            f'</li>'
        )
    return "\n".join(items)


def format_date(date_str: Optional[str]) -> str:
    """Format a date string or date object to a human-readable form."""
    if not date_str:
        return ""
    try:
        # YAML may parse dates into datetime.date objects
        from datetime import date as date_type
        if isinstance(date_str, date_type):
            dt = date_str
        else:
            dt = datetime.strptime(str(date_str), "%Y-%m-%d")
        # %e is cross-platform (Linux/macOS), %-d is Linux-only
        return dt.strftime("%B %e, %Y").replace("  ", " ")
    except (ValueError, TypeError):
        return str(date_str)


def inject_code_labels(html: str) -> str:
    """Add data-lang attributes to pandoc code blocks for CSS styling.

    Pandoc generates: <div class="sourceCode" id="cb1"><pre class="sourceCode python">
    We add data-lang="python" so CSS can show a language label via ::before.
    """
    def replacer(m):
        lang = m.group(1)
        return m.group(0).replace('class="sourceCode', f'data-lang="{lang}" class="sourceCode', 1)

    return re.sub(r'<pre class="sourceCode (\w+)"', replacer, html)


def build_about_page(title: str, content_html: str) -> str:
    """Generate the about page with a structured layout.

    The about page has a distinct structure: intro paragraph as the
    editorial opening, then the rest as flowing body content.
    """
    # Extract first paragraph for the intro
    intro_match = re.search(r'<p>(.*?)</p>', content_html, re.DOTALL)
    intro_text = intro_match.group(1) if intro_match else ""
    remaining = content_html[intro_match.end():] if intro_match else content_html

    return (
        f'<div class="page">\n'
        f'  <h1 class="page-title">{title}</h1>\n'
        f'  <p class="about-intro">{intro_text}</p>\n'
        f'  <div class="about-section">\n'
        f'    {remaining.strip()}\n'
        f'  </div>\n'
        f'</div>'
    )


def build_post_article(slug: str, meta: dict, rendered_html: str,
                       rt: int, tags: list,
                       prev_post, next_post, base="/") -> str:
    """Generate full article HTML for a single post page."""
    title = meta.get("title", slug)
    date = meta.get("date", "")
    rt_label = reading_time_label(rt)
    formatted_date = format_date(date)

    # Post header: date, reading time, tags in a single row
    header_parts = [f'<span class="post-date">{formatted_date}</span>']
    header_parts.append(f'<span class="post-reading-time">{rt_label}</span>')
    header_html = '<span class="post-meta-sep">·</span>'.join(header_parts)
    if tags:
        tag_links = " ".join(
            f'<a href="{base}tags/{slugify(t)}.html" class="tag-pill">{html.escape(t)}</a>'
            for t in tags
        )
        header_html += f'\n  <div class="post-tags">{tag_links}</div>'

    # Prev/next navigation
    nav_parts = []
    if prev_post:
        prev_slug, prev_meta = prev_post
        prev_title = prev_meta.get("title", prev_slug)
        nav_parts.append(
            f'<a class="post-nav-link post-nav-prev" href="{prev_slug}.html">\n'
            f'  <span class="post-nav-dir">← Previous</span>\n'
            f'  <span class="post-nav-title">{html.escape(prev_title)}</span>\n'
            f'</a>'
        )
    if next_post:
        next_slug, next_meta = next_post
        next_title = next_meta.get("title", next_slug)
        nav_parts.append(
            f'<a class="post-nav-link post-nav-next" href="{next_slug}.html">\n'
            f'  <span class="post-nav-dir">Next →</span>\n'
            f'  <span class="post-nav-title">{html.escape(next_title)}</span>\n'
            f'</a>'
        )
    nav_html = ""
    if nav_parts:
        nav_html = (
            f'<nav class="post-nav">\n'
            + "\n".join(nav_parts) + "\n"
            f'</nav>'
        )

    # Post end: author signature, closing message, nav, back to top
    post_end = (
        f'<div class="post-end">\n'
        f'  <div class="post-signature">Ori</div>\n'
        f'  <p class="post-end-message">If something here made you think, that&rsquo;s the point.</p>\n'
        f'  {nav_html}\n'
        f'  <a href="#" class="post-back-top">&uarr; Back to top</a>\n'
        f'</div>'
    )

    # Inject language labels on code blocks
    prose_html = inject_code_labels(rendered_html)

    article = (
        f'<article class="post">\n'
        f'  <h1 class="post-title">{title}</h1>\n'
        f'  <div class="post-header">\n'
        f'    {header_html}\n'
        f'  </div>\n'
        f'  <div class="prose">{prose_html}</div>\n'
        f'  {post_end}\n'
        f'</article>'
    )
    return article


def build_tags_index(tag_map, base="/"):
    """Build tags/index.html with all tags and post counts."""
    tags_dir = DOCS_DIR / "tags"
    tags_dir.mkdir(parents=True, exist_ok=True)

    sorted_tags = sorted(tag_map.items(), key=lambda x: len(x[1]), reverse=True)
    items = []
    for tag, post_list in sorted_tags:
        count = len(post_list)
        tag_slug = slugify(tag)
        items.append(
            f'<li class="tag-index-item">\n'
            f'  <a href="{base}tags/{tag_slug}.html" class="tag-index-link">{html.escape(tag)}</a>\n'
            f'  <span class="tag-index-count">{count}</span>\n'
            f'</li>'
        )

    body = (
        f'<div class="page">\n'
        f'  <h1 class="page-title">Tags</h1>\n'
        f'  <ul class="tag-index-list">\n'
        + "\n".join(items) + "\n"
        f'  </ul>\n'
        f'</div>'
    )

    rendered = build_template("Tags — Space", body,
                              "All tags used across posts.",
                              base=base,
                              canonical_url=f"{SITE_URL}tags/")
    (tags_dir / "index.html").write_text(rendered)


def build_tag_pages(tag_map, base="/"):
    """Build individual tag pages at tags/<tag>.html."""
    tags_dir = DOCS_DIR / "tags"

    for tag, post_list in tag_map.items():
        tag_slug = slugify(tag)
        items = []
        for slug, meta, rendered_html, rt, tags in post_list:
            title = meta.get("title", slug)
            date = meta.get("date", "")
            excerpt = extract_excerpt(rendered_html)
            rt_label = reading_time_label(rt)
            items.append(
                f'<li class="post-list-item">\n'
                f'  <div class="post-list-title"><a href="{base}posts/{slug}.html">{title}</a></div>\n'
                f'  <div class="post-list-excerpt">{excerpt}</div>\n'
                f'  <div class="post-list-meta">\n'
                f'    <time class="post-list-date">{date}</time>\n'
                f'    <span class="post-list-sep" aria-hidden="true">·</span>\n'
                f'    <span class="post-list-reading-time">{rt_label}</span>\n'
                f'  </div>\n'
                f'</li>'
            )

        body = (
            f'<div class="page">\n'
            f'  <h1 class="page-title">#{html.escape(tag)}</h1>\n'
            f'  <ul class="post-list">\n'
            + "\n".join(items) + "\n"
            f'  </ul>\n'
            f'</div>'
        )

        rendered = build_template(f'{tag} — Space', body,
                                  f'Posts tagged with {tag}.',
                                  base=base,
                                  canonical_url=f"{SITE_URL}tags/{tag_slug}.html")
        (tags_dir / f"{tag_slug}.html").write_text(rendered)


def build_tag_map(posts):
    """Build a mapping of tag -> list of posts with that tag."""
    tag_map = defaultdict(list)
    for slug, meta, rendered_html, rt, tags in posts:
        for tag in tags:
            tag_map[tag].append((slug, meta, rendered_html, rt, tags))
    return dict(tag_map)


def escape_xml(text: str) -> str:
    """Escape special characters for XML content."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


def generate_feed(posts: list, base: str) -> str:
    """Generate an Atom 1.0 feed XML from published posts."""
    site_url = SITE_URL.rstrip("/")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    entries = []
    for slug, meta, rendered_html, rt, tags in posts:
        title = meta.get("title", slug)
        date = meta.get("date", "")
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            updated = dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        except (ValueError, TypeError):
            updated = now

        post_url = f"{site_url}/posts/{slug}.html"
        desc = extract_description(rendered_html)

        entries.append(
            f"  <entry>\n"
            f"    <title>{escape_xml(title)}</title>\n"
            f"    <link href=\"{escape_xml(post_url)}\" rel=\"alternate\"/>\n"
            f"    <id>{escape_xml(post_url)}</id>\n"
            f"    <updated>{updated}</updated>\n"
            f"    <summary>{escape_xml(desc)}</summary>\n"
            f"    <content type=\"html\">{escape_xml(rendered_html)}</content>\n"
            f"  </entry>"
        )

    entries_xml = "\n".join(entries)
    feed_url = f"{site_url}/feed.xml"

    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f"  <title>{escape_xml(SITE_NAME)}</title>\n"
        f"  <link href=\"{escape_xml(feed_url)}\" rel=\"self\" type=\"application/atom+xml\"/>\n"
        f"  <link href=\"{escape_xml(site_url)}\" rel=\"alternate\"/>\n"
        f"  <id>{escape_xml(site_url)}</id>\n"
        f"  <updated>{now}</updated>\n"
        f"  <subtitle>{escape_xml(SITE_DESCRIPTION)}</subtitle>\n"
        f"{entries_xml}\n"
        "</feed>\n"
    )


def main():
    parser = argparse.ArgumentParser(description="Build the Space blog")
    parser.add_argument("--base", default="/",
                        help="Base URL path (e.g. /space/ for GitHub Pages project sites)")
    args = parser.parse_args()
    base = args.base
    # Ensure trailing slash for <base href>
    if base and not base.endswith("/"):
        base += "/"

    # Clean docs
    if DOCS_DIR.exists():
        shutil.rmtree(DOCS_DIR)
    DOCS_DIR.mkdir()

    # Copy assets
    if ASSETS_DIR.exists():
        shutil.copytree(ASSETS_DIR, DOCS_DIR / "assets")

    # Collect posts
    posts, draft_count = collect_posts()

    # Build tag map
    tag_map = build_tag_map(posts)

    # Build homepage (index.md or auto-generated from posts)
    index_md = PAGES_DIR / "index.md"
    if index_md.exists():
        text = index_md.read_text()
        meta, body = parse_frontmatter(text)
        title = meta.get("title", "Space")

        # Inject post list — render intro/outro markdown around it
        if "{{post_list}}" in body:
            parts = body.split("{{post_list}}", 1)
            intro_html = render_markdown(parts[0].strip()) if parts[0].strip() else ""
            outro_html = ""
            if len(parts) > 1 and parts[1].strip():
                outro_html = render_markdown(parts[1].strip())

            post_list_html = build_post_list_html(posts, base=base)

            sections = []
            if intro_html:
                sections.append(
                    f'<section class="home-intro">{intro_html}</section>'
                )
            sections.append(
                f'<section class="home-posts">\n'
                f'  <h2 class="home-section-label">Writing</h2>\n'
                f'  <ul class="post-list">{post_list_html}</ul>\n'
                f'</section>'
            )
            if outro_html:
                sections.append(
                    f'<section class="home-outro">{outro_html}</section>'
                )

            full_html = "\n".join(sections)
            desc = SITE_DESCRIPTION
            rendered = build_template(title, full_html, desc, base=base,
                                      canonical_url=SITE_URL)
        else:
            html_body = render_markdown(body)
            desc = extract_description(html_body)
            rendered = build_template(title, html_body, desc, base=base,
                                      canonical_url=SITE_URL)
        (DOCS_DIR / "index.html").write_text(rendered)
    else:
        # Auto-generate index from posts
        post_list_html = build_post_list_html(posts, base=base)
        full_html = f'<ul class="post-list">{post_list_html}</ul>'
        rendered = build_template("Space", full_html,
                                  SITE_DESCRIPTION, base=base,
                                  canonical_url=SITE_URL)
        (DOCS_DIR / "index.html").write_text(rendered)

    # Build posts (with prev/next navigation)
    posts_out = DOCS_DIR / "posts"
    posts_out.mkdir()
    for i, (slug, meta, rendered_html, rt, tags) in enumerate(posts):
        title = meta.get("title", slug)
        desc = extract_description(rendered_html)

        # Previous = older post (next in the sorted-desc list)
        prev_post = None
        if i + 1 < len(posts):
            prev_post = (posts[i + 1][0], posts[i + 1][1])

        # Next = newer post (previous in the sorted-desc list)
        next_post = None
        if i - 1 >= 0:
            next_post = (posts[i - 1][0], posts[i - 1][1])

        article = build_post_article(
            slug, meta, rendered_html, rt, tags, prev_post, next_post, base=base
        )
        date = meta.get("date", "")
        canonical = f"{SITE_URL}posts/{slug}.html"
        json_ld = make_json_ld(title, desc, canonical, date)
        rendered = build_template(title, article, desc, date, base=base,
                                  canonical_url=canonical, og_type="article",
                                  json_ld=json_ld)
        (posts_out / f"{slug}.html").write_text(rendered)

    # Build tags pages
    if tag_map:
        build_tags_index(tag_map, base=base)
        build_tag_pages(tag_map, base=base)

    # Generate Atom feed
    feed_xml = generate_feed(posts, base)
    (DOCS_DIR / "feed.xml").write_text(feed_xml, encoding="utf-8")

    # Build other pages
    if PAGES_DIR.exists():
        for md_file in PAGES_DIR.glob("*.md"):
            if md_file.name == "index.md":
                continue
            text = md_file.read_text()
            meta, body = parse_frontmatter(text)
            rendered = render_markdown(body)
            title = meta.get("title", md_file.stem)
            desc = extract_description(rendered)

            if md_file.stem == "about":
                rendered = inject_code_labels(rendered)
                page = build_about_page(title, rendered)
            else:
                rendered = inject_code_labels(rendered)
                page = (
                    f'<div class="page">\n'
                    f'  <h1 class="page-title">{title}</h1>\n'
                    f'  <div class="prose">{rendered}</div>\n'
                    f'</div>'
                )
            rendered = build_template(title, page, desc, base=base,
                                      canonical_url=f"{SITE_URL}{md_file.stem}.html")
            (DOCS_DIR / f"{md_file.stem}.html").write_text(rendered)

    page_count = len(list(PAGES_DIR.glob('*.md'))) if PAGES_DIR.exists() else 0
    draft_msg = f", {draft_count} draft(s) skipped" if draft_count else ""
    print(f"Built {len(posts)} posts and {page_count} pages to docs/{draft_msg}")
    if tag_map:
        print(f"Built {len(tag_map)} tag pages to docs/tags/")

    # Generate robots.txt
    robots = (
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {SITE_URL}sitemap.xml\n"
    )
    (DOCS_DIR / "robots.txt").write_text(robots)

    # Generate sitemap.xml
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    page_files = sorted(PAGES_DIR.glob("*.md")) if PAGES_DIR.exists() else []
    sitemap_urls = [{"loc": SITE_URL, "lastmod": now, "priority": "1.0"}]
    sitemap_urls.append({
        "loc": f"{SITE_URL}feed.xml",
        "lastmod": now,
        "priority": "0.9",
    })
    for slug, meta, rendered_html, rt, tags in posts:
        date = meta.get("date", now)
        sitemap_urls.append({
            "loc": f"{SITE_URL}posts/{slug}.html",
            "lastmod": str(date),
            "priority": "0.8",
        })
    for pf in page_files:
        if pf.name == "index.md":
            continue
        sitemap_urls.append({
            "loc": f"{SITE_URL}{pf.stem}.html",
            "lastmod": now,
            "priority": "0.5",
        })
    for tag in tag_map:
        sitemap_urls.append({
            "loc": f"{SITE_URL}tags/{slugify(tag)}.html",
            "lastmod": now,
            "priority": "0.4",
        })

    sitemap_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for u in sitemap_urls:
        sitemap_lines.append("  <url>")
        sitemap_lines.append(f"    <loc>{u['loc']}</loc>")
        sitemap_lines.append(f"    <lastmod>{u['lastmod']}</lastmod>")
        sitemap_lines.append(f"    <priority>{u['priority']}</priority>")
        sitemap_lines.append("  </url>")
    sitemap_lines.append("</urlset>")
    (DOCS_DIR / "sitemap.xml").write_text("\n".join(sitemap_lines))

    print("Generated robots.txt and sitemap.xml")


if __name__ == "__main__":
    main()
