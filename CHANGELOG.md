# Changelog

## Unreleased

- Terraform analysis now includes local nested modules and displays relative
  paths for findings. Hidden, sensitive, generated, and symlinked paths remain
  excluded.
- Added `github-actions-check` to flag top-level `permissions: write-all` in
  local workflow files. It does not parse YAML or contact GitHub.
- Added `dockerfile-check` to find implicit or explicit `latest` base-image
  tags in local Dockerfiles. It does not execute Docker or pull images.
- Added `project-review` to run Terraform, GitHub Actions, and Dockerfile
  static checks together while continuing after individual check failures.
- Terraform analysis now flags literal public-address settings on
  `aws_db_instance` in HCL and JSON. Findings include source lines and explain
  that subnet routing and network rules determine reachability; dynamic values
  are marked incomplete.
- Terraform analysis also flags explicit `storage_encrypted = false` on
  `aws_db_instance` in HCL and JSON, with source locations and the documented
  cross-region read-replica caveat. Dynamic settings are marked incomplete.
- Terraform analysis also reports explicit
  `aws_db_instance.deletion_protection = false` in HCL and JSON, with source
  locations. The output states that AWS permissions are still required to
  delete the instance; dynamic values are marked incomplete.
- Terraform analysis also reports `aws_db_instance.skip_final_snapshot = true`
  in HCL and JSON, with source locations. It explains the final-snapshot
  behavior without claiming other backups are absent; dynamic values are
  marked incomplete.
- Terraform analysis also flags `aws_db_instance.backup_retention_period = 0`
  in HCL and JSON, with source locations and sanitized AI summaries. It explains
  that RDS automated backups are disabled without making claims about AWS
  Backup plans or other snapshots.
- Terraform analysis now flags explicit S3 bucket versioning statuses
  `Suspended` and `Disabled`, plus `enabled = false` in the legacy bucket block.
  HCL and Terraform JSON are supported; dynamic values are marked incomplete,
  and the report does not claim to inspect live buckets.

## Unreleased

- Terraform static findings now include filenames and parser-derived HCL line
  numbers for supported ingress, S3 ACL/public-access, EBS encryption, and
  IMDS token settings. Terraform JSON findings now include matching source line
  numbers too. Sensitive configuration names remain suppressed; tests verify
  locations in both formats.
- Terraform analysis now flags explicit `http_tokens = "optional"` in EC2
  instance and launch-template metadata options, and marks dynamic settings
  incomplete. Output explains that this permits IMDSv1 compatibility while
  leaving account-level settings, launch overrides, and live behavior
  unverified. HCL/JSON tests and sanitized AI context coverage were added.
- Terraform analysis now flags literal `encrypted = false` in managed
  `aws_ebs_volume` resources and in `aws_instance` root and additional EBS block
  devices, plus EBS blocks in `aws_launch_template` block-device mappings, and
  marks unresolved expressions incomplete. Findings clarify that account-level
  EBS encryption defaults may override the setting; live volumes are not
  checked. HCL and JSON tests and sanitized AI context coverage were added.
- Refreshed the project virtual environment's editable package install after
  discovering its `devops-copilot` entry point was stale. The installed command
  now lists and runs the current Terraform review workflow. README installation
  instructions now use editable mode for checkout-based development.
- Terraform analysis now flags explicitly false bucket-level S3 Block Public
  Access settings and marks unresolved settings incomplete in HCL and JSON.
  Reports do not infer effective exposure; regression tests cover both formats
  and sanitized AI context.
- Added a static Terraform check for literal `public-read` and
  `public-read-write` ACLs in common S3 bucket/object resources. It supports HCL
  and Terraform JSON, reports unresolved dynamic ACL values without echoing
  them, and warns that Block Public Access may override the configuration.
  Bucket policies and grant blocks are not analyzed. Tests cover both formats.
- Added optional `--explain` and `--model` flags to `terraform-review`. It sends
  only allowlisted findings to local Ollama; the standard review remains AI-free.
  Tests verify filename suppression and that analysis errors skip the AI call.
- Added `terraform-review` to run formatting, initialized-directory validation,
  and static Terraform analysis in one local command. Static analysis still
  runs if Terraform checks fail. It does not access AWS, call AI, or change
  files or infrastructure. Offline tests cover command routing and failures.
- Added optional `--output path/to/file.tf` support to `terraform-draft`. It
  creates a new file only, refuses existing targets, requires the `.tf`
  extension, and leaves formatting, validation, and infrastructure changes to
  the user. Regression tests cover successful creation and overwrite refusal.
- Updated `terraform-draft` to request a brief plain-language comment before
  each top-level HCL block. A regression test verifies this prompt requirement;
  model output still needs review because prompts cannot guarantee compliance.
- Confirmed with the user that `terraform-draft` produces a response from the
  locally installed Ollama model. The generated HCL remains unverified until
  reviewed and checked with Terraform.
- Added `terraform-draft` to request an HCL draft from local Ollama using only
  the requirements typed by the user. The command labels output unverified and
  prints it by default without validating files. Tests mock the model; a live
  local response was later confirmed by the user.
- Added `terraform-explain`, which combines the local static analyzer with an
  Ollama explanation. The model receives only allowlisted summaries of public
  ingress and Terraform version findings; no source, filenames, labels, values,
  or unresolved CIDRs are included. Analysis failures skip AI. Tests cover
  sanitized context, unresolved values, and error handling; live Ollama remains
  unverified because this environment blocks localhost access.
- Added `ask` for local AI question answering through Ollama at localhost. It
  uses Python's standard library, sends only the typed question, bounds the
  model context and response, and suppresses local service details on errors.
  Tests mock Ollama; no model was installed or run.
- Added `aws-security-groups`, a read-only AWS CLI command that reports
  internet-wide inbound security group rules without printing group IDs,
  descriptions, credentials, or raw AWS errors. The command accepts an
  optional region and requires `ec2:DescribeSecurityGroupRules`. Regression
  tests use mocked responses; no live AWS account was queried.
- Added `./test.sh` as a one-command way to run the regression suite and check
  the included Terraform examples; it uses the project virtual environment
  when present and documents the shortcut in the README.
- Added HCL security group ingress analysis using the optional parser. Unresolved
  ingress CIDRs now produce an incomplete result instead of a clean claim.
- Added regression checks for unresolved JSON and HCL CIDRs without exposing
  the expression or resource label.
- Fixed HCL normalization to retain multiple resources of the same type and to
  preserve quoted protocol strings such as `"-1"` correctly.
- Added 11 standard-library regression tests covering help and argument
  handling, invalid paths, project summary filtering, and Git/Terraform command
  behavior with mocked subprocesses.
- Corrected the README minimum Python version from 3.10 to 3.9 after verifying
  the CLI on Python 3.9.6.
- Updated `inspect` to skip conventional Python virtual environment and
  bytecode cache directories, including their directory counts; documented the
  exclusions and added regression coverage.
- Added `status <directory>` as a read-only project overview, reusing the safe
  inspection summary without invoking Git or Terraform.
- Added `check` for Git, Python, and Terraform availability and version numbers;
  unexpected version output is not shown.
- Terraform formatting and validation failures now include generic safe next
  steps while raw tool output remains suppressed.
- Terraform checks now recognize JSON configuration files ending in `.tf.json`.
- Terraform checks summarize visible configuration filenames while suppressing
  sensitive filenames and never printing file contents.
- Terraform checks recommend a `required_version` constraint when readable
  configuration lacks one; unreadable files do not trigger a false recommendation.
- Git status reports safe change counts; rename entries with a sensitive old or
  new filename are suppressed.
- `terraform-analyze` detects potential internet-wide AWS security group
  ingress in Terraform JSON, while ignoring egress and restricted CIDRs. It
  reports known protocol and port details, hides unresolved expressions,
  reports coverage limits, and does not claim to confirm deployed exposure.
- Terraform validation skips now explain the initialization requirement and
  that manual `terraform init` may download provider plugins; init is never run
  by the CLI.
- Tightened `required_version` detection for inline HCL and compact JSON, and
  ignored full-line comments to avoid false recommendations.
- Version-constraint detection now skips multiline HCL comments and quoted
  text; `.tf.json` files are inspected with the standard JSON parser.
- Documented the current heuristic limits and deferred a parser dependency.
- Added beginner-friendly Terraform workflow guidance for validation, planning,
  applying, and destroying, with the CLI's command limits stated explicitly.
- Terraform formatting failures now distinguish unknown causes from confirmed
  formatting differences; the CLI directs users to inspect local output.
- Added packaging metadata with optional `python-hcl2>=8.1.4,<9` and the
  read-only `terraform-analyze` command. The base CLI works without the parser.
- Base editable installation and console help succeeded in the local virtual
  environment. Installing the optional extra could not reach the package index;
  parser behavior is covered with mocks pending real package verification.
- The standard-library test suite now passes all 31 tests. Python compilation
  and the installed base console command also pass.
- Rechecked the optional parser after the installation attempt: it remains
  unavailable, and pip cache inspection is disabled by a cache-directory
  ownership warning. Updated the roadmap to reflect completed CLI/diagnostic
  stages and actual packaging status; TODO now records the precise external
  verification step.
- Improved the `git-status` error for non-repository directories while keeping
  raw Git output suppressed; added regression coverage and documented it.
- `terraform-analyze` now uses Python's built-in JSON parser for JSON-only
  modules, so this case no longer needs the optional HCL package. Added tests
  for parser-free JSON analysis and hidden invalid-JSON diagnostics; all 32
  tests pass.
- Added `devops-copilot --version`, sourced from the package version, and
  documented the option.
- Updated packaging metadata to use the same package version value, avoiding
  a second version string that could drift.
- `terraform-analyze` now continues with `.tf.json` files when HCL files are
  present but the optional parser is unavailable. It reports skipped HCL files
  and returns nonzero for partial analysis; regression coverage passes.
- Added and documented a provider-free `.tf.json` example. Local analysis and
  `terraform fmt -check` pass; validation is correctly skipped without init.
- Retried installing the optional HCL parser with a writable temporary pip
  cache; package-index DNS remains unavailable, so the extra is still not
  installed.
- Directory arguments for `inspect`, `status`, `terraform`,
  `terraform-analyze`, and `git-status` now default to the current directory.
  Added regression coverage and documented the behavior.
- Tightened the Terraform version hint to require a top-level `terraform`
  block, avoiding a false positive from unrelated `required_version` values.
- Project inspection now skips `node_modules` trees as well as Python virtual
  environments and caches; regression coverage confirms the exclusion.
- Project summaries now count files, directories, and extensions in one walk
  without retaining every file path in memory.
- Added a regression test to keep project inspection to one filesystem walk.
- Invalid `.tf.json` files now report line and column numbers while keeping
  file contents and parser messages hidden.
- The Terraform version hint now reports the safe configuration filename and
  HCL line number when found, without echoing the constraint value.
- Added a provider-free HCL example for local formatting checks and later
  optional-parser analysis; documented both commands.
- Verified all 11 tests pass on Python 3.9.6. Inspecting this checkout now
  reports 9 files and 2 directories instead of including virtual environment
  contents. After adding `status`, all 13 tests passed; after adding `check`,
  all 16 tests passed and the live command found all three tools. The suite now
  has 25 passing tests, including JSON-only detection, sensitive filename
  suppression, version-constraint advice, Git change counts, rename filtering,
  and initialization guidance.
