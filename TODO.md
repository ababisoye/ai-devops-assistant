# Current Task

## Next task: review Terraform ingress findings on a representative module

The read-only public-ingress rule now analyzes common AWS security group
resources in Terraform JSON and HCL. Known protocol and port details are
summarized safely. Dynamic or malformed ingress CIDRs produce an incomplete
result instead of a clean claim, and their values are not printed.

The optional parser (`python-hcl2` 8.1.4) is installed in the project virtual
environment. The one-command test script runs the regression suite and both
included Terraform examples. All 46 tests passed, including tests using the
real parser.

### Acceptance criteria

- Try `terraform-analyze` on a representative local Terraform module.
- Check that findings are useful and do not disclose labels or configuration
  values.
- Record false positives, missing cases, or confusing wording before adding
  more security rules.

### Next actionable step

Run `./test.sh` from the project directory for a quick local check. To analyze
another module, run `venv/bin/python main.py terraform-analyze /path/to/module`
from the project directory, replacing the path with the module's folder. This
is local static analysis; it does not contact AWS or change infrastructure.
