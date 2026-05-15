import datetime
import requests
import os
import time
from xml.dom import minidom


def get_age(birthday):
    """
    Calculate the age since the given birthday.
    """
    today = datetime.date.today()
    birth_date = birthday.date()

    years = today.year - birth_date.year
    months = today.month - birth_date.month
    days = today.day - birth_date.day

    if days < 0:
        previous_month = today.month - 1 or 12
        previous_month_year = today.year if today.month > 1 else today.year - 1
        days += get_days_in_month(previous_month_year, previous_month)
        months -= 1

    if months < 0:
        months += 12
        years -= 1

    return f'{years} years, {months} months, {days} days'


def get_days_in_month(year, month):
    """
    Return the number of days in the given month.
    """
    if month == 12:
        next_month = datetime.date(year + 1, 1, 1)
        current_month = datetime.date(year, month, 1)
        return (next_month - current_month).days

    next_month = datetime.date(year, month + 1, 1)
    current_month = datetime.date(year, month, 1)
    return (next_month - current_month).days


def format_number(value):
    """
    Format a number with thousands separators for SVG display.
    """
    return f'{value:,}'


def fetch_github_data():
    """
    Fetch live repo and code-change totals across accessible owned and contributed repositories.
    """
    token = os.environ['ACCESS_TOKEN']
    headers = get_github_headers(token)
    user_name, user_id = fetch_viewer(headers)

    return fetch_repository_stats(user_name, user_id, headers)


def get_github_headers(token):
    """
    Return headers used for GitHub REST and GraphQL requests.
    """
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }


def fetch_viewer(headers):
    """
    Fetch the authenticated GitHub user's login and node ID.
    """
    query = '''
    query {
        viewer {
            login
            id
        }
    }'''
    viewer = run_graphql_query(query, {}, headers)['data']['viewer']
    return viewer['login'], viewer['id']


def fetch_repository_stats(user_name, user_id, headers):
    """
    Fetch repo, commit, and LOC stats across all accessible repos and branches.
    """
    accessible_repos = fetch_accessible_repositories(headers)
    owned_repos = {repo['full_name'] for repo in accessible_repos if repo['owner']['login'] == user_name}
    contributed_repos = set()
    seen_commit_shas = set()
    commit_count = 0
    loc_added = 0
    loc_removed = 0

    for repo in accessible_repos:
        repo_commit_count, repo_added, repo_removed = fetch_repository_code_changes(
            repo,
            user_id,
            headers,
            seen_commit_shas,
        )

        if repo_commit_count and repo['owner']['login'] != user_name:
            contributed_repos.add(repo['full_name'])

        commit_count += repo_commit_count
        loc_added += repo_added
        loc_removed += repo_removed

    repo_count = len(owned_repos | contributed_repos)
    loc_total = max(loc_added - loc_removed, 0)

    return len(owned_repos), len(contributed_repos), commit_count, loc_total, loc_added, loc_removed


def fetch_accessible_repositories(headers):
    """
    Fetch all repositories accessible to the authenticated user.
    """
    repos = []
    seen_repos = set()
    page = 1

    while True:
        page_repos = run_rest_query(
            'https://api.github.com/user/repos',
            headers,
            {
                'visibility': 'all',
                'affiliation': 'owner,collaborator,organization_member',
                'per_page': 100,
                'page': page,
            },
        )

        if not page_repos:
            return repos

        for repo in page_repos:
            if repo['full_name'] in seen_repos:
                continue

            repos.append(repo)
            seen_repos.add(repo['full_name'])

        page += 1


def fetch_repository_code_changes(repo, user_id, headers, seen_commit_shas):
    """
    Fetch authored commits and code changes from a repository's default branch.
    """
    repo_commit_count = 0
    repo_added = 0
    repo_removed = 0
    branch = repo.get('default_branch')

    if not branch:
        return repo_commit_count, repo_added, repo_removed

    branch_commits = fetch_default_branch_author_commits(
        repo['owner']['login'],
        repo['name'],
        branch,
        user_id,
        headers,
    )

    for commit in branch_commits:
        commit_sha = commit['oid']
        repo_commit_count += 1

        if commit_sha in seen_commit_shas:
            continue

        seen_commit_shas.add(commit_sha)
        repo_added += commit['additions']
        repo_removed += commit['deletions']

    return repo_commit_count, repo_added, repo_removed


def fetch_default_branch_author_commits(owner, repo_name, branch, user_id, headers):
    """
    Fetch authored commit stats from a repository's default branch.
    """
    query = '''
    query($owner: String!, $name: String!, $branch: String!, $authorId: ID!, $after: String) {
        repository(owner: $owner, name: $name) {
            ref(qualifiedName: $branch) {
                target {
                    ... on Commit {
                        history(first: 50, after: $after, author: {id: $authorId}) {
                            nodes {
                                oid
                                additions
                                deletions
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
    }'''
    commits = []
    cursor = None

    while True:
        variables = {
            'owner': owner,
            'name': repo_name,
            'branch': branch,
            'authorId': user_id,
            'after': cursor,
        }
        data = run_graphql_query(query, variables, headers)['data']['repository']
        ref = data['ref']

        if not ref or not ref['target']:
            return commits

        history = ref['target'].get('history')

        if not history:
            return commits

        commits.extend(history['nodes'])

        if not history['pageInfo']['hasNextPage']:
            return commits

        cursor = history['pageInfo']['endCursor']


def run_rest_query(url, headers, params=None, allow_statuses=None):
    """
    Run a GitHub REST request and return the response JSON.
    """
    allow_statuses = allow_statuses or set()

    for attempt in range(5):
        response = requests.get(url, headers=headers, params=params, timeout=30)

        if response.status_code < 500:
            break

        time.sleep(2 * (attempt + 1))

    if response.status_code in allow_statuses:
        return []

    response.raise_for_status()
    return response.json()


def run_graphql_query(query, variables, headers):
    """
    Run a GitHub GraphQL query and return the response JSON.
    """
    for attempt in range(5):
        response = requests.post(
            'https://api.github.com/graphql',
            json={'query': query, 'variables': variables},
            headers=headers,
            timeout=30,
        )

        if response.status_code < 500:
            break

        time.sleep(2 * (attempt + 1))

    response.raise_for_status()
    payload = response.json()

    if payload.get('errors'):
        raise RuntimeError(f"GitHub GraphQL request failed: {payload['errors']}")

    return payload


def update_svg(filename, age, repo_count, contribution_count, commit_count, loc_total, loc_added, loc_removed):
    """
    Update the SVG file with the provided values.
    """
    svg = minidom.parse(filename)
    tspans = svg.getElementsByTagName('tspan')

    def set_tspan_text(tspan, value):
        if tspan.firstChild:
            tspan.firstChild.data = str(value)
            return

        tspan.appendChild(svg.createTextNode(str(value)))

    def set_next_value(label, value):
        for index, tspan in enumerate(tspans):
            if not tspan.firstChild or tspan.firstChild.data.strip() != label:
                continue

            for next_tspan in tspans[index + 1:]:
                if next_tspan.firstChild:
                    set_tspan_text(next_tspan, value)
                    return

        raise ValueError(f"Could not find SVG label: {label}")

    def set_first_class_value(class_name, value):
        for tspan in tspans:
            if tspan.getAttribute('class') != class_name:
                continue

            set_tspan_text(tspan, value)
            return

        raise ValueError(f"Could not find SVG class: {class_name}")

    set_next_value('Uptime', age)
    set_next_value('Repos Owned', format_number(repo_count))
    set_next_value('Repos Contributed', format_number(contribution_count))
    set_next_value('Commits', format_number(commit_count))
    set_next_value('Lines Added', f"{format_number(loc_added)}++")
    set_next_value('Lines Removed', f"{format_number(loc_removed)}--")
    set_next_value('Lines of Code', format_number(loc_total))

    with open(filename, 'w', encoding='utf-8') as file:
        file.write(svg.toxml())


if __name__ == '__main__':
    # User-defined birthday
    birthday = datetime.datetime(2003, 6, 13)

    # Fetch data
    age = get_age(birthday)
    repo_count, contribution_count, commit_count, loc_total, loc_added, loc_removed = fetch_github_data()

    # Update SVG files
    update_svg('dark.svg', age, repo_count, contribution_count, commit_count, loc_total, loc_added, loc_removed)
    update_svg('light.svg', age, repo_count, contribution_count, commit_count, loc_total, loc_added, loc_removed)
