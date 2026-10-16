# DevOps Copilot Roadmap

## Vision

Build a useful, security-conscious DevOps assistant that starts as a local,
read-only CLI. Add AI, cloud, and team features only when the core diagnostics
are reliable and their privacy, cost, and operational impact are understood.

## Development stages

1. **Python CLI foundation — complete.** Provide clear help, useful
   read-only commands, safe errors and exit codes, automated tests, and accurate
   installation and usage documentation.
2. **Local DevOps diagnostics — complete.** Detect common tools and project files; improve
   Git and Terraform checks without exposing secrets or changing infrastructure.
3. **Terraform troubleshooting — current stage.** Explain likely configuration issues and
   safe validation results, distinguishing evidence from suggestions.
4. **AI integration.** Compare local and hosted options, then add a modular
   provider only after privacy and cost trade-offs are approved.
5. **GitHub and CI/CD assistance.** Inspect workflow configuration and explain
   failures using safe, read-only integrations.
6. **AWS diagnostics and cost awareness.** Add least-privilege read-only
   checks only when justified; never change cloud resources autonomously.
7. **Docker and Kubernetes assistance.** Add local validation and read-only
   diagnosis before considering changes to live workloads.
8. **Product development.** Evaluate packaging, reports, APIs, dashboards, and
   team features based on demonstrated usefulness and operating cost.

## Milestones

- **Completed:** Initial CLI implementation with `inspect`, `terraform`, and
  `git-status`; standard-library-only runtime; basic usage documentation and
  sensitive-path safeguards are present. Added 11 standard-library regression
  tests for command behavior, errors, and sensitive output suppression; verified
  on Python 3.9.6. README minimum version now matches supported syntax.
- **Completed:** Project inspection now skips conventional Python virtual
  environments and bytecode caches; tests verify those exclusions while
  preserving ordinary source folders. A local run now reports 9 files and 2
  directories rather than hundreds of virtual environment files.
- **Completed:** Added a unified, informational `status` command that reuses
  safe project inspection without implicitly running external tools. Verified
  valid and invalid paths; tests prove it does not look up or invoke tools.
- **Completed:** Added `check` to report Git, Python, and Terraform availability
  and recognized version numbers. Missing or unexpected tools get a nonzero
  result; tests verify output filtering. Live check passed for all three tools.
- **Completed:** Terraform failures now provide generic safe next steps while
  suppressing raw command output. Tests verify guidance and suppression.
- **Completed:** Terraform checks recognize `.tf` and `.tf.json` files. A
  mocked test confirms a JSON-only module triggers formatting checks.
- **Completed:** Terraform checks summarize safe configuration filenames and
  suppress sensitive filenames. Tests cover HCL, JSON-only, and sensitive-name
  cases without printing configuration contents.
- **Completed:** Terraform checks give a non-blocking `required_version`
  recommendation when readable configuration lacks a constraint. They do not
  echo configuration values; tests cover present, absent, and unreadable files.
- **Completed:** Git status reports modified, added, deleted, and untracked
  counts; sensitive entries are excluded. Rename filtering suppresses a
  sensitive old filename even when the new name is ordinary.
- **Completed:** Git status now explains that a selected directory may not be
  a repository when Git returns an error, while continuing to hide raw Git
  diagnostics. Regression coverage confirms the clearer message.
- **Completed:** `terraform-analyze` parses JSON-only `.tf.json` files with
  Python's standard library, so JSON analysis does not require the optional
  HCL dependency. Invalid JSON diagnostics remain hidden; all 32 tests pass.
- **Completed:** Added `devops-copilot --version` using the package's single
  version value, with a regression test for the reported version.
- **Completed:** Packaging metadata now reads that same version value instead
  of keeping a second hard-coded copy.
- **Completed:** When the optional HCL parser is missing from a mixed module,
  `terraform-analyze` still summarizes `.tf.json` files, reports skipped HCL
  files, and returns a nonzero status to signal partial analysis.
- **Completed:** Added a provider-free JSON Terraform example and documented
  how to run analysis and the read-only formatting check. Both commands pass
  locally without initializing infrastructure.
- **Completed:** Directory arguments are now optional for project, Terraform,
  and Git status commands; omitted paths use the current directory. Tests cover
  the default for all five commands.
- **Completed:** The `required_version` hint now only recognizes the setting
  inside a top-level Terraform block, reducing false positives from unrelated
  assignments. Regression tests pass.
- **Completed:** Project summaries also skip `node_modules` dependency trees,
  alongside Python virtual environments and caches, to keep local scans small.
- **Completed:** Invalid Terraform JSON diagnostics now include safe line and
  column numbers without showing file contents or parser messages.
- **Completed:** Project summaries now gather counts in one filesystem walk
  without storing a full list of project file paths.
- **Completed:** The `required_version` hint now reports the visible filename
  and HCL line number when available, without echoing the version value.
- **Completed:** Added a provider-free HCL example. Terraform formatting passes
  locally; analysis correctly reports that the optional parser is unavailable.
- **Completed:** When validation is skipped, the CLI explains that the module
  needs initialization and that `terraform init` may download providers. It
  leaves initialization to the user.
- **Completed:** `terraform-analyze` flags potential internet-wide AWS security
  group ingress in JSON and HCL for inline and standalone resource forms.
  Restricted ranges and egress are ignored. Output avoids resource labels and
  values and clarifies that static findings do not confirm deployed exposure.
  Known protocols and ports are summarized safely; unresolved values are not
  printed, and unresolved CIDRs produce an incomplete result. The real optional
  parser was verified; all 46 tests pass, including parser-backed HCL tests.
- **Completed:** Added a `required_version` advisory. Detection handles HCL,
  compact JSON, and line comments without echoing file contents; tests cover
  present, absent, unreadable, and commented-out declarations.
- **Completed:** Version-constraint detection now ignores multi-line HCL
  comments and quoted text; `.tf.json` files are checked with the standard JSON
  parser. Tests cover these false-positive cases.
- **Completed:** README explains validation, planning, applying, and destroying;
  it states that the CLI runs formatting and validation only.
- **Completed:** Terraform formatting failures no longer assume formatting is
  the cause; guidance acknowledges syntax errors and keeps raw output hidden.
- **Completed:** User approved optional HCL parser support. Packaging metadata
  provides a separate optional extra; the parser was installed in the project
  virtual environment and verified against real HCL examples. JSON analysis
  continues to use the standard library.
- **Stage 2 complete:** Local tool availability, project overview, Git status,
  and safe Terraform formatting/validation checks are implemented.
- **Design note:** Keep the current narrow Terraform hint standard-library
  only. HCL supports nested syntax and single-line and multiline comments; a
  full parser would reduce false positives for richer rules. Revisit a parser
  only when a concrete diagnostic needs it.
- **Future:** Tool detection and clearer diagnostics; Terraform explanations;
  optional AI and integrations only after the core CLI is dependable.

## Current project state

The checkout does not contain a `.git` directory, so repository history and
working-tree status could not be inspected here. Packaging metadata now supports
a base installation, console entry point, and optional Terraform parser extra.
The base CLI and regression suite run on Python 3.9.6. The optional
`python-hcl2` 8.1.4 parser is installed in the project virtual environment and
verified with the HCL analysis tests.
