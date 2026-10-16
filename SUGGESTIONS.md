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

## Future ideas

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

### Optional AI explanation provider

- **Problem:** Static explanations may not cover unfamiliar errors.
- **Who benefits:** Users troubleshooting complex diagnostic output.
- **Difficulty:** High.
- **Running/API cost:** Potential usage-based API charges, or local hardware and
  maintenance costs.
- **Dependencies and risks:** Provider choice, secret scrubbing, data minimization,
  consent, and graceful operation without a provider.
- **Timing:** Defer until core diagnostics are useful without AI and cost and
  privacy options can be compared.
