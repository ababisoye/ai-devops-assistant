# DevOps Copilot

A standard-library-based command line assistant for beginner-friendly,
read-only DevOps checks, with an optional Terraform parser. It requires Python
3.9 or newer.

## Run it

Install the standard-library CLI from this checkout with:

```sh
python3 -m pip install .
```

To enable structured Terraform analysis, install the optional parser extra:

```sh
python3 -m pip install '.[terraform]'
```

The parser works locally; other CLI commands do not require it.

Check the installed CLI version with `devops-copilot --version`.

From this directory, run the CLI with Python:

```sh
python3 main.py --help
python3 main.py check
python3 main.py status /path/to/project
python3 main.py inspect /path/to/project
python3 main.py terraform /path/to/terraform/module
python3 main.py terraform-analyze /path/to/terraform/module
python3 main.py git-status /path/to/repository
```

You can also use the package entry point:

```sh
python3 -m devops_copilot.cli --help
```

## Quick test

From the project directory, run:

```sh
./test.sh
```

This runs the automated tests and analyzes the included JSON and HCL examples
when the optional parser is installed. It does not contact AWS or change
infrastructure. The script uses this project's `venv/` Python when available.

## Commands

The directory argument for `inspect`, `status`, `terraform`, `terraform-analyze`,
and `git-status` is optional. If omitted, each command uses the current
directory.

- `check` reports whether Git, Python, and Terraform are on `PATH` and can
  provide a recognizable version. It only runs each tool's version command;
  it does not change files or infrastructure. It returns a nonzero exit status
  if a tool is missing or its version cannot be checked.
- `status` gives a quick project overview using the same safe file summary as
  `inspect`. It does not run Git or Terraform checks.
- `inspect` counts visible files and directories and summarizes file extensions.
  It does not read file contents. Hidden paths, common secret/credential names,
  symlinks, Terraform state files, conventional Python virtual environment
  directories (`venv`, `env`, `virtualenv`), bytecode caches (`__pycache__`),
  and `node_modules` are excluded.
- `terraform` reports whether Terraform is installed. If the selected directory
  contains `.tf` or `.tf.json` files directly, it runs `terraform fmt -check`. It runs
  `terraform validate` only when the directory has a `.terraform` initialization
  directory. If validation is skipped, it explains that you can run
  `terraform init` manually; this may download provider plugins, and DevOps Copilot does
  not run initialization. Raw Terraform output is suppressed to avoid exposing sensitive
  diagnostics. A failed formatting check could indicate formatting differences
  or a syntax error, so repeat `terraform fmt -check` locally for details. A
  validation failure suggests running `terraform validate` locally for its
  detailed diagnostic. It summarizes visible configuration filenames but
  does not print configuration contents. It also gives a non-blocking
  recommendation if it cannot find a `required_version` constraint; unreadable
  files do not produce a recommendation. The hint looks for the assignment in
  a top-level `terraform` block and reports its filename and HCL line number
  when available. It is still a simple text-based check, not a full HCL parser;
  confirm the result manually before changing configuration.
- `terraform-analyze` summarizes `.tf` and `.tf.json` declarations and reports
  whether a Terraform version constraint exists. JSON uses Python's built-in
  parser; HCL `.tf` analysis requires the optional parser extra above. When the
  parser is missing, HCL files are reported as skipped and the command returns
  a nonzero status. It does not print configuration values. For malformed JSON,
  it reports a line and column while suppressing file contents and parser text.
  It also flags potential internet-wide AWS security group ingress in JSON and
  HCL for common inline and standalone rule resources. This is static analysis:
  it cannot confirm deployed exposure and makes no AWS calls. Known protocol
  and port details are included; unresolved values are not printed. If an
  ingress CIDR cannot be resolved, the check says it is incomplete instead of
  reporting a clean result.
- `git-status` shows short Git status, branch information, and counts of
  modified, added, deleted, and untracked files. Entries under hidden or
  commonly sensitive paths are suppressed from both the listing and counts.
  If Git cannot read the selected directory, the CLI suggests that it may not
  be a repository and suppresses Git's raw error output.

## Terraform command meanings

- `terraform validate` checks that the configuration is syntactically valid
  and internally consistent. It needs an initialized working directory, and
  it does not check remote services or predict infrastructure changes.
- `terraform plan` compares configuration with current state and previews
  proposed changes. It does not apply those changes, but may contact configured
  services to read current state.
- `terraform apply` carries out planned changes to infrastructure.
- `terraform destroy` removes infrastructure managed by the configuration.

DevOps Copilot only runs `fmt -check` and, when initialized, `validate`. It
never runs `plan`, `apply`, or `destroy`.

The CLI never reads or prints environment variables, secret file contents, or
Terraform state contents. It never runs `terraform apply`, `terraform destroy`,
or any infrastructure-changing command. Terraform checks are local validation
commands; the CLI does not run `terraform init`.

## Try it locally

Use the commands below to exercise the CLI against this checkout and any local
project or repository:

```sh
python3 main.py --help
python3 main.py inspect .
python3 main.py terraform .
python3 main.py git-status .
```

To try Terraform checks without a cloud provider or the optional HCL package,
use the included JSON-only example:

```sh
python3 main.py terraform-analyze examples/terraform-json
python3 main.py terraform examples/terraform-json
```

The formatting check runs locally. Validation is skipped because the example
has not been initialized; DevOps Copilot will not run `terraform init`.

An HCL example is also available for Terraform's formatting check:

```sh
python3 main.py terraform examples/terraform-hcl
```

To analyze that HCL file, install the optional `terraform` extra, then run
`venv/bin/python main.py terraform-analyze examples/terraform-hcl` when you
installed it in the project's virtual environment.

The Terraform and Git commands handle missing executables and unsuitable paths
with an explanatory message and a nonzero exit status where appropriate.
