#!/usr/bin/env python3
"""Generate a GitHub activity graph (last 31 days) as a self-contained SVG.

No third-party hosting and no extra packages - only the Python standard library.
Uses the GitHub GraphQL API when a token is available, otherwise (or on failure)
reads the public contribution calendar of the profile - no token required.
"""
import datetime as dt
import html
import json
import os
import random
import re
import urllib.request

USER = os.environ.get("GH_USER", "sseal2004")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT = os.environ.get("OUT", "assets/activity-graph.svg")
DAYS = 31

# tokyo-night colours (same values as the old URL parameters)
BG, TEXT, LINE, POINT, GRID = "#0D1117", "#0E75B6", "#F75C7E", "#FFFFFF", "#1F2A37"

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}"""


def fetch_counts(start: dt.date, end: dt.date) -> dict:
    variables = {
        "login": USER,
        "from": f"{start.isoformat()}T00:00:00Z",
        "to": f"{end.isoformat()}T23:59:59Z",
    }
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": variables}).encode(),
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "activity-graph-generator",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if data.get("errors") or not data.get("data", {}).get("user"):
        raise SystemExit(f"GitHub API error: {data}")
    weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return {d["date"]: d["contributionCount"] for w in weeks for d in w["contributionDays"]}


def fetch_counts_public(start: dt.date, end: dt.date) -> dict:
    """No-token fallback: read the public contribution calendar HTML of the profile."""
    req = urllib.request.Request(
        f"https://github.com/users/{USER}/contributions",
        headers={"User-Agent": "Mozilla/5.0 (activity-graph-generator)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        page = resp.read().decode("utf-8", "replace")
    cell_date = {}
    for tag in re.findall(r"<td[^>]*ContributionCalendar-day[^>]*>", page):
        d = re.search(r'data-date="([\d-]+)"', tag)
        i = re.search(r'id="(contribution-day-component-[\d-]+)"', tag)
        if d and i:
            cell_date[i.group(1)] = d.group(1)
    counts = {}
    for cell_id, n in re.findall(r'for="(contribution-day-component-[\d-]+)"[^>]*>\s*(No|\d+) contributions?', page):
        if cell_id in cell_date:
            counts[cell_date[cell_id]] = 0 if n == "No" else int(n)
    if not counts:
        raise SystemExit("Could not read the public contribution calendar")
    return counts


def nice_step(max_value: int) -> int:
    for step in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
        if max_value / step <= 5:
            return step
    return 1000


def build_svg(days: list, counts: list) -> str:
    W, H = 900, 330
    L, R, T, B = 70, 30, 70, 60
    plot_w, plot_h = W - L - R, H - T - B

    step = nice_step(max(counts + [1]))
    y_max = step * (-(-max(counts + [1]) // step))  # round up to a multiple of step

    def x(i):
        return L + plot_w * i / (len(counts) - 1)

    def y(v):
        return T + plot_h * (1 - v / y_max)

    p = []
    p.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
             f'font-family="Segoe UI, Helvetica, Arial, sans-serif">')
    p.append(f'<rect width="{W}" height="{H}" fill="{BG}" rx="6"/>')
    p.append(f'<text x="{W/2}" y="34" text-anchor="middle" font-size="19" font-weight="600" fill="{TEXT}">'
             f'{html.escape(USER)}\'s Contribution Graph</text>')

    # horizontal grid + y labels
    for v in range(0, y_max + 1, step):
        p.append(f'<line x1="{L}" y1="{y(v):.1f}" x2="{W-R}" y2="{y(v):.1f}" stroke="{GRID}" stroke-width="1"/>')
        p.append(f'<text x="{L-10}" y="{y(v)+4:.1f}" text-anchor="end" font-size="12" fill="{TEXT}">{v}</text>')

    # x labels (day of month)
    for i, d in enumerate(days):
        p.append(f'<text x="{x(i):.1f}" y="{T+plot_h+20}" text-anchor="middle" font-size="11" fill="{TEXT}">{d.day}</text>')

    # axis titles
    p.append(f'<text x="{L+plot_w/2}" y="{H-14}" text-anchor="middle" font-size="13" fill="{TEXT}">Days</text>')
    p.append(f'<text transform="translate(18 {T+plot_h/2}) rotate(-90)" text-anchor="middle" font-size="13" fill="{TEXT}">Contributions</text>')

    # line + points
    pts = " ".join(f"{x(i):.1f},{y(c):.1f}" for i, c in enumerate(counts))
    p.append(f'<polyline points="{pts}" fill="none" stroke="{LINE}" stroke-width="2.5" stroke-linejoin="round"/>')
    for i, c in enumerate(counts):
        p.append(f'<circle cx="{x(i):.1f}" cy="{y(c):.1f}" r="3.5" fill="{POINT}"><title>{days[i]}: {c} contributions</title></circle>')

    p.append("</svg>")
    return "\n".join(p)


def main():
    end = dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=DAYS - 1)
    days = [start + dt.timedelta(days=i) for i in range(DAYS)]

    if os.environ.get("DEMO") == "1":          # offline test with fake data
        random.seed(7)
        counts = [random.choice([0, 0, 1, 2, 3, 5, 8]) for _ in days]
    else:
        try:
            by_date = fetch_counts(start, end) if TOKEN else fetch_counts_public(start, end)
        except Exception as err:               # API hiccup -> use the public page instead
            print("GraphQL failed, using public page:", err)
            by_date = fetch_counts_public(start, end)
        counts = [by_date.get(d.isoformat(), 0) for d in days]

    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(build_svg(days, counts))
    print(f"Wrote {OUT} - {sum(counts)} contributions in the last {DAYS} days")


if __name__ == "__main__":
    main()
