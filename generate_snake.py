import datetime
import os
import time

import requests

import snake_solver


GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
GRID_HEIGHT = 7
CELL_SIZE = 16
DOT_SIZE = 12
DOT_RADIUS = 2
SNAKE_LENGTH = 5

LIGHT_PALETTE = {
    "empty": "#ebedf0",
    "border": "#1b1f230a",
    "dots": ["#ebedf0", "#c8d4e2", "#8fa4be", "#5b7aa0", "#2e4970"],
    "snake": "#1e293b",
}

DARK_PALETTE = {
    "empty": "#161b22",
    "border": "#1b1f230a",
    "dots": ["#161b22", "#2a3548", "#3f5471", "#6586ad", "#9ab4d4"],
    "snake": "#f1f5f9",
}


def main():
    token = os.environ["ACCESS_TOKEN"]
    headers = get_github_headers(token)

    summary = fetch_contribution_calendar(headers)
    cells = build_cells_from_weeks(summary["weeks"])

    os.makedirs("dist", exist_ok=True)
    write_svg("dist/github-snake.svg", cells, LIGHT_PALETTE)
    write_svg("dist/github-snake-dark.svg", cells, DARK_PALETTE)
    print(f"Login:                       {summary['login']}")
    print(f"Calendar total (visible):    {summary['total']}")
    print(f"  commits:                   {summary['commits']}")
    print(f"  issues:                    {summary['issues']}")
    print(f"  pull requests:             {summary['prs']}")
    print(f"  reviews:                   {summary['reviews']}")
    print(f"Restricted (PAT can't see):  {summary['restricted']}")
    print(f"Window:                      {summary['from']} → {summary['to']}")


def get_github_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_contribution_calendar(headers):
    query = """
    query {
        viewer {
            login
            contributionsCollection {
                startedAt
                endedAt
                totalCommitContributions
                totalIssueContributions
                totalPullRequestContributions
                totalPullRequestReviewContributions
                restrictedContributionsCount
                contributionCalendar {
                    totalContributions
                    weeks {
                        contributionDays {
                            date
                            contributionCount
                            weekday
                        }
                    }
                }
            }
        }
    }"""
    viewer = run_graphql_query(query, {}, headers)["data"]["viewer"]
    collection = viewer["contributionsCollection"]
    calendar = collection["contributionCalendar"]
    return {
        "login": viewer["login"],
        "total": calendar["totalContributions"],
        "commits": collection["totalCommitContributions"],
        "issues": collection["totalIssueContributions"],
        "prs": collection["totalPullRequestContributions"],
        "reviews": collection["totalPullRequestReviewContributions"],
        "restricted": collection["restrictedContributionsCount"],
        "from": collection["startedAt"],
        "to": collection["endedAt"],
        "weeks": calendar["weeks"],
    }


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


def build_cells_from_weeks(weeks):
    cells = []
    for week_index, week in enumerate(weeks):
        for day in week["contributionDays"]:
            count = day["contributionCount"]
            cells.append({
                "date": datetime.date.fromisoformat(day["date"]),
                "x": week_index,
                "y": day["weekday"],
                "count": count,
                "level": contribution_level(count),
            })
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
    eat_times = get_eat_times(route)
    empty_color = palette["empty"]

    parts = [
        f'<svg viewBox="{view_box}" width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">',
        "<desc>Generated from accessible GitHub repository commits using a custom snk-compatible contribution grid</desc>",
        "<style>",
        ":root{--cb:%s;--cs:%s;--ce:%s;%s}" % (
            palette["border"],
            palette["snake"],
            empty_color,
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
        rect_x = cell["x"] * CELL_SIZE + (CELL_SIZE - DOT_SIZE) / 2
        rect_y = cell["y"] * CELL_SIZE + (CELL_SIZE - DOT_SIZE) / 2
        eat_time = eat_times.get((cell["x"], cell["y"]))
        rect_open = (
            '<rect x="%s" y="%s" width="%s" height="%s" rx="%s" ry="%s" '
            'data-date="%s" data-count="%s" data-level="%s"'
            % (
                rect_x, rect_y, DOT_SIZE, DOT_SIZE, DOT_RADIUS, DOT_RADIUS,
                cell["date"].isoformat(), cell["count"], cell["level"],
            )
        )

        if eat_time is not None and cell["count"] > 0:
            level_color = palette["dots"][cell["level"]]
            eat_fraction = max(min(eat_time / duration, 0.9999), 0.0001)
            parts.append(
                '%s>'
                '<animate attributeName="fill" calcMode="discrete" '
                'values="%s;%s;%s" keyTimes="0;%.6f;1" '
                'dur="%sms" repeatCount="indefinite" />'
                '</rect>'
                % (rect_open, level_color, empty_color, empty_color, eat_fraction, duration)
            )
        else:
            parts.append('%s />' % rect_open)

    parts.extend(["</g>", create_animated_snake(route, duration), "</svg>"])

    with open(path, "w", encoding="utf-8") as file:
        file.write("".join(parts))


def get_eat_times(route):
    eat_times = {}
    for index, point in enumerate(route):
        key = (point["x"], point["y"])
        if key not in eat_times:
            eat_times[key] = index * 100
    return eat_times


def build_snake_route(cells):
    if not cells:
        return [{"x": 0, "y": 0}]

    width = max(cell["x"] for cell in cells) + 1
    height = GRID_HEIGHT
    grid = snake_solver.Grid(width, height)
    for cell in cells:
        level = cell["level"]
        if level > 0:
            snake_solver.set_color(grid, cell["x"], cell["y"], level)

    start_y = height // 2
    snake0 = snake_solver.make_snake([(-1, start_y)] * SNAKE_LENGTH)
    chain = snake_solver.get_best_route(grid, snake0)

    route = [
        {"x": snake_solver.snake_head_x(s), "y": snake_solver.snake_head_y(s)}
        for s in chain
    ]
    return route or [{"x": -1, "y": start_y}]


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
