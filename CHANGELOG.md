# Changelog

## Unreleased

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
