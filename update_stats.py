import datetime
import requests
import os
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


def fetch_github_data():
    """
    Fetch data for repositories, contributions, commits, stars, followers, and LOC from GitHub API.
    """
    # GraphQL query templates
    repo_query = '''
    query($login: String!) {
        user(login: $login) {
            repositories {
                totalCount
            }
        }
    }'''

    star_query = '''
    query($login: String!) {
        user(login: $login) {
            repositories {
                edges {
                    node {
                        stargazers {
                            totalCount
                        }
                    }
                }
            }
        }
    }'''

    commit_query = '''
    query($login: String!) {
        user(login: $login) {
            contributionsCollection {
                totalCommitContributions
            }
        }
    }'''

    follower_query = '''
    query($login: String!) {
        user(login: $login) {
            followers {
                totalCount
            }
        }
    }'''

    loc_query = '''
    query($login: String!) {
        user(login: $login) {
            repositories(first: 100) {
                edges {
                    node {
                        name
                        defaultBranchRef {
                            target {
                                ... on Commit {
                                    history {
                                        totalCount
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }'''

    headers = {'authorization': 'token ' + os.environ['ACCESS_TOKEN']}
    user_name = os.environ['USER_NAME']

    # Send GraphQL requests
    def run_query(query, variables):
        response = requests.post('https://api.github.com/graphql', json={'query': query, 'variables': variables}, headers=headers)
        if response.status_code != 200:
            raise Exception(f"GitHub API request failed: {response.status_code} {response.text}")
        return response.json()

    # Fetch data
    repo_data = run_query(repo_query, {'login': user_name})['data']['user']['repositories']['totalCount']
    star_data = sum(edge['node']['stargazers']['totalCount'] for edge in
                    run_query(star_query, {'login': user_name})['data']['user']['repositories']['edges'])
    commit_data = run_query(commit_query, {'login': user_name})['data']['user']['contributionsCollection']['totalCommitContributions']
    follower_data = run_query(follower_query, {'login': user_name})['data']['user']['followers']['totalCount']

    # LOC data
    loc_data = run_query(loc_query, {'login': user_name})['data']['user']['repositories']['edges']
    loc_added, loc_removed, loc_total = 0, 0, 0

    for repo in loc_data:
        try:
            history = repo['node']['defaultBranchRef']['target']['history']
            loc_total += history['totalCount']
        except (TypeError, KeyError):
            continue

    return repo_data, commit_data, star_data, follower_data, loc_total, loc_added, loc_removed


def update_svg(filename, age, repo_count, contrib_count, commit_count, star_count, follower_count, loc_total, loc_added, loc_removed):
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
    set_next_value('Repos', repo_count)
    set_next_value('Contributed', contrib_count)
    set_next_value('Commmits', commit_count)
    set_next_value('Lines of Code', loc_total)
    set_first_class_value('addColor', f"{loc_added}++")
    set_first_class_value('delColor', f"{loc_removed}--")

    with open(filename, 'w', encoding='utf-8') as file:
        file.write(svg.toxml())


if __name__ == '__main__':
    # User-defined birthday
    birthday = datetime.datetime(2003, 6, 13)

    # Fetch data
    age = get_age(birthday)
    repo_count, commit_count, star_count, follower_count, loc_total, loc_added, loc_removed = fetch_github_data()

    # Update SVG files
    update_svg('dark.svg', age, repo_count, repo_count, commit_count, star_count, follower_count, loc_total, loc_added, loc_removed)
    update_svg('light.svg', age, repo_count, repo_count, commit_count, star_count, follower_count, loc_total, loc_added, loc_removed)
