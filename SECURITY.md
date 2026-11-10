# Security policy

## Supported versions

Security fixes land on `master` and in the latest release candidate or release.
Older tags are not patched.

| Version | Supported |
|---|---|
| `master` | yes |
| latest `v1.0.0-rc.N` / latest release | yes |
| anything older | no |

## Reporting a vulnerability

Please do not open a public issue. Report privately through GitHub security
advisories: <https://github.com/duketopceo/wisp/security/advisories/new>.

Include what you found, the version (release tag or commit), steps to reproduce,
and the impact. Do not include real API keys or personal data.

You can expect an acknowledgement within a few days and a status update once
the report is triaged. Please allow time for a fix before disclosing publicly;
reporters are credited in the advisory unless they prefer otherwise.

## Scope

In scope: the daemon, shell plugin, CLI, browser extension and native host, and
the install and update scripts. Wisp sends screen content and text to the model
provider you configure; see [docs/PRIVACY.md](docs/PRIVACY.md). Vulnerabilities in
third-party providers or upstream dependencies belong with those projects.
