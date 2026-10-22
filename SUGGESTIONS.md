# Suggestions Backlog

Estimates assume a small, standard-library-first project. Costs are recurring
service or API costs, not developer time.

## High value

### Explain Terraform check failures without revealing raw diagnostics

- **Problem:** The CLI safely suppresses Terraform output, but a failure gives
  beginners little direction.
- **Who benefits:** Developers who need a safe next step after formatting or
  validation fails.
- **Difficulty:** Low for generic guidance; higher for diagnosing individual
  Terraform errors.
- **Running/API cost:** None.
- **Dependencies and risks:** Keep messages generic and do not echo potentially
  sensitive paths, values, or raw process output.
- **Timing:** Completed; tests confirm useful generic directions without
  exposing raw command output.

### Exclude generated and dependency directories from inspection summaries

- **Problem:** A local `venv/` can make a small project appear to contain
  hundreds of source files.
- **Who benefits:** Developers reviewing a project overview.
- **Difficulty:** Low.
- **Running/API cost:** None.
- **Dependencies and risks:** A small conventional-directory exclusion list;
  avoid hiding arbitrary user folders unexpectedly.
- **Timing:** Completed after observing the issue in this checkout and noting
  that JavaScript dependency trees can also dominate local scans.

### Add regression tests for safety and command behavior

- **Problem:** Existing behavior has no automated guard against regressions.
- **Who benefits:** The maintainer and anyone relying on safe diagnostics.
- **Difficulty:** Low.
- **Running/API cost:** None.
- **Dependencies and risks:** Python `unittest`; test external tools through
  mocks to avoid side effects and machine-specific results.
- **Timing:** Completed; 11 regression tests protect the existing commands
  before more features are added.

### Add a unified `status` command and diagnostic summary

- **Problem:** Current operations require separate commands, and the roadmap
  calls for a quick status view.
- **Who benefits:** Beginners who want a fast overview of a project.
- **Difficulty:** Medium.
- **Running/API cost:** None for local checks.
- **Dependencies and risks:** Reuse existing checks carefully; avoid duplicate
  or surprising subprocess execution.
- **Timing:** Completed; the new `status` command reuses the safe project
  summary and does not invoke external tools.

### Completed: combine the local Terraform checks in one command

- **Priority:** High value.
- **Problem:** Beginners had to remember and run separate Terraform check and
  static-analysis commands.
- **Who benefits:** Developers reviewing a module or a generated draft.
- **Difficulty:** Low; it reuses existing checks without new dependencies.
- **Running/API cost:** None; it runs locally.
- **Dependencies and risks:** Validation runs only in initialized directories;
  the command does not initialize, plan, or change infrastructure.
- **Timing:** Implemented as `terraform-review`; tests cover failure reporting
  and continuing static analysis when tool checks fail. An opt-in `--explain`
  flag also uses local Ollama with sanitized findings only; live explanation
  behavior still needs confirmation in the user's Terminal.

### Completed: flag explicit public S3 canned ACLs in Terraform

- **Priority:** High value.
- **Problem:** Public canned ACLs can grant anonymous read or write access to
  S3 bucket/object data.
- **Who benefits:** Developers reviewing Terraform storage configuration.
- **Difficulty:** Medium; HCL parsing and JSON handling must avoid evaluating
  expressions or printing private values.
- **Running/API cost:** None; analysis runs locally.
- **Dependencies and risks:** This narrow rule only checks literal
  `public-read` and `public-read-write` values in supported bucket and object
  resources. It does not analyze bucket policies or grants, and effective
  access may be overridden by Block Public Access settings.
- **Timing:** Implemented for HCL and Terraform JSON. Tests cover both formats,
  dynamic ACL suppression, and sanitized AI context.

### Completed: flag explicitly disabled bucket-level S3 protections

- **Priority:** High value.
- **Problem:** Explicitly disabling one of the bucket-level public-access
  protections can weaken a storage configuration.
- **Who benefits:** Developers reviewing Terraform before deployment.
- **Difficulty:** Low.
- **Running/API cost:** None; this is local static analysis.
- **Dependencies and risks:** Only literal bucket-level settings are checked;
  account and organization controls may affect effective behavior.
- **Timing:** Implemented with HCL/JSON tests and sanitized AI summaries.

### Completed: flag explicit unencrypted EBS volume settings

- **Priority:** High value.
- **Problem:** Terraform may explicitly request an EBS volume without encryption.
- **Who benefits:** Developers reviewing EC2 storage configuration.
- **Difficulty:** Low.
- **Running/API cost:** None; local static analysis.
- **Dependencies and risks:** The rule checks literal `encrypted = false` on
  `aws_ebs_volume`, `aws_instance` root/additional EBS blocks, and EBS blocks
  in `aws_launch_template`. Account-level defaults may override it; deployed
  volumes are outside the check.
- **Timing:** Implemented with HCL/JSON tests and sanitized AI explanations.

### Completed: flag optional EC2 metadata tokens

- **Priority:** High value.
- **Problem:** Token-optional instance metadata can preserve IMDSv1 compatibility.
- **Who benefits:** Developers reviewing EC2 instance and launch-template
  security settings.
- **Difficulty:** Low.
- **Running/API cost:** None; local static analysis.
- **Dependencies and risks:** Explicit literal settings only. Account-level
  settings and launch overrides affect final behavior; the rule makes no live
  AWS checks.
- **Timing:** Implemented with HCL/JSON tests and sanitized AI summaries.

### Completed: add safe Terraform source locations to findings

- **Priority:** High value.
- **Problem:** Security findings are easier to review when users can locate the
  relevant configuration quickly.
- **Who benefits:** Developers reviewing Terraform diagnostics and AI explanations.
- **Difficulty:** Medium; source positions must come from parsed HCL rather than
  matching arbitrary text.
- **Running/API cost:** None.
- **Dependencies and risks:** HCL line numbers come from parser positions, and
  JSON line numbers come from the standard-library decoder. Sensitive
  configuration filenames remain hidden.
- **Timing:** Implemented for supported HCL/JSON checks and covered by regression tests.

## Future ideas

### Completed: flag explicitly disabled S3 bucket versioning

- **Priority:** High value.
- **Problem:** Suspended or disabled versioning does not preserve new object
  versions as a recovery option.
- **Who benefits:** Developers reviewing Terraform-managed S3 buckets.
- **Difficulty:** Low; supports current and legacy Terraform resource forms.
- **Running/API cost:** None; local static analysis only.
- **Dependencies and risks:** Dynamic settings are marked incomplete. Existing
  object versions, lifecycle rules, AWS Backup, and live bucket state are not
  inspected; versioning alone is not a complete backup strategy.
- **Timing:** Implemented and covered by HCL/JSON tests.

### Flag explicitly public RDS instance settings

- **Priority:** High value.
- **Problem:** An RDS instance configured for public accessibility can receive
  public addressing; teams may intend private-only databases.
- **Who benefits:** Developers reviewing Terraform before deployment.
- **Difficulty:** Low for explicit literal settings in supported resources.
- **Running/API cost:** None; the check is local.
- **Dependencies and risks:** A public-address setting alone does not prove
  internet reachability; subnet routing and security-group rules also matter.
  Do not query or change AWS resources.
- **Timing:** Implemented for literal `aws_db_instance.publicly_accessible =
  true` in HCL and Terraform JSON, with line references and incomplete status
  for dynamic values. The same resource check also flags explicit
  `storage_encrypted = false`, with the cross-region read-replica caveat, and
  explicit `deletion_protection = false`, without implying deletion bypasses
  AWS permissions. It also reports `skip_final_snapshot = true` without
  claiming that other backups are absent, and `backup_retention_period = 0`
  without assuming AWS Backup plans or other snapshots are absent.

### Add a conservative local GitHub Actions workflow check

- **Priority:** High value.
- **Problem:** A malformed or overly permissive workflow can waste CI runs or
  expose repository permissions and secrets.
- **Who benefits:** Developers reviewing GitHub Actions before pushing.
- **Difficulty:** Medium; YAML parsing and GitHub's expression syntax need
  careful handling to avoid misleading results.
- **Running/API cost:** None for local analysis; no GitHub access is needed.
- **Dependencies and risks:** Prefer a maintained YAML parser as an optional
  extra, or limit checks to clearly recognized syntax. Never execute workflow
  commands or print secret values; static checks cannot prove runtime behavior.
- **Timing:** Started as `github-actions-check`, which flags only a top-level
  `permissions: write-all` line. Broader checks are deferred until YAML parsing
  and GitHub expression handling can be validated reliably.

### Add local Dockerfile safety checks

- **Priority:** High value.
- **Problem:** Mutable or implicit base-image tags can make builds change
  unexpectedly over time.
- **Who benefits:** Developers building or reviewing container images.
- **Difficulty:** Low for narrow Dockerfile rules; higher for full syntax and
  build-context validation.
- **Running/API cost:** None for static local checks.
- **Dependencies and risks:** Do not execute Docker builds or pull images
  automatically; distinguish unresolved variable references from verified
  findings.
- **Timing:** Started as `dockerfile-check`, which flags implicit or explicit
  `latest` tags and marks variable image references incomplete. Full Dockerfile
  parsing and build validation are deferred.

### Combine local checks into one project review

- **Priority:** High value.
- **Problem:** Users otherwise need to remember separate commands for each
  supported project type.
- **Who benefits:** Developers who want one quick local review before sharing
  or committing a project.
- **Difficulty:** Low; compose existing read-only checks and preserve each
  check's exit status.
- **Running/API cost:** None.
- **Dependencies and risks:** Avoid adding implicit network, AI, Terraform, or
  Docker execution to a static review command.
- **Timing:** Implemented as `project-review`; it runs local Terraform,
  GitHub Actions, and Dockerfile checks and continues after a check failure.

### Add more Terraform security rules after validating the current finding

- **Priority:** High value.
- **Problem:** One narrow ingress rule cannot cover the range of common
  configuration risks developers need to review.
- **Who benefits:** Developers reviewing Terraform changes and small teams.
- **Difficulty:** Medium; each rule needs schema-aware parsing and tests.
- **Running/API cost:** None; local analysis only.
- **Dependencies and risks:** Keep findings conservative and read-only; do not
  imply the configuration is deployed or complete a security audit.
- **Timing:** Defer until the current rule has been tried on representative
  JSON and HCL projects.

### Completed: add HCL coverage for public-ingress checks

- **Priority:** High value.
- **Problem:** The first public-ingress rule initially analyzed Terraform JSON
  only, leaving common `.tf` modules unchecked for this condition.
- **Who benefits:** Users with conventional HCL Terraform modules.
- **Difficulty:** Medium; requires verifying parser output shapes and nested
  block handling.
- **Running/API cost:** No API cost; local optional parser dependency only.
- **Dependencies and risks:** HCL analysis depends on the optional parser and
  remains local; findings are potential static exposure only.
- **Timing:** Completed after `python-hcl2` 8.1.4 installed in the project
  virtual environment. Real parser tests cover public ingress and unresolved
  CIDR behavior; the full suite passes.

### Completed: show protocol and port context safely

- **Timing:** Implemented for supported Terraform JSON and HCL ingress forms. TCP/UDP
  port ranges, ICMP type/code values, and all-protocol rules use fixed safe
  formatting. Unknown expressions are described as unavailable and are never
  echoed. Unresolved CIDRs produce an incomplete result, not a clean claim.
  Regression tests cover known and unknown values using JSON, mocked parser
  output, and the installed real parser.

### Consider an HCL parser for richer Terraform diagnostics

- **Problem:** Text matching cannot reliably understand nested HCL blocks,
  comments, and expressions well enough for many configuration checks.
- **Who benefits:** Users who need accurate, file-specific Terraform findings.
- **Difficulty:** Medium; parser integration and cross-version behavior need
  tests.
- **Running/API cost:** No API cost; adds a Python dependency and maintenance.
- **Dependencies and risks:** Must handle Terraform JSON too and keep parsing
  local; incorrect rules could create false alarms.
- **Alternatives:** Simple text matching adds no dependency and works for a few
  narrow hints, but it cannot reliably follow nested blocks and multiline
  comments. A parser such as [python-hcl2](https://pypi.org/project/python-hcl2/)
  parses HCL2 into Python data and documents JSON conversion support, but adds
  its own parser dependency and maintenance surface.
- **Timing:** Approved and implemented as the optional `terraform-analyze`
  command; the parser is installed and verified for the current Terraform
  ingress rule. HashiCorp
  documents nested block syntax and `#`,
  `//`, and multiline `/* ... */` comments in its
  [Terraform syntax reference](https://developer.hashicorp.com/terraform/language/syntax/configuration).
  Fixed the known false positive in the current version hint by checking only
  top-level `terraform` blocks; use parser-backed checks for richer HCL rules.

### Explain Terraform findings with file and line references

- **Problem:** A pass/fail result does not teach users how to fix a problem.
- **Who benefits:** Developers learning Terraform and teams triaging failures.
- **Difficulty:** Medium to high, depending on parser needs.
- **Running/API cost:** None for local rule-based checks; AI explanations may
  add API cost and require explicit privacy controls.
- **Dependencies and risks:** Avoid treating heuristics as confirmed defects;
  never read state files or apply changes.
- **Timing:** Defer until CLI safety and tests are established.

### Completed: add optional local AI questions

- **Priority:** High value.
- **Problem:** Static CLI messages cannot answer general DevOps questions.
- **Who benefits:** Beginners learning cloud and DevOps concepts.
- **Difficulty:** Medium.
- **Running/API cost:** No API cost; the user downloads a local model (default
  download about 1.4 GB) and uses local memory and compute.
- **Dependencies and risks:** Optional Ollama install and model; answers can be
  wrong. The current command sends only the question and has no project context.
- **Timing:** Implemented as `ask`; end-to-end model verification waits on an
  optional local Ollama install.

### Completed: explain safe Terraform findings with local AI

- **Priority:** High value.
- **Problem:** `ask` currently cannot see Terraform or AWS findings, so users
  must copy them into a separate question themselves.
- **Who benefits:** Beginners who want help interpreting the assistant's own
  verified outputs.
- **Difficulty:** Medium.
- **Running/API cost:** No API cost with Ollama; local compute only.
- **Dependencies and risks:** Pass only deliberately selected, secret-screened
  summaries. Keep model explanations separate from verified findings and never
  let model output execute commands.
- **Timing:** Implemented as `terraform-explain`. Tests confirm it passes only
  allowlisted static summaries. A live Ollama run remains to verify from the
  user's Terminal because the Codex execution environment cannot access the
  local service.

### Draft Terraform configurations with AI for review

- **Priority:** High value.
- **Problem:** Beginners need help turning infrastructure requirements into a
  Terraform starting point.
- **Who benefits:** Developers learning AWS and infrastructure as code.
- **Difficulty:** Medium to high; generated configurations need clear scope and
  reliable validation.
- **Running/API cost:** No API cost with the local model; local compute only.
- **Dependencies and risks:** Clearly label generated code as unverified.
  Optional saving must refuse to overwrite existing files and must never apply
  infrastructure. Run formatting and validation only when the user asks.
- **Timing:** Implemented as `terraform-draft`. Offline regression tests cover
  bounded input, safe prompt requirements, and explicit unverified messaging.
  Optional saving creates new `.tf` files only. The user confirmed local Ollama
  returns a draft; manual review and
  validation remain necessary before using generated HCL. The prompt also asks
  for a plain-language comment before each top-level block.
