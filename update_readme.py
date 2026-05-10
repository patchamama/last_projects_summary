#!/usr/bin/env python3
"""Update README.md with a readable per-project GitHub portfolio view.

Usage:
  python update_readme.py
  python update_readme.py --user patchamama --output README.md
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import getpass
import json
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os

API_BASE = "https://api.github.com"


@dataclass
class RepoCard:
    name: str
    url: str
    start_date: str
    last_commit_date: str
    languages: list[str]
    frameworks: list[str]
    deploy_urls: list[str]
    description: str
    stars: int
    forks: int
    open_issues: int


class GitHubClient:
    def __init__(self, token: str):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "readme-portfolio-updater",
        }

    def get_json(self, url: str) -> Any:
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))

    def get_text(self, url: str) -> str:
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", errors="ignore")


def iso_date(iso_datetime: str | None) -> str:
    return (iso_datetime or "")[:10] if iso_datetime else "—"


def extract_readme_markdown(client: GitHubClient, owner: str, repo: str) -> str:
    try:
        data = client.get_json(f"{API_BASE}/repos/{owner}/{repo}/readme")
        content = data.get("content")
        if content:
            return base64.b64decode(content).decode("utf-8", errors="ignore")
    except Exception:
        pass
    return ""


def extract_description(readme_md: str, fallback: str | None) -> str:
    if readme_md:
        lines = [ln.strip() for ln in readme_md.splitlines()]
        candidates: list[str] = []
        for ln in lines:
            if not ln:
                continue
            if ln.startswith(("#", "![", "```", "<img")):
                continue
            lowered = ln.lower()
            if lowered.startswith(("license", "installation", "usage", "contributing", "table of contents")):
                continue
            ln = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", ln)
            ln = re.sub(r"<[^>]+>", "", ln).strip()
            if len(ln) > 20:
                candidates.append(ln)
            if len(candidates) >= 2:
                break
        if candidates:
            return " ".join(candidates)[:240]

    if fallback and fallback.strip():
        return fallback.strip()
    return "No description available."


def detect_frameworks(readme_md: str, root_filenames: list[str]) -> list[str]:
    haystack = (readme_md + "\n" + "\n".join(root_filenames)).lower()
    patterns = [
        (r"react-native", "React Native"),
        (r"next\\.js|\"next\"", "Next.js"),
        (r"nuxt", "Nuxt.js"),
        (r"\\breact\\b", "React"),
        (r"\\bvue\\b", "Vue"),
        (r"svelte", "Svelte"),
        (r"angular", "Angular"),
        (r"nestjs|@nestjs/core", "NestJS"),
        (r"\\bexpress\\b", "Express"),
        (r"fastapi", "FastAPI"),
        (r"django", "Django"),
        (r"flask", "Flask"),
        (r"streamlit", "Streamlit"),
        (r"gradio", "Gradio"),
        (r"laravel", "Laravel"),
        (r"symfony", "Symfony"),
        (r"ruby on rails|\\brails\\b", "Ruby on Rails"),
        (r"spring boot|spring-boot", "Spring Boot"),
        (r"gin-gonic|\\bgin\\b", "Gin"),
        (r"flutter", "Flutter"),
        (r"vite", "Vite"),
        (r"astro", "Astro"),
        (r"phoenix", "Phoenix"),
    ]
    found: list[str] = []
    for pattern, name in patterns:
        if re.search(pattern, haystack, re.IGNORECASE) and name not in found:
            found.append(name)
    return found


def extract_deploy_urls(owner: str, repo: dict[str, Any], readme_md: str) -> list[str]:
    urls: list[str] = []

    homepage = (repo.get("homepage") or "").strip()
    if homepage:
        urls.append(homepage)

    if repo.get("has_pages"):
        urls.append(f"https://{owner}.github.io/{repo['name']}/")

    # Add likely deployment links from README
    found = re.findall(r"https?://[^\s)\]\"']+", readme_md or "")
    deploy_hosts = (
        "vercel.app",
        "netlify.app",
        "onrender.com",
        "herokuapp.com",
        "railway.app",
        "github.io",
        "pages.dev",
        "fly.dev",
    )
    for u in found:
        if any(host in u for host in deploy_hosts) and u not in urls:
            urls.append(u)

    return urls[:3]


def fetch_repo_cards(client: GitHubClient, owner: str, limit: int) -> list[RepoCard]:
    repos = client.get_json(f"{API_BASE}/users/{owner}/repos?per_page=100&sort=updated")
    repos = [r for r in repos if not r.get("fork") and r.get("owner", {}).get("login", "").lower() == owner.lower()]
    repos.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    repos = repos[:limit]

    cards: list[RepoCard] = []
    for repo in repos:
        name = repo["name"]
        readme_md = extract_readme_markdown(client, owner, name)

        # Languages
        languages: list[str] = []
        try:
            lang_json = client.get_json(f"{API_BASE}/repos/{owner}/{name}/languages")
            languages = list(lang_json.keys())[:4]
        except Exception:
            pass
        if not languages and repo.get("language"):
            languages = [repo["language"]]

        # Root filenames for framework detection hints
        root_filenames: list[str] = []
        try:
            contents = client.get_json(f"{API_BASE}/repos/{owner}/{name}/contents")
            if isinstance(contents, list):
                root_filenames = [it.get("name", "") for it in contents if it.get("type") == "file"]
        except Exception:
            pass

        cards.append(
            RepoCard(
                name=name,
                url=repo["html_url"],
                start_date=iso_date(repo.get("created_at")),
                last_commit_date=iso_date(repo.get("pushed_at")),
                languages=languages,
                frameworks=detect_frameworks(readme_md, root_filenames),
                deploy_urls=extract_deploy_urls(owner, repo, readme_md),
                description=extract_description(readme_md, repo.get("description")),
                stars=int(repo.get("stargazers_count", 0)),
                forks=int(repo.get("forks_count", 0)),
                open_issues=int(repo.get("open_issues_count", 0)),
            )
        )

    return cards


def render_readme(cards: list[RepoCard], owner: str) -> str:
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    lines: list[str] = [
        "# Projects Portfolio — Readable View",
        "",
        f"Updated on {today}. Ordered by latest activity (owned non-fork repositories from `{owner}`).",
        "",
    ]

    for i, c in enumerate(cards, 1):
        lines.append(f"## {i}. 📁 [{c.name}]({c.url})")

        meta = f"🗓️ **{c.start_date} → {c.last_commit_date}**"
        meta += " · 💻 **Languages:** " + (", ".join(c.languages) if c.languages else "—")
        meta += " · 🧩 **Frameworks:** " + (", ".join(c.frameworks) if c.frameworks else "None detected")
        lines.append(meta)

        if c.deploy_urls:
            links = " | ".join(f"[{u}]({u})" for u in c.deploy_urls)
            lines.append(f"🌐 **Deploy / Pages:** {links}")
        else:
            lines.append("🌐 **Deploy / Pages:** —")

        lines.append("")
        lines.append(c.description)
        lines.append("")
        lines.append("<details>")
        lines.append("<summary>Hidden details (ready to expand)</summary>")
        lines.append("")
        lines.append(f"- ⭐ Stars: {c.stars}")
        lines.append(f"- 🍴 Forks: {c.forks}")
        lines.append(f"- 🐞 Open issues: {c.open_issues}")
        lines.append("- ✅ TODO: _Add next action manually_")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines)


def resolve_token(explicit_token: str | None) -> str:
    if explicit_token:
        return explicit_token.strip()

    env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()

    print("No GitHub token found in GITHUB_TOKEN/GH_TOKEN.")
    entered = getpass.getpass("Paste a GitHub PAT (input hidden): ").strip()
    if not entered:
        raise SystemExit("A GitHub token is required.")
    return entered


def validate_token(client: GitHubClient) -> None:
    try:
        me = client.get_json(f"{API_BASE}/user")
    except Exception as e:
        raise SystemExit(f"Failed to validate token: {e}")

    if not isinstance(me, dict) or "login" not in me:
        raise SystemExit("Token validation failed: unexpected GitHub response.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Update README.md from GitHub repositories")
    parser.add_argument("--user", default="patchamama", help="GitHub username (default: patchamama)")
    parser.add_argument("--limit", type=int, default=50, help="Max repositories to include (default: 50)")
    parser.add_argument("--output", default="README.md", help="Output markdown file (default: README.md)")
    parser.add_argument("--token", default=None, help="GitHub token (optional; env/prompt fallback)")
    args = parser.parse_args()

    token = resolve_token(args.token)
    client = GitHubClient(token)
    validate_token(client)

    cards = fetch_repo_cards(client, args.user, args.limit)
    markdown = render_readme(cards, args.user)
    Path(args.output).write_text(markdown, encoding="utf-8")
    print(f"Updated {args.output} with {len(cards)} repositories.")


if __name__ == "__main__":
    main()
