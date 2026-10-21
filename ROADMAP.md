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
3. **Terraform troubleshooting — complete for the current narrow checks.** Explain likely configuration issues and
   safe validation results, distinguishing evidence from suggestions.
4. **AI integration — local Ollama Q&A and safe Terraform explanations
   implemented.** Hosted providers and project-context explanations beyond the
   supported static findings remain future work.
5. **GitHub and CI/CD assistance — initial local workflow check implemented.**
   The first check flags a top-level `permissions: write-all` line; YAML
   validation, job-level permissions, other workflow diagnostics, and failure
   explanations remain future work.
6. **AWS diagnostics and cost awareness — initial read-only security group and
   local RDS configuration checks implemented.** Broader diagnostics and cost
   awareness remain future work; never change cloud resources autonomously.
7. **Docker and Kubernetes assistance — initial Dockerfile check implemented.**
   The local check flags implicit or explicit `latest` base-image tags;
   broader Docker and Kubernetes diagnostics remain future work.
8. **Product development.** Evaluate packaging, reports, APIs, dashboards, and
   team features based on demonstrated usefulness and operating cost.

## Milestones

- **Completed:** Added `project-review` to run Terraform static analysis,
  GitHub Actions permission checks, and Dockerfile base-image checks together.
  Each check runs locally and the command continues after individual failures.
- **Completed:** Terraform analysis flags literal
  `aws_db_instance.publicly_accessible = true` in HCL and JSON, marks dynamic
  values incomplete, and gives source locations. It notes that network
  reachability depends on subnet routing and security-group rules; no AWS state
  is queried.
- **Completed:** Terraform analysis flags explicit
  `aws_db_instance.storage_encrypted = false` in HCL and JSON, marks dynamic
  values incomplete, and gives source locations. It notes the provider's
  cross-region read-replica exception and makes no claim about deployed state.
- **Completed:** Terraform analysis reports explicit
  `aws_db_instance.deletion_protection = false` in HCL and JSON, marks dynamic
  values incomplete, and notes that AWS permissions are still required to
  delete an instance. No live settings are queried.
- **Completed:** Terraform analysis reports explicit
  `aws_db_instance.skip_final_snapshot = true` in HCL and JSON, marks dynamic
  values incomplete, and explains that a future Terraform deletion would not
  request a final snapshot. It does not assess other backups or perform deletes.
- **Completed:** Terraform analysis reports
  `aws_db_instance.backup_retention_period = 0` in HCL and JSON, marks dynamic
  values incomplete, and explains that this disables RDS automated backups
  where the setting applies. AWS Backup plans and other snapshots are not
  inspected.
- **Completed:** Terraform analysis flags explicitly suspended or disabled
  S3 versioning in current and legacy Terraform resource forms. HCL/JSON tests
  cover literal and dynamic values; reports include source lines where
  available and do not claim to inspect live buckets.

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
- **Completed:** Terraform analysis flags literal public S3 canned ACLs and
  explicitly false bucket-level S3 Block Public Access settings in HCL and
  JSON. Dynamic values are marked incomplete. Findings do not establish
  effective access; account and organization settings are not inspected.
- **Completed:** Terraform analysis flags literal `encrypted = false` on
  `aws_ebs_volume` resources and `aws_instance` root/additional EBS device
  blocks and `aws_launch_template` EBS mappings in HCL and JSON. Account-level
  encryption defaults may override the declaration; live volumes are not
  checked.
- **Completed:** Terraform analysis flags explicit token-optional metadata
  settings in `aws_instance` and `aws_launch_template` resources. Dynamic
  values are incomplete; account settings, launch overrides, and live behavior
  are not checked.
- **Completed:** Static findings include filenames and parser-derived HCL line
  numbers where supported. Terraform JSON findings include matching source line
  numbers. Sensitive filenames remain suppressed.
- **Completed:** Terraform static analysis includes local nested modules and
  reports paths relative to the selected directory. Hidden, sensitive,
  generated, and symlinked paths remain excluded; regression tests verify this.
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
- **Completed:** Added `aws-security-groups`, which calls the AWS CLI's
  read-only `DescribeSecurityGroupRules` operation and reports internet-wide
  inbound IPv4/IPv6 rules. It suppresses raw AWS diagnostics and does not print
  group IDs or descriptions. Regression tests use mocked responses; no live AWS
  account was queried during implementation.
- **Completed:** Added `ask` using Ollama's local chat endpoint and Python's
  standard library. It sends only the question to localhost, caps context and
  answer length, and keeps working diagnostics available when Ollama is absent.
  Tests use a mocked local response; no model was installed or invoked.
- **Completed:** Added `terraform-explain`, which feeds a local model only
  allowlisted summaries from the existing Terraform static checks. Filenames,
  resource labels, configuration values, and unresolved CIDRs are excluded.
  Analysis errors skip the model request. Regression tests verify the filtering
  and error path; a live model response still needs verification from the user's
  Terminal because this execution environment blocks localhost access.
- **Completed:** Added `terraform-draft`, which asks a local model for a small
  Terraform HCL draft from typed requirements and prints it for review. Optional
  `--output` saves to a new `.tf` file and refuses to overwrite an existing
  target. It does not inspect project files or format, validate, or apply code.
  Offline tests verify input bounds and prompt settings; the user confirmed the
  command returns a draft using local Ollama. The generated HCL still requires
  human review and Terraform validation before use.
- **Updated:** Terraform drafts now ask the model to comment each top-level
  block in beginner-friendly language. Automated tests verify the prompt
  instruction; whether a live model follows it depends on its output.
- **Updated:** Added safe opt-in saving with `--output`; tests verify new-file
  creation and that existing files remain unchanged.
- **Completed:** Added `terraform-review`, a one-command workflow for existing
  local formatting, initialized-directory validation, and static analysis. It
  makes no AWS or AI calls and does not modify files or infrastructure.
- **Updated:** `terraform-review --explain` can optionally ask local Ollama to
  explain supported findings. It reuses the allowlisted context sanitizer, and
  the default command remains AI-free. Tests verify filename exclusion and
  skipped AI on incomplete analysis; live model behavior awaits a user run.
- **Completed:** Terraform analysis flags explicit `public-read` and
  `public-read-write` canned ACLs in common S3 bucket/object resources in HCL
  and JSON. Dynamic values are marked unresolved. Static findings explain that
  Block Public Access can override them; bucket policies and grant blocks are
  not covered.
- **Design note:** Keep the current narrow Terraform hint standard-library
  only. HCL supports nested syntax and single-line and multiline comments; a
  full parser would reduce false positives for richer rules. Revisit a parser
  only when a concrete diagnostic needs it.
- **Future:** Tool detection and clearer diagnostics; Terraform explanations;
  optional AI and integrations only after the core CLI is dependable.

## Current project state

The checkout contains Git metadata and the working tree can be inspected.
Packaging metadata now supports
a base installation, console entry point, and optional Terraform parser extra.
The base CLI and regression suite run on Python 3.9.6. The optional
`python-hcl2` 8.1.4 parser is installed in the project virtual environment and
verified with the HCL analysis tests. The new AWS command requires an installed
AWS CLI and `ec2:DescribeSecurityGroupRules` on the configured identity; no
additional Python dependency was added. AI question answering requires an
optional Ollama installation and a downloaded model; no hosted API or AI
subscription is used.
