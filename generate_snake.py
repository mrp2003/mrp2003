import datetime
import os
import time
from collections import defaultdict

import requests


GITHUB_API_URL = "https://api.github.com"
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
GRID_DAYS = 371
GRID_HEIGHT = 7
CELL_SIZE = 16
DOT_SIZE = 12
DOT_RADIUS = 2
SNAKE_LENGTH = 5

LIGHT_PALETTE = {
    "empty": "#ebedf0",
    "border": "#1b1f230a",
    "dots": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
    "snake": "purple",
}

DARK_PALETTE = {
    "empty": "#161b22",
    "border": "#1b1f230a",
    "dots": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"],
    "snake": "purple",
}


def main():
    token = os.environ["ACCESS_TOKEN"]
    headers = get_github_headers(token)
    login, user_id = fetch_viewer(headers)
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=GRID_DAYS - 1)

    print(f"Fetching contributions for {login} from {start_date} to {today}")
    daily_counts = fetch_daily_contributions(user_id, start_date, today, headers)
    cells = build_cells(start_date, today, daily_counts)

    os.makedirs("dist", exist_ok=True)
    write_svg("dist/github-snake.svg", cells, LIGHT_PALETTE)
    write_svg("dist/github-snake-dark.svg", cells, DARK_PALETTE)
    print(f"Generated snake from {sum(daily_counts.values())} commits across accessible repositories")


def get_github_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_viewer(headers):
    query = """
    query {
        viewer {
            login
            id
        }
    }"""
    viewer = run_graphql_query(query, {}, headers)["data"]["viewer"]
    return viewer["login"], viewer["id"]


def fetch_daily_contributions(user_id, start_date, end_date, headers):
    repos = fetch_accessible_repositories(headers)
    counts = defaultdict(int)
    seen_commit_shas = set()

    for repo in repos:
        branch = repo.get("default_branch")
        if not branch:
            continue

        commits = fetch_repository_commits(repo, branch, user_id, start_date, end_date, headers)
        for commit in commits:
            if commit["oid"] in seen_commit_shas:
                continue

            committed_date = parse_github_date(commit["committedDate"]).date()
            if start_date <= committed_date <= end_date:
                counts[committed_date] += 1
                seen_commit_shas.add(commit["oid"])

    return counts


def fetch_accessible_repositories(headers):
    repos = []
    seen_repos = set()
    page = 1

    while True:
        page_repos = run_rest_query(
            f"{GITHUB_API_URL}/user/repos",
            headers,
            {
                "visibility": "all",
                "affiliation": "owner,collaborator,organization_member",
                "per_page": 100,
                "page": page,
            },
        )

        if not page_repos:
            return repos

        for repo in page_repos:
            if repo["full_name"] in seen_repos:
                continue

            repos.append(repo)
            seen_repos.add(repo["full_name"])

        page += 1


def fetch_repository_commits(repo, branch, user_id, start_date, end_date, headers):
    query = """
    query($owner: String!, $name: String!, $branch: String!, $authorId: ID!, $since: GitTimestamp!, $until: GitTimestamp!, $after: String) {
        repository(owner: $owner, name: $name) {
            ref(qualifiedName: $branch) {
                target {
                    ... on Commit {
                        history(first: 50, after: $after, author: {id: $authorId}, since: $since, until: $until) {
                            nodes {
                                oid
                                committedDate
                            }
                            pageInfo {
                                hasNextPage
                                endCursor
                            }
                        }
                    }
                }
            }
        }
    }"""
    commits = []
    cursor = None
    since = datetime.datetime.combine(start_date, datetime.time.min, tzinfo=datetime.timezone.utc).isoformat()
    until = datetime.datetime.combine(end_date, datetime.time.max, tzinfo=datetime.timezone.utc).isoformat()

    while True:
        variables = {
            "owner": repo["owner"]["login"],
            "name": repo["name"],
            "branch": branch,
            "authorId": user_id,
            "since": since,
            "until": until,
            "after": cursor,
        }
        repository = run_graphql_query(query, variables, headers)["data"]["repository"]
        ref = repository["ref"] if repository else None

        if not ref or not ref["target"]:
            return commits

        history = ref["target"].get("history")
        if not history:
            return commits

        commits.extend(history["nodes"])
        if not history["pageInfo"]["hasNextPage"]:
            return commits

        cursor = history["pageInfo"]["endCursor"]


def parse_github_date(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def run_rest_query(url, headers, params=None):
    for attempt in range(5):
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code < 500:
            break
        time.sleep(2 * (attempt + 1))

    response.raise_for_status()
    return response.json()


def run_graphql_query(query, variables, headers):
    for attempt in range(5):
        response = requests.post(
            GITHUB_GRAPHQL_URL,
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=30,
        )
        if response.status_code < 500:
            break
        time.sleep(2 * (attempt + 1))

    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"GitHub GraphQL request failed: {payload['errors']}")

    return payload


def build_cells(start_date, end_date, daily_counts):
    first_sunday = start_date - datetime.timedelta(days=(start_date.weekday() + 1) % 7)
    cells = []
    current_date = first_sunday

    while current_date <= end_date:
        week = (current_date - first_sunday).days // 7
        weekday = (current_date.weekday() + 1) % 7
        count = daily_counts.get(current_date, 0)
        cells.append({
            "date": current_date,
            "x": week,
            "y": weekday,
            "count": count,
            "level": contribution_level(count),
        })
        current_date += datetime.timedelta(days=1)

    return cells


def contribution_level(count):
    if count <= 0:
        return 0
    if count <= 2:
        return 1
    if count <= 5:
        return 2
    if count <= 10:
        return 3
    return 4


def write_svg(path, cells, palette):
    route = build_snake_route(cells)
    width = (max(cell["x"] for cell in cells) + 3) * CELL_SIZE
    height = (GRID_HEIGHT + 5) * CELL_SIZE
    view_box = f"{-CELL_SIZE} {-CELL_SIZE * 2} {width} {height}"
    duration = max(len(route) * 100, 1000)

    parts = [
        f'<svg viewBox="{view_box}" width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">',
        "<desc>Generated from accessible GitHub repository commits using a custom snk-compatible contribution grid</desc>",
        "<style>",
        ":root{--cb:%s;--cs:%s;--ce:%s;%s}" % (
            palette["border"],
            palette["snake"],
            palette["empty"],
            "".join(f"--c{index}:{color};" for index, color in enumerate(palette["dots"])),
        ),
        ".grid rect{fill:var(--c0);stroke:var(--cb);stroke-width:1px}",
        '.grid rect[data-level="1"]{fill:var(--c1)}',
        '.grid rect[data-level="2"]{fill:var(--c2)}',
        '.grid rect[data-level="3"]{fill:var(--c3)}',
        '.grid rect[data-level="4"]{fill:var(--c4)}',
        ".snake{fill:var(--cs)}",
        ".snake-eye{fill:#fff}",
        "</style>",
        '<g class="grid">',
    ]

    for cell in cells:
        x = cell["x"] * CELL_SIZE
        y = cell["y"] * CELL_SIZE
        parts.append(
            '<rect x="%s" y="%s" width="%s" height="%s" rx="%s" ry="%s" data-date="%s" data-count="%s" data-level="%s" />'
            % (
                x + (CELL_SIZE - DOT_SIZE) / 2,
                y + (CELL_SIZE - DOT_SIZE) / 2,
                DOT_SIZE,
                DOT_SIZE,
                DOT_RADIUS,
                DOT_RADIUS,
                cell["date"].isoformat(),
                cell["count"],
                cell["level"],
            )
        )

    parts.extend(["</g>", create_animated_snake(route, duration), "</svg>"])

    with open(path, "w", encoding="utf-8") as file:
        file.write("".join(parts))


def build_snake_route(cells):
    active_cells = [cell for cell in cells if cell["count"] > 0]
    if not active_cells:
        active_cells = cells

    active_cells.sort(key=lambda cell: (cell["x"], cell["y"]))
    route = []
    current = {"x": 0, "y": 0}

    for cell in active_cells:
        route.extend(path_between(current, cell))
        current = {"x": cell["x"], "y": cell["y"]}

    return dedupe_route(route or [{"x": 0, "y": 0}])


def path_between(start, end):
    path = []
    x = start["x"]
    y = start["y"]

    while x != end["x"]:
        x += 1 if end["x"] > x else -1
        path.append({"x": x, "y": y})

    while y != end["y"]:
        y += 1 if end["y"] > y else -1
        path.append({"x": x, "y": y})

    return path


def dedupe_route(route):
    deduped = []
    for point in route:
        if deduped and deduped[-1] == point:
            continue
        deduped.append(point)
    return deduped


def create_animated_snake(route, duration):
    segments = []
    for index in range(SNAKE_LENGTH):
        values = animation_values(route, index)
        opacity = 1 - (index * 0.12)
        segments.append(
            '<rect class="snake" width="%s" height="%s" rx="%s" ry="%s" opacity="%.2f">'
            '<animate attributeName="x" dur="%sms" repeatCount="indefinite" values="%s" />'
            '<animate attributeName="y" dur="%sms" repeatCount="indefinite" values="%s" />'
            "</rect>"
            % (DOT_SIZE, DOT_SIZE, DOT_RADIUS, DOT_RADIUS, opacity, duration, values["x"], duration, values["y"])
        )

    head_values = animation_values(route, 0)
    eye_offset = DOT_SIZE * 0.3
    segments.append(
        '<circle class="snake-eye" r="1.2">'
        '<animate attributeName="cx" dur="%sms" repeatCount="indefinite" values="%s" />'
        '<animate attributeName="cy" dur="%sms" repeatCount="indefinite" values="%s" />'
        "</circle>"
        % (duration, offset_values(head_values["x"], eye_offset), duration, offset_values(head_values["y"], eye_offset))
    )

    return "<g>" + "".join(segments) + "</g>"


def animation_values(route, lag):
    adjusted = []
    for index in range(len(route)):
        adjusted.append(route[max(index - lag, 0)])

    return {
        "x": ";".join(str(point["x"] * CELL_SIZE + (CELL_SIZE - DOT_SIZE) / 2) for point in adjusted),
        "y": ";".join(str(point["y"] * CELL_SIZE + (CELL_SIZE - DOT_SIZE) / 2) for point in adjusted),
    }


def offset_values(values, offset):
    return ";".join(str(float(value) + offset) for value in values.split(";"))


if __name__ == "__main__":
    main()
