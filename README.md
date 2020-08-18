# tfs-work-items-to-github-issues
Export work items from Microsoft Team Foundation Server to Github Issues

Reads work items from TFS Server, converts to Github issues and uploads them to a Github repository.

The following fields are mapped:

| TFS Work Item | Github Issue |
|---------------|--------------|
| Title | Title |
| Assigned To | Assignees[1] |
| Iteration | Milestone |
| Work Item Type | Label (Type: XXX) |
| Area | Label: (Area: XXX) |
| State | open or closed |
| ID | Body |
| Steps to Reproduce | Body |
| Description | Body |
| Created By | Body |
| Created Date | Body |
| Resolved Date | Body |
| Resolved By | Body |
| Resolved Reason | Body |
| Closed Date | Body |
| Closed By | Body |
| Closed Reason | Body |

[1] *Assignments are only mapped if there is a corresponding Github user for the TFS user*


# Usage

```
tfs-work-items-to-github-issues -u <TFS Server URL> -t <TFS Access Token> -p <TFS Project> -r <Github Repo> -a <Github Access Token> -m <user map file> -s <Start work item ID>
```

For example:

```
tfs-work-items-to-github-issues -u http://tfs.tfs.com/tfs -p DefaultCollection -t acc3457e21ff4 -r jhandley/tfs-work-items-to-github-issues -a 8286e190a883a1bcca4   -m user_map.txt
```

# Mapping users

To associate usernames in TFS with Github users provide a text file that contains the TFS to Github mapping. Each line in the text should have the TFS username and the corresponding Github username separated by an equal sign. For example:

```
Josh <12345-12\jhandley>=jhandley
```


# Linking commits to issues

Assuming the code has been ported from TFS to Git using [git-tfs](https://github.com/git-tfs/git-tfs) this tool will add links to each of the commits in the repository that corresponds to a TFS change set that is associated with the work item. It will also add a comment to the commit containing a link to the associated issue. It does this by parsing the links to TFS changesets in the commit messages generated by git-tfs. These links look like this _git-tfs-id: [http://tfs.tfs.com/tfs/DefaultCollection]$/MyProject;C1234_. Note that these links are stripped from the commit messages if you do the clean commits step in the [tfs-git directions](https://github.com/git-tfs/git-tfs/blob/master/doc/usecases/migrate_tfs_to_git.md). If you remove those links the linking of issues to commits will no longer work.


This tool uses the following packages:

- https://github.com/devopshq/tfs
- https://github.com/PyGithub/PyGithub
- https://github.com/verigak/progress/
