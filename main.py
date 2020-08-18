import getopt
import re
import sys
from collections import defaultdict
import csv

from github import Github
from progress.bar import Bar
from tfs import TFSAPI
from urllib3 import Retry


def gh_username(tfs_user, user_map):
    return user_map.get(tfs_user, tfs_user)


def gh_user(github, tfs_user, user_map):
    if not hasattr(gh_user, "cache"):
        gh_user.cache = {}
    if tfs_user not in gh_user.cache:
        try:
            gh_user.cache[tfs_user] = github.get_user(gh_username(tfs_user, user_map))
        except:
            gh_user.cache[tfs_user] = None
    return gh_user.cache[tfs_user]


def at_ref(s):
    return "@" + s if isinstance(s, str) and len(s) > 0 else ""


def remove_prefix(text, prefix):
    return text[text.startswith(prefix) and len(prefix):]


def gh_milestone(repo, title):
    if not hasattr(gh_milestone, "cache"):
        gh_milestone.cache = {}
    if title not in gh_milestone.cache:
        milestone = next((m for m in repo.get_milestones() if m.title == title), None)
        if milestone is None:
            milestone = repo.create_milestone(title=title)
        gh_milestone.cache[title] = milestone
    return gh_milestone.cache[title]


def gh_label(repo, name, color):
    if not hasattr(gh_label, "cache"):
        gh_label.cache = {}
    if name not in gh_label.cache:
        existing_labels = list(repo.get_labels())
        label = next((lab for lab in existing_labels if lab.name == name), None)
        if label is None:
            label = repo.create_label(name=name, color=color)
        gh_label.cache[name] = label
    return gh_label.cache[name]


def gh_state(state):
    state_map = {"Closed": "closed", "Resolved": "closed", "Active": "open"}
    return state_map[state]


def tfs_work_items_to_change_sets(tfs):
    print("Loading change sets...")
    items_to_change_sets = defaultdict(list)
    change_sets = tfs.get_changesets(top=1000000)
    with Bar('Matching work items to change sets...', max=len(change_sets)) as bar:
        for change_set in change_sets:
            for work_item in change_set.workitems:
                items_to_change_sets[work_item.id].append(change_set.id)
            bar.next()
    return items_to_change_sets


def change_sets_to_commits(repo):
    print("Loading commits...")
    cs_to_commit = {}
    commits = repo.get_commits()
    change_set_regex = re.compile(r"git-tfs-id: \[http://tfs.dhsprogram.com/tfs/DefaultCollection\]\$/CSPro/.*;C(\d+)")
    num_missing = 0
    with Bar('Matching change sets to commits...', max=commits.totalCount) as bar:
        for commit in commits:
            message = commit.commit.message
            match = change_set_regex.search(message)
            if match:
                cs_to_commit[int(match.group(1))] = commit
            else:
                num_missing = num_missing + 1
            bar.next()
    print("{} commits missing TFS change set numbers ".format(num_missing))
    return cs_to_commit


def map_list_dict(lst, dct):
    return [dct[k] for k in lst if k in dct]


def work_items_to_commits(tfs, repo):
    cs_to_commit = change_sets_to_commits(repo)
    work_items_to_change_sets = tfs_work_items_to_change_sets(tfs)
    return {k: map_list_dict(v, cs_to_commit) for k, v in work_items_to_change_sets.items()}


def format_commits(commits):
    commit_urls = list(map(lambda c: c.html_url, commits))
    if not commit_urls:
        return ""
    result = "Commits: \r\n\r\n"
    for tag in commit_urls:
        result += "- " + tag + " \r\n"
    return result


def format_body(workitem, commits, user_map):
    body_template = """**TFS#: {}**
---
{}
<br>
{}
<br>
{}

<br><br>

|Action|By|Date|Reason|
|------|--|-----|-----|
|Created  | {} | {} |    |
|Resolved | {} | {} | {} |
|Closed   | {} | {} | {} |
<br>
{}
"""

    closed_reason = workitem['System.Reason'] if workitem['System.State'] == 'Closed' else ""

    return body_template.format(workitem.id,
                                workitem['System.Description'] or "",
                                workitem['Microsoft.VSTS.TCM.ReproSteps'] or "",
                                "History: \r\n\r\n" + workitem['History'] if workitem['History'] else "",
                                at_ref(gh_username(workitem['CreatedBy'], user_map)) or "",
                                workitem['CreatedDate'] or "",
                                at_ref(gh_username(workitem['Microsoft.VSTS.Common.ResolvedBy'], user_map)) or "",
                                workitem['Microsoft.VSTS.Common.ResolvedDate'] or "",
                                workitem['Microsoft.VSTS.Common.ResolvedReason'] or "",
                                at_ref(gh_username(workitem['Microsoft.VSTS.Common.ClosedBy'], user_map)) or "",
                                workitem['Microsoft.VSTS.Common.ClosedDate'] or "",
                                closed_reason,
                                format_commits(commits))


def create_issue(work_item, items_to_commits, github, repo, user_map):
    title = work_item['Title']
    commits = items_to_commits.get(work_item.id, [])
    body = format_body(work_item, commits, user_map)
    max_body_len = 65536
    if len(body) > max_body_len:
        print("Warning: truncated body of work item {} that is longer than {} characters".format(work_item['id'],
                                                                                                 max_body_len))
        body = body[:max_body_len]

    labels = []
    area = work_item['System.AreaLevel2']
    if area:
        labels.append(gh_label(repo, "Area: " + area, "bfd4f2"))
    item_type = work_item['System.WorkItemType']
    if item_type:
        labels.append(gh_label(repo, "Type: " + item_type, "f9d0c4"))

    assignees = []
    assigned_to = gh_user(github, work_item['System.AssignedTo'], user_map)
    if assigned_to:
        assignees.append(assigned_to)

    iteration = work_item['System.IterationLevel2']
    milestone = gh_milestone(repo, iteration) if iteration else None

    state = gh_state(work_item['System.State'])

    if milestone:
        issue = repo.create_issue(title=title, body=body, assignees=assignees, labels=labels, milestone=milestone)
    else:
        issue = repo.create_issue(title=title, body=body, assignees=assignees, labels=labels)

    if state == "closed":
        issue.edit(state="closed")
    for commit in commits:
        commit.create_comment("Associated work item {} issue {}".format(work_item.id, issue.html_url))


def create_issues(gh_token, gh_repo_name, tfs_url, tfs_project, tfs_token, user_map, start):
    print("Connecting to Github repository {}...".format(gh_repo_name))
    github = Github(gh_token, retry=Retry(total=10, status_forcelist=(500, 502, 504), backoff_factor=0.3))
    repo = github.get_repo(gh_repo_name)

    print("Connecting to TFS Server {}...".format(tfs_url))
    tfs = TFSAPI(tfs_url, project=tfs_project, pat=tfs_token)

    print("Getting work items...")
    work_item_query = tfs.run_wiql("SELECT * FROM workitems")
    work_items = tfs.get_workitems(work_item_query.workitem_ids)

    items_to_commits = work_items_to_commits(tfs, repo)

    with Bar('Creating issues...', max=len(work_items)) as bar:
        for work_item in work_items:
            if work_item.id > start:
                create_issue(work_item, items_to_commits, github, repo, user_map)
            bar.next()


def usage(app):
    print("{} -u <TFS Server URL> -t <TFS Access Token> -p <TFS Project> -r <Github Repo> -a <Github Access Token -m "
          "<user map file> -s <Start work item ID>".format(app))


def load_user_map(filename):
    with open(filename, 'r') as map_file:
        return {row[0]: row[1] for row in csv.reader(map_file, delimiter='=')}


def main(argv):
    gh_repo = None
    gh_token = None
    tfs_url = None
    tfs_token = None
    tfs_project = None
    user_map_file = None
    start_item = 0
    try:
        opts, args = getopt.getopt(argv[1:], "hu:t:p:r:a:m:s:",
                                   ["help", "tfs-url=", "tfs-token=", "tfs-project=", "gh-repo=", "gh-token=",
                                    "user-map=", "start="])
    except getopt.GetoptError:
        usage(argv[0])
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            usage(argv[0])
            sys.exit()
        elif opt in ("-u", "--tfs-url"):
            tfs_url = arg
        elif opt in ("-t", "--tfs-token"):
            tfs_token = arg
        elif opt in ("-p", "--tfs-project"):
            tfs_project = arg
        elif opt in ("-r", "--gh-repo"):
            gh_repo = arg
        elif opt in ("-a", "--gh-token"):
            gh_token = arg
        elif opt in ("-m", "--user-map"):
            user_map_file = arg
        elif opt in ("-s", "--start"):
            start_item = int(arg)

    if None in [tfs_url, tfs_token, gh_repo, gh_token]:
        print("Missing required argument")
        usage(argv[0])
        sys.exit(2)

    if tfs_project is None:
        tfs_project = "DefaultCollection"

    user_map = load_user_map(user_map_file) if user_map_file is not None else {}
    create_issues(gh_token, gh_repo, tfs_url, tfs_project, tfs_token, user_map, start_item)


if __name__ == "__main__":
    main(sys.argv)
