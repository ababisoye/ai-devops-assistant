# DevOps Copilot

A standard-library-based command line assistant for beginner-friendly,
read-only DevOps checks across Terraform, GitHub Actions, and Dockerfiles, with
an optional Terraform parser. It requires Python
3.9 or newer.

## Run it

Install the CLI in editable mode from this checkout so the `devops-copilot`
command uses the current source as you update it:

```sh
python3 -m pip install -e .
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
python3 main.py terraform-review /path/to/terraform/module
python3 main.py terraform-review /path/to/terraform/module --explain --model llama3
python3 main.py terraform-explain /path/to/terraform/module --model llama3
python3 main.py terraform-draft 'Create a private S3 bucket' --model llama3
python3 main.py terraform-draft 'Create a private S3 bucket' --model llama3 --output ./main.tf
python3 main.py aws-security-groups --region us-east-1
python3 main.py ask 'What is Terraform state?'
python3 main.py git-status /path/to/repository
python3 main.py github-actions-check /path/to/project
python3 main.py dockerfile-check /path/to/project
python3 main.py project-review /path/to/project
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
when the optional parser is installed. It does not contact AWS or an AI service
or change infrastructure. AWS and AI command tests use mocked responses. The
script uses this project's `venv/` Python when available.

## Commands

The directory argument for `inspect`, `status`, `terraform`, `terraform-analyze`,
`terraform-review`, `terraform-explain`, and `git-status` is optional. If omitted,
each command uses the current directory.

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
- `terraform-review` runs the existing formatting and (when initialized)
  validation checks, followed by static analysis, in one local command. It does
  not call AWS or an AI service and does not modify files or infrastructure.
  Formatting or validation failures do not prevent static analysis from
  reporting what it can. It returns a nonzero status if any check fails. Add
  `--explain` to ask local Ollama for a beginner-friendly explanation of
  supported findings; without that option, it remains fully local and AI-free.
  The model receives only sanitized findings, not Terraform files, filenames,
  resource labels, variable values, or state. Choose an installed model with
  `--model`.
- `terraform-analyze` summarizes `.tf` and `.tf.json` declarations and reports
  whether a Terraform version constraint exists in the selected directory and
  its local subdirectories. Hidden, sensitive, generated, and symlinked
  directories/files are skipped. Findings show paths relative to the selected
  directory. JSON uses Python's built-in
  parser; HCL `.tf` analysis requires the optional parser extra above. When the
  parser is missing, HCL files are reported as skipped and the command returns
  a nonzero status. It does not print configuration values. For malformed JSON,
  it reports a line and column while suppressing file contents and parser text.
  It also flags potential internet-wide AWS security group ingress in JSON and
  HCL for common inline and standalone rule resources. This is static analysis:
  it cannot confirm deployed exposure and makes no AWS calls. Known protocol
  and port details are included; unresolved values are not printed. If an
  ingress CIDR cannot be resolved, the check says it is incomplete instead of
  reporting a clean result. It also flags literal `public-read` and
  `public-read-write` ACLs in common S3 bucket and object resources. Dynamic ACL
  values are marked incomplete. Bucket policies and grant blocks are outside
  this rule, and S3 Block Public Access settings may override an ACL finding;
  effective access remains unverified.
  It also reports explicitly false bucket-level settings in
  `aws_s3_bucket_public_access_block`; dynamic values are marked incomplete.
  Account or organization settings and effective access are not checked.
  For EBS, it flags explicit `encrypted = false` and unresolved encryption
  expressions in `aws_ebs_volume`, the `root_block_device` and `ebs_block_device`
  blocks in `aws_instance`, and EBS blocks in `aws_launch_template` block-device
  mappings. Account-level EBS encryption defaults may override the setting, and
  deployed encryption is not checked. Other resource types are outside this
  check. It also reports explicit `http_tokens = "optional"` metadata settings
  on `aws_instance` and `aws_launch_template`, which allow IMDSv1 compatibility.
  Dynamic token settings are marked incomplete. Account settings and launch
  overrides can affect the result; the analyzer does not inspect live instances.
  For `aws_db_instance`, it also flags an explicit
  `publicly_accessible = true` setting and unresolved expressions. Public
  accessibility alone does not prove internet reachability; subnet routing and
  security-group rules also matter, and this local check does not inspect them
  or deployed resources. It also flags explicit `storage_encrypted = false`
  and unresolved encryption expressions; the provider notes this setting is
  ignored for cross-region read replicas. It also identifies an explicit
  `deletion_protection = false`; this is a configuration fact, and AWS
  permissions are still required for deletion. It also reports
  `skip_final_snapshot = true`, which means a later Terraform deletion would
  not request a final snapshot; other backups are outside this check. See the
  [Terraform `aws_db_instance` reference](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/db_instance)
  and [Amazon RDS network security guidance](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/infrastructure-security.html).
  It also flags `backup_retention_period = 0`, which disables RDS automated
  backups where the setting applies; AWS Backup plans and other snapshots are
  not inspected. See [Amazon RDS backup retention guidance](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_WorkingWithAutomatedBackups.BackupRetention.html).
  For S3 buckets, it reports explicit versioning status `Suspended` or
  `Disabled` in `aws_s3_bucket_versioning`, and `enabled = false` in the legacy
  `aws_s3_bucket.versioning` block. Dynamic values are marked incomplete;
  configured status does not verify live bucket state. See the [Terraform S3
  versioning resource](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_versioning)
  and [S3 Versioning guidance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html).
  Static findings include the configuration filename and source line where the
  supported literal was found. Sensitive configuration filenames remain hidden.
- `terraform-explain` runs the same static analysis, then asks the local Ollama
  model to explain supported findings in beginner-friendly language. It passes
  only allowlisted summaries of supported findings, such as public ingress,
  public S3 canned ACLs and versioning, EBS encryption, optional IMDSv2 settings, or explicit
  RDS public-access, storage-encryption, deletion-protection, final-snapshot,
  and backup-retention settings. Terraform
  source, filenames, resource labels, variable values, and state are not sent to
  the model. The model explanation may be
  wrong; the static analyzer output above it remains the verified evidence.
  Analysis errors skip the AI request. It requires Ollama and the optional HCL
  parser when the module contains `.tf` files.
- `terraform-draft 'plain language requirements'` asks the local Ollama model
  to print an unverified Terraform HCL draft. It sends only the requirements
  you typed, not project files. By default it prints the draft. Use `--output
  path/to/file.tf` to save it as a new file; the command refuses to overwrite an
  existing file and does not create missing parent directories. It does not
  format, validate, or apply the draft. Review it carefully before using it;
  generated Terraform may be incomplete or wrong.
  The model is asked to add a short HCL comment before each top-level block to
  explain its purpose.
- `aws-security-groups` uses the AWS CLI's read-only
  `ec2 describe-security-group-rules` request to report internet-wide inbound
  IPv4 and IPv6 rules in the selected region. Install and configure the AWS CLI
  first; the identity it uses needs `ec2:DescribeSecurityGroupRules`. The
  command uses the AWS CLI's configured region unless `--region` is supplied.
  It does not print security group IDs, descriptions, credentials, or raw AWS
  errors. It does not test network reachability or change AWS resources. Running
  it contacts AWS; tests do not.
- `ask 'your question'` sends that question to an Ollama service on this Mac at
  `localhost:11434`. It does not scan project files or use a hosted AI API.
  Ollama must be installed and running, and the model must be downloaded. The
  default model is `qwen3:1.7b`; Ollama lists its download at about 1.4 GB.
  Actual memory use is higher and depends on the model and Mac, so responses may
  be slow on a low-memory computer. Choose another installed model with
  `--model`. If Ollama is unavailable, the other diagnostic commands still
  work. AI answers can be wrong and should be checked before acting on them.
- `git-status` shows short Git status, branch information, and counts of
  modified, added, deleted, and untracked files. Entries under hidden or
  commonly sensitive paths are suppressed from both the listing and counts.
  If Git cannot read the selected directory, the CLI suggests that it may not
  be a repository and suppresses Git's raw error output.
- `github-actions-check` reads local `.github/workflows/*.yml` and `.yaml`
  files and flags a top-level `permissions: write-all` line. It does not
  contact GitHub, execute workflows, parse or validate YAML, inspect effective
  permissions, or print workflow contents. This is one limited static check,
  not a complete workflow security review.
- `dockerfile-check` scans visible Dockerfiles in the selected project and
  flags `FROM` images with an implicit or explicit `latest` tag. Digest-pinned
  references and `scratch` are ignored; variable-based image references are
  reported as incomplete. It does not run Docker, build images, pull images,
  or establish whether a tagged image is trustworthy.
- `project-review` runs Terraform static analysis, the local GitHub Actions
  permission check, and the Dockerfile base-image check in one command. It
  continues through all three checks if one reports an issue and returns a
  nonzero exit status if any check fails. Individual checks may separately
  report incomplete analysis. It does not run
  Terraform, Docker, AWS, GitHub, or an AI model.

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

The CLI never prints environment variables, secret file contents, or
Terraform state contents. It never runs `terraform apply`, `terraform destroy`,
or any infrastructure-changing command. Terraform checks are local validation
commands; the CLI does not run `terraform init`. The AWS command makes a
read-only API request only when you run it. The AI `ask` command contacts only
the local Ollama endpoint. `ask` sends only the question you typed;
`terraform-draft` sends only the requirements you typed. If you provide
`--output`, it writes the model response to that new `.tf` file and refuses to
overwrite an existing path.

## Try it locally

Use the commands below to exercise the CLI against this checkout and any local
project or repository:

```sh
python3 main.py --help
python3 main.py inspect .
python3 main.py terraform .
python3 main.py terraform-explain examples/terraform-json --model llama3
python3 main.py terraform-draft 'Create a private S3 bucket' --model llama3
python3 main.py terraform-draft 'Create a private S3 bucket' --model llama3 --output ./main.tf
python3 main.py git-status .
python3 main.py ask 'What does terraform validate check?'
```

To enable `ask`, install [Ollama for macOS](https://ollama.com/download/mac),
then download the default model in Terminal:

```sh
ollama pull qwen3:1.7b
```

The default model download is about 1.4 GB. After Ollama is running, try `ask`
or `terraform-draft` again. Use `--model llama3` if that is the model you have
installed.
These setup steps are optional; they do not affect the other CLI commands.

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
