"""Regression tests for the safe, read-only CLI commands."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import tempfile
import unittest
from urllib.error import URLError
from unittest.mock import MagicMock, patch

from devops_copilot import cli


class CliTests(unittest.TestCase):
    def run_captured(self, function, *args):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = function(*args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_help_lists_existing_commands(self):
        stdout = StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            cli.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        for command in ("inspect", "status", "check", "terraform", "terraform-analyze", "terraform-review", "terraform-explain", "terraform-draft", "aws-security-groups", "ask", "git-status", "github-actions-check", "dockerfile-check", "project-review"):
            self.assertIn(command, stdout.getvalue())

    def test_version_flag_reports_package_version(self):
        stdout = StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            cli.main(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(stdout.getvalue().strip(), "devops-copilot 0.1.0")

    def test_missing_command_is_rejected(self):
        with self.assertRaises(SystemExit) as raised:
            cli.main([])
        self.assertEqual(raised.exception.code, 2)

    def test_directory_commands_default_to_current_directory(self):
        for command in ("inspect", "status", "terraform", "terraform-analyze", "terraform-review", "terraform-explain", "git-status", "github-actions-check", "dockerfile-check", "project-review"):
            with self.subTest(command=command):
                args = cli.build_parser().parse_args([command])
                self.assertEqual(args.directory, ".")

    def test_inspect_reports_visible_files_but_not_sensitive_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "app.py").write_text("print('ok')\n")
            (root / ".env").write_text("SECRET_VALUE=do-not-print\n")
            (root / "credentials.json").write_text("do-not-print\n")
            (root / "terraform.tfstate").write_text("do-not-print\n")
            private_dir = root / "private"
            private_dir.mkdir()
            (private_dir / "visible.txt").write_text("do-not-print\n")
            for generated_name in ("venv", "env", "virtualenv", "__pycache__", "node_modules"):
                generated = root / generated_name
                generated.mkdir()
                (generated / "dependency.pyc").write_text("not project source\n")
            (root / ".hidden").mkdir()
            (root / ".hidden" / "hidden.txt").write_text("do-not-print\n")

            code, stdout, _ = self.run_captured(cli.inspect_project, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Files: 2", stdout)
        self.assertIn("Directories: 1", stdout)
        self.assertIn(".py: 1", stdout)
        self.assertIn(".txt: 1", stdout)
        for secret in ("SECRET_VALUE", "credentials.json", "terraform.tfstate", "hidden.txt"):
            self.assertNotIn(secret, stdout)

    def test_inspect_rejects_missing_directory(self):
        code, _, stderr = self.run_captured(cli.inspect_project, "/path/that/does/not/exist")
        self.assertEqual(code, 2)
        self.assertIn("does not exist", stderr)

    def test_inspect_walks_project_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "app.py").write_text("print('ok')\n")
            with patch.object(cli.os, "walk", wraps=cli.os.walk) as walk:
                code, _, _ = self.run_captured(cli.inspect_project, temp_dir)

        self.assertEqual(code, 0)
        walk.assert_called_once()

    def test_status_shows_read_only_overview_without_external_tools(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "app.py").write_text("print('ok')\n")
            with patch.object(cli.shutil, "which", side_effect=AssertionError("external tool lookup")), \
                    patch.object(cli.subprocess, "run", side_effect=AssertionError("external command")):
                code, stdout, _ = self.run_captured(cli.main, ["status", temp_dir])

        self.assertEqual(code, 0)
        self.assertIn("Files: 1", stdout)
        self.assertIn(".py: 1", stdout)

    def test_status_rejects_missing_directory(self):
        code, _, stderr = self.run_captured(cli.main, ["status", "/path/that/does/not/exist"])
        self.assertEqual(code, 2)
        self.assertIn("does not exist", stderr)

    def test_check_reports_available_tool_versions(self):
        paths = {"git": "/fake/git", "python3": "/fake/python3", "terraform": "/fake/terraform"}
        responses = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="git version 2.45.1\n", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="Python 3.9.6\n", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="Terraform v1.9.8\n", stderr=""),
        ]
        with patch.object(cli.shutil, "which", side_effect=paths.get), \
                patch.object(cli.subprocess, "run", side_effect=responses) as run:
            code, stdout, _ = self.run_captured(cli.main, ["check"])

        self.assertEqual(code, 0)
        self.assertIn("Git: available (version 2.45.1)", stdout)
        self.assertIn("Python: available (version 3.9.6)", stdout)
        self.assertIn("Terraform: available (version 1.9.8)", stdout)
        self.assertEqual(run.call_count, 3)

    def test_check_reports_missing_tool_and_returns_nonzero(self):
        paths = {"git": "/fake/git", "python3": "/fake/python3", "terraform": None}
        responses = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="git version 2.45.1\n", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="Python 3.9.6\n", stderr=""),
        ]
        with patch.object(cli.shutil, "which", side_effect=paths.get), \
                patch.object(cli.subprocess, "run", side_effect=responses) as run:
            code, stdout, _ = self.run_captured(cli.main, ["check"])

        self.assertEqual(code, 1)
        self.assertIn("Terraform: not found on PATH", stdout)
        self.assertEqual(run.call_count, 2)

    def test_check_suppresses_unexpected_version_command_output(self):
        paths = {"git": "/fake/git", "python3": None, "python": None, "terraform": None}
        failure = subprocess.CompletedProcess(args=[], returncode=0, stdout="private diagnostic", stderr="")
        with patch.object(cli.shutil, "which", side_effect=paths.get), \
                patch.object(cli.subprocess, "run", return_value=failure):
            code, stdout, _ = self.run_captured(cli.check_tools)

        self.assertEqual(code, 1)
        self.assertIn("Python: not found on PATH", stdout)
        self.assertIn("Terraform: not found on PATH", stdout)
        self.assertIn("Git: found on PATH but its version could not be determined", stdout)
        self.assertNotIn("private diagnostic", stdout)

    def test_terraform_rejects_missing_directory_before_tool_lookup(self):
        with patch.object(cli.shutil, "which") as which:
            code, _, stderr = self.run_captured(cli.terraform_check, "/path/that/does/not/exist")
        self.assertEqual(code, 2)
        self.assertIn("does not exist", stderr)
        which.assert_not_called()

    def test_terraform_review_runs_analysis_even_if_tool_checks_fail(self):
        with patch.object(cli, "terraform_check", return_value=1) as check, \
                patch.object(cli, "terraform_analyze", return_value=0) as analyze:
            code, stdout, stderr = self.run_captured(cli.terraform_review, "/terraform/module")

        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertIn("formatting and validation checks", stdout)
        self.assertIn("static analysis", stdout)
        check.assert_called_once_with("/terraform/module")
        analyze.assert_called_once_with("/terraform/module")

    def test_terraform_review_stops_after_invalid_directory(self):
        with patch.object(cli, "terraform_check", return_value=2) as check, \
                patch.object(cli, "terraform_analyze") as analyze:
            code, _, _ = self.run_captured(cli.terraform_review, "/missing")

        self.assertEqual(code, 2)
        check.assert_called_once_with("/missing")
        analyze.assert_not_called()

    def test_terraform_review_returns_failure_if_analysis_fails(self):
        with patch.object(cli, "terraform_check", return_value=0), \
                patch.object(cli, "terraform_analyze", return_value=1):
            code, stdout, _ = self.run_captured(cli.terraform_review, "/terraform/module")

        self.assertEqual(code, 1)
        self.assertNotIn("Review finished", stdout)

    def test_terraform_review_reports_completion_when_checks_succeed(self):
        with patch.object(cli, "terraform_check", return_value=0), \
                patch.object(cli, "terraform_analyze", return_value=0):
            code, stdout, _ = self.run_captured(cli.terraform_review, "/terraform/module")

        self.assertEqual(code, 0)
        self.assertIn("Review finished", stdout)

    def test_terraform_review_explains_only_sanitized_findings_when_requested(self):
        analyzer_report = (
            "Potential public ingress: private-user-network.tf contains an "
            "aws_security_group rule open to 0.0.0.0/0 "
            "(protocol tcp, ports 22-22). Static analysis cannot confirm deployed exposure."
        )
        def report_analysis(_directory):
            print(analyzer_report)
            return 0

        with patch.object(cli, "terraform_check", return_value=0), \
                patch.object(cli, "terraform_analyze", side_effect=report_analysis), \
                patch.object(cli, "ask_local_model", return_value=0) as ask:
            code, stdout, stderr = self.run_captured(
                cli.terraform_review, "/terraform/module", True, "llama3"
            )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("AI explanation", stdout)
        ask.assert_called_once()
        self.assertEqual(ask.call_args.args[1], "llama3")
        context = ask.call_args.kwargs["context"]
        self.assertIn("0.0.0.0/0", context)
        self.assertIn("ports 22-22", context)
        self.assertNotIn("private-user-network.tf", context)

    def test_terraform_review_skips_ai_when_analysis_fails(self):
        with patch.object(cli, "terraform_check", return_value=0), \
                patch.object(cli, "terraform_analyze", return_value=1), \
                patch.object(cli, "ask_local_model") as ask:
            code, stdout, _ = self.run_captured(
                cli.terraform_review, "/terraform/module", True, "llama3"
            )

        self.assertEqual(code, 1)
        self.assertIn("AI explanation skipped", stdout)
        ask.assert_not_called()

    def test_main_dispatches_terraform_review(self):
        with patch.object(cli, "terraform_review", return_value=0) as review:
            code = cli.main([
                "terraform-review", "/terraform/module", "--explain", "--model", "llama3"
            ])

        self.assertEqual(code, 0)
        review.assert_called_once_with("/terraform/module", True, "llama3")

    def test_terraform_reports_missing_tool(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(cli.shutil, "which", return_value=None):
            code, stdout, _ = self.run_captured(cli.terraform_check, temp_dir)
        self.assertEqual(code, 1)
        self.assertIn("Terraform is not installed", stdout)

    def test_terraform_checks_format_and_validate_without_exposing_tool_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "main.tf").write_text("resource {}\n")
            (root / ".terraform").mkdir()
            result = subprocess.CompletedProcess(
                args=["terraform"], returncode=1, stdout="secret output", stderr="private detail"
            )
            with patch.object(cli.shutil, "which", return_value="/fake/terraform"), \
                    patch.object(cli.subprocess, "run", return_value=result) as run:
                code, stdout, _ = self.run_captured(cli.terraform_check, temp_dir)

        self.assertEqual(code, 1)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0], ["/fake/terraform", "fmt", "-check"])
        self.assertEqual(run.call_args_list[1].args[0], ["/fake/terraform", "validate"])
        self.assertIn("raw tool output was suppressed", stdout)
        self.assertIn("formatting or a configuration syntax error", stdout)
        self.assertIn("run 'terraform validate'", stdout)
        self.assertNotIn("secret output", stdout)
        self.assertNotIn("private detail", stdout)

    def test_terraform_fmt_failure_does_not_assume_formatting_is_the_problem(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "main.tf").write_text("not valid Terraform\n")
            failure = subprocess.CompletedProcess(
                args=["terraform"], returncode=1, stdout="sensitive source", stderr="syntax details"
            )
            with patch.object(cli.shutil, "which", return_value="/fake/terraform"), \
                    patch.object(cli.subprocess, "run", return_value=failure):
                code, stdout, _ = self.run_captured(cli.terraform_check, temp_dir)

        self.assertEqual(code, 1)
        self.assertIn("formatting or a configuration syntax error", stdout)
        self.assertNotIn("Formatting differences were found", stdout)
        self.assertNotIn("sensitive source", stdout)
        self.assertNotIn("syntax details", stdout)

    def test_terraform_analyze_reports_missing_optional_parser(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf").write_text("resource {}\n")
            with patch.object(cli.importlib, "import_module", side_effect=ImportError):
                code, _, stderr = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 1)
        self.assertIn("python3 -m pip install '.[terraform]'", stderr)

    def test_terraform_analyze_continues_json_when_hcl_parser_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "main.tf").write_text('resource "example" "one" {}\n')
            (root / "extra.tf.json").write_text(
                '{"terraform":{"required_version":">= 1.5"},'
                '"resource":{"example":{"two":{}}}}\n'
            )
            with patch.object(cli.importlib, "import_module", side_effect=ImportError):
                code, stdout, stderr = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 1)
        self.assertIn("HCL analysis requires the optional parser", stderr)
        self.assertIn("Terraform configuration files analyzed: 1/2", stdout)
        self.assertIn("HCL files skipped: 1", stdout)
        self.assertIn("Terraform version constraint: found", stdout)
        self.assertNotIn('">= 1.5"', stdout)

    def test_terraform_analyze_summarizes_declarations_without_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "main.tf").write_text("sensitive configuration text\n")
            (root / "credentials.tf").write_text("hidden configuration text\n")
            parser = SimpleNamespace(load=lambda stream: {
                "resource": [{"aws_instance": {"web": {"ami": "PRIVATE_AMI"}}}],
                "variable": [{"region": {"default": "PRIVATE_REGION"}}],
                "terraform": [{"required_version": '">= 1.0"'}],
            })
            with patch.object(cli.importlib, "import_module", return_value=parser) as load_parser:
                code, stdout, _ = self.run_captured(cli.main, ["terraform-analyze", temp_dir])

        self.assertEqual(code, 0)
        self.assertIn("Terraform configuration files analyzed: 1/1", stdout)
        self.assertIn("Declaration types: resource, terraform, variable", stdout)
        self.assertIn("Terraform version constraint: found", stdout)
        self.assertIn("1 sensitive configuration filename(s) suppressed", stdout)
        self.assertNotIn("PRIVATE_AMI", stdout)
        self.assertNotIn("PRIVATE_REGION", stdout)
        self.assertNotIn("credentials.tf", stdout)
        load_parser.assert_called_once_with("hcl2")

    def test_terraform_analyze_summarizes_json_configuration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf.json").write_text(
                '{"terraform":{"required_version":">= 1.5"},'
                '"resource":{"aws_s3_bucket":{"logs":{}}}}\n'
            )
            with patch.object(cli.importlib, "import_module", side_effect=AssertionError("HCL parser imported")):
                code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Declaration types: resource, terraform", stdout)
        self.assertIn("Terraform version constraint: found", stdout)
        self.assertNotIn(">= 1.5", stdout)

    def test_terraform_analyze_includes_nested_modules_and_skips_generated_or_sensitive_dirs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "modules" / "network"
            nested.mkdir(parents=True)
            (nested / "main.tf.json").write_text(
                '{"resource":{"aws_security_group":{"hidden_label":{'
                '"ingress":[{"protocol":"tcp","from_port":443,"to_port":443,'
                '"cidr_blocks":["0.0.0.0/0"]}]}}}}\n'
            )
            generated = root / ".terraform" / "modules"
            generated.mkdir(parents=True)
            (generated / "ignored.tf.json").write_text('{"provider":{}}\n')
            secret = root / "secrets"
            secret.mkdir()
            (secret / "ignored.tf.json").write_text('{"provider":{}}\n')

            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Terraform configuration files analyzed: 1/1", stdout)
        self.assertIn("file: modules/network/main.tf.json", stdout)
        self.assertNotIn("ignored.tf.json", stdout)
        self.assertNotIn("hidden_label", stdout)

    def test_terraform_analyze_finds_public_ingress_in_supported_json_resources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf.json").write_text(
                '{"resource": {'
                '"aws_security_group": {"private_label": {"ingress": ['
                '{"protocol": "tcp", "from_port": 443, "to_port": 443,'
                ' "cidr_blocks": ["0.0.0.0/0"], "ipv6_cidr_blocks": ["::/0"]}] }},'
                '"aws_security_group_rule": {'
                '"another_private_label": {"type": "ingress", "protocol": "udp",'
                ' "from_port": 53, "to_port": 53, "cidr_blocks": ["0.0.0.0/0"]},'
                '"egress_label": {"type": "egress", "cidr_blocks": ["0.0.0.0/0"]}},'
                '"aws_vpc_security_group_ingress_rule": {'
                '"third_private_label": {"ip_protocol": "tcp", "from_port": 22,'
                ' "to_port": 22, "cidr_ipv4": "0.0.0.0/0", "cidr_ipv6": "::/0"}}}}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Potential public ingress", stdout)
        self.assertIn("0.0.0.0/0", stdout)
        self.assertIn("::/0", stdout)
        self.assertIn("protocol tcp, ports 443-443", stdout)
        self.assertIn("protocol udp, ports 53-53", stdout)
        self.assertIn("protocol tcp, ports 22-22", stdout)
        self.assertIn("Static analysis cannot confirm deployed exposure", stdout)
        self.assertNotIn("private_label", stdout)
        self.assertNotIn("another_private_label", stdout)
        self.assertNotIn("egress_label", stdout)

    def test_terraform_analyze_flags_public_s3_acls_and_hides_expressions(self):
        configuration = {
            "resource": {
                "aws_s3_bucket": {
                    "public_read_bucket": {"acl": "public-read"},
                    "private_bucket": {"acl": "private"},
                    "dynamic_bucket": {"acl": "${var.sensitive_acl}"},
                },
                "aws_s3_bucket_acl": {
                    "public_write_bucket": {"acl": "public-read-write"},
                },
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf.json").write_text(json.dumps(configuration))
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("aws_s3_bucket uses public-read", stdout)
        self.assertIn("aws_s3_bucket_acl uses public-read-write", stdout)
        self.assertIn("S3 ACL check incomplete", stdout)
        self.assertIn("Block Public Access settings may override it", stdout)
        self.assertNotIn("public_read_bucket", stdout)
        self.assertNotIn("public_write_bucket", stdout)
        self.assertNotIn("sensitive_acl", stdout)

    def test_terraform_analyze_flags_public_s3_acls_in_hcl(self):
        try:
            cli.importlib.import_module("hcl2")
        except ImportError:
            self.skipTest("optional python-hcl2 extra is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "storage.tf").write_text(
                'resource "aws_s3_bucket" "hidden_read_label" {\n'
                '  acl = "public-read"\n'
                '}\n'
                'resource "aws_s3_bucket_acl" "hidden_write_label" {\n'
                '  acl = "public-read-write"\n'
                '}\n'
                'resource "aws_s3_bucket" "private_label" {\n'
                '  acl = "private"\n'
                '}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("aws_s3_bucket uses public-read", stdout)
        self.assertIn("aws_s3_bucket_acl uses public-read-write", stdout)
        self.assertIn("file: storage.tf, line: 2", stdout)
        self.assertIn("file: storage.tf, line: 5", stdout)
        self.assertNotIn("hidden_read_label", stdout)
        self.assertNotIn("hidden_write_label", stdout)
        self.assertNotIn("private_label", stdout)

    def test_terraform_analyze_flags_explicitly_disabled_s3_public_access(self):
        configuration = {
            "resource": {
                "aws_s3_bucket_public_access_block": {
                    "private_label": {
                        "block_public_acls": True,
                        "block_public_policy": False,
                        "ignore_public_acls": "${var.hidden_setting}",
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf.json").write_text(json.dumps(configuration))
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("sets block_public_policy = false", stdout)
        self.assertIn("S3 public-access block check incomplete", stdout)
        self.assertIn("effective access were not checked", stdout)
        self.assertNotIn("private_label", stdout)
        self.assertNotIn("hidden_setting", stdout)

    def test_terraform_analyze_flags_explicitly_disabled_s3_public_access_in_hcl(self):
        try:
            cli.importlib.import_module("hcl2")
        except ImportError:
            self.skipTest("optional python-hcl2 extra is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "storage.tf").write_text(
                'resource "aws_s3_bucket_public_access_block" "hidden_label" {\n'
                '  block_public_acls       = true\n'
                '  block_public_policy     = false\n'
                '  ignore_public_acls      = true\n'
                '  restrict_public_buckets = true\n'
                '}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("sets block_public_policy = false", stdout)
        self.assertIn("file: storage.tf, line: 3", stdout)
        self.assertNotIn("hidden_label", stdout)
        self.assertNotIn("S3 public-access block check incomplete", stdout)

    def test_terraform_analyze_flags_s3_versioning_not_enabled(self):
        configuration = {
            "resource": {
                "aws_s3_bucket_versioning": {
                    "hidden_label": {"versioning_configuration": [{"status": "Suspended"}]},
                    "dynamic_label": {"versioning_configuration": [{"status": "${var.hidden_status}"}]},
                },
                "aws_s3_bucket": {
                    "legacy_label": {"versioning": [{"enabled": False}]},
                },
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = json.dumps(configuration, indent=2)
            (Path(temp_dir) / "storage.tf.json").write_text(source)
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("S3 bucket versioning is suspended", stdout)
        self.assertIn("S3 bucket versioning is explicitly disabled", stdout)
        self.assertIn("S3 versioning check incomplete", stdout)
        self.assertIn("live bucket state were not assessed", stdout)
        self.assertNotIn("hidden_label", stdout)
        self.assertNotIn("legacy_label", stdout)
        self.assertNotIn("hidden_status", stdout)

    def test_terraform_analyze_flags_suspended_s3_versioning_in_hcl(self):
        try:
            cli.importlib.import_module("hcl2")
        except ImportError:
            self.skipTest("optional python-hcl2 extra is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "storage.tf").write_text(
                'resource "aws_s3_bucket_versioning" "hidden_label" {\n'
                '  bucket = "example"\n'
                '  versioning_configuration {\n'
                '    status = "Suspended"\n'
                '  }\n'
                '}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("S3 bucket versioning is suspended", stdout)
        self.assertIn("file: storage.tf, line: 4", stdout)
        self.assertNotIn("hidden_label", stdout)
        self.assertNotIn("S3 versioning check incomplete", stdout)

    def test_terraform_analyze_flags_explicitly_unencrypted_ebs_volumes(self):
        configuration = {
            "resource": {
                "aws_ebs_volume": {
                    "hidden_unencrypted_label": {"encrypted": False},
                    "encrypted_label": {"encrypted": True},
                    "dynamic_label": {"encrypted": "${var.hidden_value}"},
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = json.dumps(configuration, indent=2)
            (Path(temp_dir) / "main.tf.json").write_text(source)
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("aws_ebs_volume explicitly sets encrypted = false", stdout)
        encrypted_line = next(
            index for index, line in enumerate(source.splitlines(), start=1)
            if '"encrypted": false' in line
        )
        self.assertIn(f"file: main.tf.json, line: {encrypted_line})", stdout)
        self.assertIn("EBS encryption check incomplete", stdout)
        self.assertIn("Account-level EBS encryption by default may override", stdout)
        self.assertNotIn("hidden_unencrypted_label", stdout)
        self.assertNotIn("hidden_value", stdout)

    def test_terraform_analyze_flags_explicitly_unencrypted_ebs_volumes_in_hcl(self):
        try:
            cli.importlib.import_module("hcl2")
        except ImportError:
            self.skipTest("optional python-hcl2 extra is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "storage.tf").write_text(
                'resource "aws_ebs_volume" "hidden_label" {\n'
                '  availability_zone = "us-east-1a"\n'
                '  size               = 10\n'
                '  encrypted          = false\n'
                '}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("aws_ebs_volume explicitly sets encrypted = false", stdout)
        self.assertIn("file: storage.tf, line: 4", stdout)
        self.assertNotIn("hidden_label", stdout)
        self.assertNotIn("EBS encryption check incomplete", stdout)

    def test_terraform_analyze_flags_unencrypted_instance_block_devices(self):
        configuration = {
            "resource": {
                "aws_instance": {
                    "hidden_instance_label": {
                        "root_block_device": [{"encrypted": False}],
                        "ebs_block_device": [
                            {"encrypted": True},
                            {"encrypted": "${var.hidden_encryption}"},
                        ],
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf.json").write_text(json.dumps(configuration))
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("aws_instance.root_block_device explicitly sets encrypted = false", stdout)
        self.assertIn("file: main.tf.json", stdout)
        self.assertIn("EBS encryption check incomplete", stdout)
        self.assertNotIn("hidden_instance_label", stdout)
        self.assertNotIn("hidden_encryption", stdout)

    def test_terraform_analyze_flags_unencrypted_instance_block_devices_in_hcl(self):
        try:
            cli.importlib.import_module("hcl2")
        except ImportError:
            self.skipTest("optional python-hcl2 extra is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "instance.tf").write_text(
                'resource "aws_instance" "hidden_label" {\n'
                '  root_block_device {\n'
                '    encrypted = false\n'
                '  }\n'
                '  ebs_block_device {\n'
                '    encrypted = true\n'
                '  }\n'
                '}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("aws_instance.root_block_device explicitly sets encrypted = false", stdout)
        self.assertIn("file: instance.tf, line: 3", stdout)
        self.assertNotIn("hidden_label", stdout)
        self.assertNotIn("EBS encryption check incomplete", stdout)

    def test_terraform_analyze_flags_unencrypted_launch_template_volumes(self):
        configuration = {
            "resource": {
                "aws_launch_template": {
                    "hidden_template_label": {
                        "block_device_mappings": [
                            {"ebs": [{"encrypted": False}]},
                            {"ebs": [{"encrypted": "${var.hidden_encryption}"}]},
                        ]
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf.json").write_text(json.dumps(configuration))
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn(
            "aws_launch_template.block_device_mappings.ebs explicitly sets encrypted = false",
            stdout,
        )
        self.assertIn("file: main.tf.json", stdout)
        self.assertIn("EBS encryption check incomplete", stdout)
        self.assertNotIn("hidden_template_label", stdout)
        self.assertNotIn("hidden_encryption", stdout)

    def test_terraform_analyze_flags_unencrypted_launch_template_volumes_in_hcl(self):
        try:
            cli.importlib.import_module("hcl2")
        except ImportError:
            self.skipTest("optional python-hcl2 extra is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "launch-template.tf").write_text(
                'resource "aws_launch_template" "hidden_label" {\n'
                '  block_device_mappings {\n'
                '    device_name = "/dev/sdh"\n'
                '    ebs {\n'
                '      encrypted = false\n'
                '    }\n'
                '  }\n'
                '}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn(
            "aws_launch_template.block_device_mappings.ebs explicitly sets encrypted = false",
            stdout,
        )
        self.assertIn("file: launch-template.tf, line: 5", stdout)
        self.assertNotIn("hidden_label", stdout)
        self.assertNotIn("EBS encryption check incomplete", stdout)

    def test_terraform_analyze_flags_optional_imdsv2_settings(self):
        configuration = {
            "resource": {
                "aws_instance": {
                    "hidden_instance_label": {
                        "metadata_options": [{"http_tokens": "optional"}]
                    },
                    "required_instance": {
                        "metadata_options": [{"http_tokens": "required"}]
                    },
                },
                "aws_launch_template": {
                    "hidden_template_label": {
                        "metadata_options": [{"http_tokens": "optional"}]
                    },
                    "dynamic_template": {
                        "metadata_options": [{"http_tokens": "${var.hidden_tokens}"}]
                    },
                },
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = json.dumps(configuration, indent=2)
            (Path(temp_dir) / "main.tf.json").write_text(source)
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Potential IMDSv1 allowed: aws_instance sets", stdout)
        self.assertIn("Potential IMDSv1 allowed: aws_launch_template sets", stdout)
        optional_lines = [
            index for index, line in enumerate(source.splitlines(), start=1)
            if '"http_tokens": "optional"' in line
        ]
        for line in optional_lines:
            self.assertIn(f"file: main.tf.json, line: {line})", stdout)
        self.assertIn("IMDS token setting check incomplete", stdout)
        self.assertNotIn("hidden_instance_label", stdout)
        self.assertNotIn("hidden_template_label", stdout)
        self.assertNotIn("hidden_tokens", stdout)

    def test_terraform_analyze_flags_optional_imdsv2_settings_in_hcl(self):
        try:
            cli.importlib.import_module("hcl2")
        except ImportError:
            self.skipTest("optional python-hcl2 extra is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "compute.tf").write_text(
                'resource "aws_instance" "hidden_instance" {\n'
                '  metadata_options {\n'
                '    http_tokens = "optional"\n'
                '  }\n'
                '}\n'
                'resource "aws_launch_template" "hidden_template" {\n'
                '  metadata_options {\n'
                '    http_tokens = "required"\n'
                '  }\n'
                '}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Potential IMDSv1 allowed: aws_instance sets", stdout)
        self.assertIn("file: compute.tf, line: 3", stdout)
        self.assertNotIn("Potential IMDSv1 allowed: aws_launch_template", stdout)
        self.assertNotIn("hidden_instance", stdout)
        self.assertNotIn("IMDS token setting check incomplete", stdout)

    def test_terraform_analyze_flags_explicit_public_rds_access_and_hides_values(self):
        configuration = {
            "resource": {
                "aws_db_instance": {
                    "private_label": {"publicly_accessible": False},
                    "public_label": {"publicly_accessible": True},
                    "dynamic_label": {"publicly_accessible": "${var.private_setting}"},
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = json.dumps(configuration, indent=2)
            (Path(temp_dir) / "database.tf.json").write_text(source)
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Potential publicly accessible RDS configuration", stdout)
        self.assertIn("requests public accessibility", stdout)
        self.assertIn("reachability also depends on subnet routing and network rules", stdout)
        public_line = next(
            index for index, line in enumerate(source.splitlines(), start=1)
            if '"publicly_accessible": true' in line
        )
        self.assertIn(f"file: database.tf.json, line: {public_line})", stdout)
        self.assertIn("RDS public-access check incomplete", stdout)
        self.assertNotIn("private_label", stdout)
        self.assertNotIn("public_label", stdout)
        self.assertNotIn("private_setting", stdout)

    def test_terraform_analyze_flags_explicit_public_rds_access_in_hcl(self):
        try:
            cli.importlib.import_module("hcl2")
        except ImportError:
            self.skipTest("optional python-hcl2 extra is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "database.tf").write_text(
                'resource "aws_db_instance" "hidden_public_label" {\n'
                '  publicly_accessible = true\n'
                '}\n'
                'resource "aws_db_instance" "hidden_private_label" {\n'
                '  publicly_accessible = false\n'
                '}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Potential publicly accessible RDS configuration", stdout)
        self.assertIn("file: database.tf, line: 2", stdout)
        self.assertNotIn("hidden_public_label", stdout)
        self.assertNotIn("hidden_private_label", stdout)

    def test_terraform_analyze_flags_explicit_unencrypted_rds_storage(self):
        configuration = {
            "resource": {
                "aws_db_instance": {
                    "private_label": {"storage_encrypted": True},
                    "unencrypted_label": {"storage_encrypted": False},
                    "dynamic_label": {"storage_encrypted": "${var.hidden_encryption}"},
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = json.dumps(configuration, indent=2)
            (Path(temp_dir) / "database.tf.json").write_text(source)
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Potential unencrypted RDS storage: aws_db_instance", stdout)
        self.assertIn("cross-region read-replica behavior may differ", stdout)
        self.assertIn("RDS storage-encryption check incomplete", stdout)
        unencrypted_line = next(
            index for index, line in enumerate(source.splitlines(), start=1)
            if '"storage_encrypted": false' in line
        )
        self.assertIn(f"file: database.tf.json, line: {unencrypted_line})", stdout)
        self.assertNotIn("unencrypted_label", stdout)
        self.assertNotIn("hidden_encryption", stdout)

    def test_terraform_analyze_flags_explicit_unencrypted_rds_storage_in_hcl(self):
        try:
            cli.importlib.import_module("hcl2")
        except ImportError:
            self.skipTest("optional python-hcl2 extra is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "database.tf").write_text(
                'resource "aws_db_instance" "hidden_label" {\n'
                '  storage_encrypted = false\n'
                '}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Potential unencrypted RDS storage", stdout)
        self.assertIn("file: database.tf, line: 2", stdout)
        self.assertNotIn("hidden_label", stdout)

    def test_terraform_analyze_flags_explicitly_disabled_rds_deletion_protection(self):
        configuration = {
            "resource": {
                "aws_db_instance": {
                    "protected_label": {"deletion_protection": True},
                    "disabled_label": {"deletion_protection": False},
                    "dynamic_label": {"deletion_protection": "${var.hidden_protection}"},
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = json.dumps(configuration, indent=2)
            (Path(temp_dir) / "database.tf.json").write_text(source)
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Potential RDS deletion protection disabled", stdout)
        self.assertIn("AWS permissions are still required", stdout)
        self.assertIn("RDS deletion-protection check incomplete", stdout)
        protection_line = next(
            index for index, line in enumerate(source.splitlines(), start=1)
            if '"deletion_protection": false' in line
        )
        self.assertIn(f"file: database.tf.json, line: {protection_line})", stdout)
        self.assertNotIn("disabled_label", stdout)
        self.assertNotIn("hidden_protection", stdout)

    def test_terraform_analyze_flags_disabled_rds_deletion_protection_in_hcl(self):
        try:
            cli.importlib.import_module("hcl2")
        except ImportError:
            self.skipTest("optional python-hcl2 extra is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "database.tf").write_text(
                'resource "aws_db_instance" "hidden_label" {\n'
                '  deletion_protection = false\n'
                '}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Potential RDS deletion protection disabled", stdout)
        self.assertIn("file: database.tf, line: 2", stdout)
        self.assertNotIn("hidden_label", stdout)

    def test_terraform_analyze_flags_rds_skipping_final_snapshot(self):
        configuration = {
            "resource": {
                "aws_db_instance": {
                    "snapshot_enabled": {"skip_final_snapshot": False},
                    "snapshot_skipped": {"skip_final_snapshot": True},
                    "dynamic_label": {"skip_final_snapshot": "${var.hidden_snapshot_setting}"},
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = json.dumps(configuration, indent=2)
            (Path(temp_dir) / "database.tf.json").write_text(source)
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Potential RDS final snapshot skipped", stdout)
        self.assertIn("no final snapshot is requested", stdout)
        self.assertIn("RDS final-snapshot check incomplete", stdout)
        snapshot_line = next(
            index for index, line in enumerate(source.splitlines(), start=1)
            if '"skip_final_snapshot": true' in line
        )
        self.assertIn(f"file: database.tf.json, line: {snapshot_line})", stdout)
        self.assertNotIn("snapshot_skipped", stdout)
        self.assertNotIn("hidden_snapshot_setting", stdout)

    def test_terraform_analyze_flags_rds_skipping_final_snapshot_in_hcl(self):
        try:
            cli.importlib.import_module("hcl2")
        except ImportError:
            self.skipTest("optional python-hcl2 extra is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "database.tf").write_text(
                'resource "aws_db_instance" "hidden_label" {\n'
                '  skip_final_snapshot = true\n'
                '}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Potential RDS final snapshot skipped", stdout)
        self.assertIn("file: database.tf, line: 2", stdout)
        self.assertNotIn("hidden_label", stdout)

    def test_terraform_analyze_flags_zero_rds_backup_retention(self):
        configuration = {
            "resource": {
                "aws_db_instance": {
                    "backup_enabled": {"backup_retention_period": 7},
                    "backup_disabled": {"backup_retention_period": 0},
                    "dynamic_label": {"backup_retention_period": "${var.hidden_retention}"},
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = json.dumps(configuration, indent=2)
            (Path(temp_dir) / "database.tf.json").write_text(source)
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Potential RDS automated backups disabled", stdout)
        self.assertIn("AWS Backup plans and other snapshots were not assessed", stdout)
        self.assertIn("RDS automated-backup check incomplete", stdout)
        retention_line = next(
            index for index, line in enumerate(source.splitlines(), start=1)
            if '"backup_retention_period": 0' in line
        )
        self.assertIn(f"file: database.tf.json, line: {retention_line})", stdout)
        self.assertNotIn("backup_disabled", stdout)
        self.assertNotIn("hidden_retention", stdout)

    def test_terraform_analyze_flags_zero_rds_backup_retention_in_hcl(self):
        try:
            cli.importlib.import_module("hcl2")
        except ImportError:
            self.skipTest("optional python-hcl2 extra is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "database.tf").write_text(
                'resource "aws_db_instance" "hidden_label" {\n'
                '  backup_retention_period = 0\n'
                '}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Potential RDS automated backups disabled", stdout)
        self.assertIn("file: database.tf, line: 2", stdout)
        self.assertNotIn("hidden_label", stdout)

    def test_terraform_explanation_context_sanitizes_public_rds_finding(self):
        report = (
            "Potential publicly accessible RDS configuration: aws_db_instance sets "
            "publicly_accessible = true. This requests public accessibility; "
            "reachability also depends on subnet routing and network rules. "
            "Static analysis did not inspect deployed state. (file: private.tf, "
            "line: 7)."
        )

        context = cli.safe_terraform_explanation_context(report)

        self.assertIn("publicly_accessible=true", context)
        self.assertIn("reachability depends on subnet routing and network rules", context)
        self.assertNotIn("private.tf", context)

    def test_terraform_explanation_context_sanitizes_unencrypted_rds_finding(self):
        report = (
            "Potential unencrypted RDS storage: aws_db_instance explicitly sets "
            "storage_encrypted = false. This is a static configuration finding; "
            "cross-region read-replica behavior may differ, and deployed encryption "
            "was not checked. (file: private.tf, line: 3)."
        )

        context = cli.safe_terraform_explanation_context(report)

        self.assertIn("storage_encrypted=false", context)
        self.assertIn("deployed encryption was not checked", context)
        self.assertNotIn("private.tf", context)

    def test_terraform_explanation_context_sanitizes_rds_deletion_protection(self):
        report = (
            "Potential RDS deletion protection disabled: aws_db_instance explicitly "
            "sets deletion_protection = false. AWS permissions are still required "
            "to delete a database; live settings were not checked. "
            "(file: private.tf, line: 3)."
        )

        context = cli.safe_terraform_explanation_context(report)

        self.assertIn("deletion_protection=false", context)
        self.assertIn("AWS permissions are still required", context)
        self.assertNotIn("private.tf", context)

    def test_terraform_explanation_context_sanitizes_rds_final_snapshot_finding(self):
        report = (
            "Potential RDS final snapshot skipped: aws_db_instance explicitly sets "
            "skip_final_snapshot = true. If Terraform later deletes this instance, "
            "no final snapshot is requested; other backups were not assessed. "
            "(file: private.tf, line: 3)."
        )

        context = cli.safe_terraform_explanation_context(report)

        self.assertIn("skip_final_snapshot=true", context)
        self.assertIn("would not request a final snapshot", context)
        self.assertNotIn("private.tf", context)

    def test_terraform_explanation_context_sanitizes_rds_automated_backup_finding(self):
        report = (
            "Potential RDS automated backups disabled: aws_db_instance explicitly "
            "sets backup_retention_period = 0. This disables RDS automated backups "
            "where the setting applies; AWS Backup plans and other snapshots were "
            "not assessed. (file: private.tf, line: 3)."
        )

        context = cli.safe_terraform_explanation_context(report)

        self.assertIn("backup_retention_period=0", context)
        self.assertIn("AWS Backup plans and other snapshots were not assessed", context)
        self.assertNotIn("private.tf", context)

    def test_terraform_analyze_finds_public_ingress_in_parsed_hcl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf").write_text("private configuration\n")
            parser_result = {
                "resource": [
                    {'"aws_security_group"': {'"hidden_label"': {
                        "ingress": [{
                            "protocol": '"tcp"', "from_port": 443, "to_port": 443,
                            "cidr_blocks": ['"0.0.0.0/0"'], "__is_block__": True,
                        }],
                        "__is_block__": True,
                    }}},
                    {'"aws_security_group_rule"': {'"also_hidden"': {
                        "type": '"ingress"', "protocol": '"icmp"',
                        "from_port": 8, "to_port": 0,
                        "ipv6_cidr_blocks": ['"::/0"'],
                    }}},
                ]
            }
            parser = SimpleNamespace(load=lambda stream: parser_result)
            with patch.object(cli.importlib, "import_module", return_value=parser):
                code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Potential public ingress", stdout)
        self.assertIn("protocol tcp, ports 443-443", stdout)
        self.assertIn("protocol icmp, type/code 8/0", stdout)
        self.assertIn("Terraform configuration files analyzed: 1/1", stdout)
        self.assertNotIn("hidden_label", stdout)
        self.assertNotIn("private configuration", stdout)

    def test_terraform_analyze_real_hcl_parser_when_installed(self):
        try:
            cli.importlib.import_module("hcl2")
        except ImportError:
            self.skipTest("optional python-hcl2 extra is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf").write_text(
                'resource "aws_security_group" "hidden_label" {\n'
                '  ingress {\n'
                '    protocol = "tcp"\n'
                '    from_port = 443\n'
                '    to_port = 443\n'
                '    cidr_blocks = ["0.0.0.0/0"]\n'
                '  }\n'
                '}\n'
                'resource "aws_security_group_rule" "legacy_label" {\n'
                '  type = "ingress"\n'
                '  protocol = "udp"\n'
                '  from_port = 53\n'
                '  to_port = 53\n'
                '  cidr_blocks = ["0.0.0.0/0"]\n'
                '}\n'
                'resource "aws_security_group_rule" "egress_label" {\n'
                '  type = "egress"\n'
                '  protocol = "tcp"\n'
                '  from_port = 0\n'
                '  to_port = 65535\n'
                '  cidr_blocks = ["0.0.0.0/0"]\n'
                '}\n'
                'resource "aws_vpc_security_group_ingress_rule" "modern_label" {\n'
                '  ip_protocol = "-1"\n'
                '  from_port = 0\n'
                '  to_port = 0\n'
                '  cidr_ipv4 = "0.0.0.0/0"\n'
                '}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Potential public ingress", stdout)
        self.assertIn("protocol tcp, ports 443-443", stdout)
        self.assertIn("protocol udp, ports 53-53", stdout)
        self.assertIn("protocol -1 (all protocols; all ports)", stdout)
        self.assertIn("file: main.tf, line: 6", stdout)
        self.assertIn("file: main.tf, line: 14)", stdout)
        self.assertIn("file: main.tf, line: 27)", stdout)
        for label in ("hidden_label", "legacy_label", "egress_label", "modern_label"):
            self.assertNotIn(label, stdout)

    def test_terraform_analyze_does_not_flag_restricted_or_egress_ranges(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf.json").write_text(
                '{"resource":{"aws_security_group":{"safe":{"ingress":['
                '{"cidr_blocks":["10.0.0.0/8"],"ipv6_cidr_blocks":["2001:db8::/32"]}],'
                '"egress":[{"cidr_blocks":["0.0.0.0/0"]}]}}}}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("no internet-wide ingress found", stdout)
        self.assertNotIn("Potential public ingress", stdout)

    def test_terraform_analyze_hides_unknown_protocol_and_port_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf.json").write_text(
                '{"resource":{"aws_vpc_security_group_ingress_rule":{"hidden_label":{'
                '"ip_protocol":"${var.protocol}","from_port":"${var.start}",'
                '"to_port":"${var.end}","cidr_ipv4":"0.0.0.0/0"}}}}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("protocol/port details unavailable", stdout)
        self.assertNotIn("var.protocol", stdout)
        self.assertNotIn("var.start", stdout)
        self.assertNotIn("hidden_label", stdout)

    def test_terraform_analyze_marks_unresolved_json_cidr_incomplete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf.json").write_text(
                '{"resource":{"aws_security_group":{"hidden_label":{"ingress":['
                '{"protocol":"tcp","from_port":443,"to_port":443,'
                '"cidr_blocks":["${var.allowed_cidrs}"]}]}}}}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Public-ingress check incomplete", stdout)
        self.assertNotIn("no internet-wide ingress found", stdout)
        self.assertNotIn("var.allowed_cidrs", stdout)
        self.assertNotIn("hidden_label", stdout)

    def test_terraform_analyze_real_parser_marks_dynamic_hcl_cidr_incomplete(self):
        try:
            cli.importlib.import_module("hcl2")
        except ImportError:
            self.skipTest("optional python-hcl2 extra is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf").write_text(
                'variable "allowed_cidrs" {}\n'
                'resource "aws_security_group" "hidden_label" {\n'
                '  ingress {\n'
                '    protocol = "tcp"\n'
                '    from_port = 443\n'
                '    to_port = 443\n'
                '    cidr_blocks = var.allowed_cidrs\n'
                '  }\n'
                '}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Public-ingress check incomplete", stdout)
        self.assertNotIn("no internet-wide ingress found", stdout)
        self.assertNotIn("allowed_cidrs", stdout)
        self.assertNotIn("hidden_label", stdout)

    def test_terraform_analyze_reports_all_protocols_without_port_range(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf.json").write_text(
                '{"resource":{"aws_security_group":{"broad":{"ingress":['
                '{"protocol":"-1","from_port":0,"to_port":0,'
                '"cidr_blocks":["0.0.0.0/0"]}]}}}}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("protocol -1 (all protocols; all ports)", stdout)

    def test_terraform_analyze_does_not_claim_json_clean_without_analyzed_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf").write_text("resource {}\n")
            parser = SimpleNamespace(load=lambda stream: {"resource": []})
            with patch.object(cli.importlib, "import_module", return_value=parser):
                code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn(
            "no internet-wide ingress found in analyzed Terraform HCL security group rules",
            stdout,
        )
        self.assertNotIn("Terraform JSON", stdout)

    def test_terraform_analyze_hides_invalid_json_details(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf.json").write_text(
                '{\n  "token": PRIVATE_VALUE\n}\n'
            )
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 1)
        self.assertIn("Could not parse main.tf.json at line 2, column", stdout)
        self.assertIn("Terraform configuration files analyzed: 0/1", stdout)
        self.assertNotIn("PRIVATE_VALUE", stdout)
        self.assertNotIn('"token"', stdout)

    def test_terraform_analyze_summarizes_valid_json_with_non_object_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf.json").write_text("[]\n")
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 1)
        self.assertIn("Could not summarize main.tf.json", stdout)
        self.assertNotIn("Could not parse", stdout)

    def test_terraform_analyze_suppresses_parser_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf").write_text("configuration text\n")
            parser = SimpleNamespace(load=lambda stream: (_ for _ in ()).throw(ValueError("SECRET_DETAIL")))
            with patch.object(cli.importlib, "import_module", return_value=parser):
                code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 1)
        self.assertIn("Could not parse main.tf", stdout)
        self.assertIn("Terraform configuration files analyzed: 0/1", stdout)
        self.assertNotIn("SECRET_DETAIL", stdout)

    def test_terraform_analyze_does_not_require_parser_without_config(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch.object(cli.importlib, "import_module", side_effect=AssertionError("parser imported")):
            code, stdout, _ = self.run_captured(cli.terraform_analyze, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("No visible Terraform configuration files", stdout)

    def test_terraform_skips_validate_without_initialization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf").write_text("resource {}\n")
            success = subprocess.CompletedProcess(args=["terraform"], returncode=0, stdout="", stderr="")
            with patch.object(cli.shutil, "which", return_value="/fake/terraform"), \
                    patch.object(cli.subprocess, "run", return_value=success) as run:
                code, stdout, _ = self.run_captured(cli.terraform_check, temp_dir)

        self.assertEqual(code, 0)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["/fake/terraform", "fmt", "-check"])
        self.assertIn("validate: skipped", stdout)
        self.assertIn("run 'terraform init' manually", stdout)
        self.assertIn("may download provider plugins", stdout)
        self.assertNotIn("/fake/terraform', 'init", str(run.call_args_list))

    def test_terraform_recognizes_json_configuration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf.json").write_text('{"resource": {}}\n')
            success = subprocess.CompletedProcess(args=["terraform"], returncode=0, stdout="", stderr="")
            with patch.object(cli.shutil, "which", return_value="/fake/terraform"), \
                    patch.object(cli.subprocess, "run", return_value=success) as run:
                code, stdout, _ = self.run_captured(cli.terraform_check, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Terraform configuration files: 1", stdout)
        self.assertIn("main.tf.json", stdout)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["/fake/terraform", "fmt", "-check"])
        self.assertIn("validate: skipped", stdout)

    def test_terraform_summary_suppresses_sensitive_filenames_and_not_contents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "main.tf").write_text("resource {}\n")
            (root / "credentials.tf").write_text("SENSITIVE_VALUE\n")
            success = subprocess.CompletedProcess(args=["terraform"], returncode=0, stdout="", stderr="")
            with patch.object(cli.shutil, "which", return_value="/fake/terraform"), \
                    patch.object(cli.subprocess, "run", return_value=success):
                code, stdout, _ = self.run_captured(cli.terraform_check, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("Terraform configuration files: 1", stdout)
        self.assertIn("main.tf", stdout)
        self.assertIn("1 configuration filename(s) suppressed", stdout)
        self.assertNotIn("credentials.tf", stdout)
        self.assertNotIn("SENSITIVE_VALUE", stdout)

    def test_terraform_recommends_version_constraint_without_printing_contents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "main.tf").write_text('resource "sample" "item" {}\n')
            success = subprocess.CompletedProcess(args=["terraform"], returncode=0, stdout="", stderr="")
            with patch.object(cli.shutil, "which", return_value="/fake/terraform"), \
                    patch.object(cli.subprocess, "run", return_value=success):
                code, stdout, _ = self.run_captured(cli.terraform_check, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("consider adding a Terraform required_version constraint", stdout)
        self.assertNotIn('resource "sample"', stdout)

    def test_terraform_does_not_treat_comment_as_version_constraint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "main.tf").write_text('# terraform { required_version = ">= 1.5" }\n')
            success = subprocess.CompletedProcess(args=["terraform"], returncode=0, stdout="", stderr="")
            with patch.object(cli.shutil, "which", return_value="/fake/terraform"), \
                    patch.object(cli.subprocess, "run", return_value=success):
                code, stdout, _ = self.run_captured(cli.terraform_check, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("consider adding a Terraform required_version constraint", stdout)

    def test_terraform_ignores_version_constraint_inside_multiline_comment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "main.tf").write_text(
                '/*\nterraform {\n  required_version = ">= 1.5"\n}\n*/\n'
            )
            success = subprocess.CompletedProcess(args=["terraform"], returncode=0, stdout="", stderr="")
            with patch.object(cli.shutil, "which", return_value="/fake/terraform"), \
                    patch.object(cli.subprocess, "run", return_value=success):
                code, stdout, _ = self.run_captured(cli.terraform_check, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("consider adding a Terraform required_version constraint", stdout)

    def test_terraform_ignores_required_version_text_inside_string(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "main.tf").write_text('description = "{ required_version = fake }"\n')
            success = subprocess.CompletedProcess(args=["terraform"], returncode=0, stdout="", stderr="")
            with patch.object(cli.shutil, "which", return_value="/fake/terraform"), \
                    patch.object(cli.subprocess, "run", return_value=success):
                code, stdout, _ = self.run_captured(cli.terraform_check, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("consider adding a Terraform required_version constraint", stdout)

    def test_terraform_detects_version_constraint_without_echoing_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "versions.tf").write_text('terraform {\n  required_version = ">= 1.5"\n}\n')
            success = subprocess.CompletedProcess(args=["terraform"], returncode=0, stdout="", stderr="")
            with patch.object(cli.shutil, "which", return_value="/fake/terraform"), \
                    patch.object(cli.subprocess, "run", return_value=success):
                code, stdout, _ = self.run_captured(cli.terraform_check, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("found in versions.tf at line 2", stdout)
        self.assertNotIn(">= 1.5", stdout)

    def test_terraform_does_not_mistake_locals_attribute_for_version_constraint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "main.tf").write_text(
                'locals {\n  required_version = "application setting"\n}\n'
            )
            success = subprocess.CompletedProcess(args=["terraform"], returncode=0, stdout="", stderr="")
            with patch.object(cli.shutil, "which", return_value="/fake/terraform"), \
                    patch.object(cli.subprocess, "run", return_value=success):
                code, stdout, _ = self.run_captured(cli.terraform_check, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("consider adding a Terraform required_version constraint", stdout)

    def test_terraform_detects_inline_json_version_constraint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "main.tf.json").write_text('{"terraform":{"required_version":">= 1.5"}}\n')
            success = subprocess.CompletedProcess(args=["terraform"], returncode=0, stdout="", stderr="")
            with patch.object(cli.shutil, "which", return_value="/fake/terraform"), \
                    patch.object(cli.subprocess, "run", return_value=success):
                code, stdout, _ = self.run_captured(cli.terraform_check, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("found in main.tf.json", stdout)
        self.assertNotIn(">= 1.5", stdout)

    def test_terraform_avoids_version_recommendation_if_config_is_unreadable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf").write_text("terraform {}\n")
            success = subprocess.CompletedProcess(args=["terraform"], returncode=0, stdout="", stderr="")
            with patch.object(cli.shutil, "which", return_value="/fake/terraform"), \
                    patch.object(cli.subprocess, "run", return_value=success), \
                    patch.object(Path, "open", side_effect=PermissionError):
                code, stdout, _ = self.run_captured(cli.terraform_check, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("could not inspect all configuration files", stdout)
        self.assertNotIn("consider adding", stdout)

    def test_git_status_rejects_missing_directory_before_tool_lookup(self):
        with patch.object(cli.shutil, "which") as which:
            code, _, stderr = self.run_captured(cli.git_status, "/path/that/does/not/exist")
        self.assertEqual(code, 2)
        self.assertIn("does not exist", stderr)
        which.assert_not_called()

    def test_github_actions_check_flags_write_all_without_printing_workflow_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workflows = Path(temp_dir) / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "ci.yml").write_text(
                "name: CI\n"
                "permissions: write-all # broad access\n"
                "jobs:\n"
                "  build:\n"
                "    steps:\n"
                "      - run: |\n"
                "          permissions: write-all\n"
                "          echo private_workflow_detail\n"
                "# permissions: write-all\n"
            )
            code, stdout, stderr = self.run_captured(cli.main, ["github-actions-check", temp_dir])

        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertIn("ci.yml at line 2", stdout)
        self.assertNotIn("private_workflow_detail", stdout)
        self.assertNotIn("line 8", stdout)

    def test_github_actions_check_reports_no_workflows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            code, stdout, _ = self.run_captured(cli.github_actions_check, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("No GitHub Actions workflow directory found", stdout)

    def test_github_actions_check_rejects_missing_directory(self):
        code, _, stderr = self.run_captured(cli.github_actions_check, "/path/does/not/exist")
        self.assertEqual(code, 2)
        self.assertIn("does not exist", stderr)

    def test_dockerfile_check_flags_implicit_and_explicit_latest_without_echoing_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Dockerfile").write_text(
                "FROM registry.example:5000/team/app:latest AS build\n"
                "RUN echo private_build_detail\n"
                "FROM ubuntu AS runtime\n"
                "FROM scratch\n"
                "FROM team/app:latest@sha256:0123456789abcdef\n"
                "FROM alpine:3.20\n"
            )
            code, stdout, stderr = self.run_captured(cli.main, ["dockerfile-check", temp_dir])

        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertIn("Dockerfiles checked: 1", stdout)
        self.assertIn("Dockerfile at line 1: uses the explicit latest tag", stdout)
        self.assertIn("Dockerfile at line 3: uses the implicit latest tag", stdout)
        self.assertNotIn("private_build_detail", stdout)
        self.assertNotIn("line 5", stdout)
        self.assertNotIn("line 6", stdout)

    def test_dockerfile_check_marks_variable_image_references_incomplete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "Dockerfile.dev").write_text(
                "ARG BASE_IMAGE\nFROM ${BASE_IMAGE} AS app\n"
            )
            code, stdout, _ = self.run_captured(cli.dockerfile_check, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("check incomplete", stdout)
        self.assertNotIn("BASE_IMAGE", stdout)

    def test_dockerfile_check_reports_no_files_and_missing_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            code, stdout, _ = self.run_captured(cli.dockerfile_check, temp_dir)

        self.assertEqual(code, 0)
        self.assertIn("No visible Dockerfiles found", stdout)
        code, _, stderr = self.run_captured(cli.dockerfile_check, "/path/does/not/exist")
        self.assertEqual(code, 2)
        self.assertIn("does not exist", stderr)

    def test_project_review_runs_all_local_checks_and_reports_partial_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch.object(cli, "terraform_analyze", return_value=1) as terraform, \
                patch.object(cli, "github_actions_check", return_value=0) as actions, \
                patch.object(cli, "dockerfile_check", return_value=0) as docker:
            code, stdout, _ = self.run_captured(cli.project_review, temp_dir)

        self.assertEqual(code, 1)
        self.assertIn("Terraform analysis:", stdout)
        self.assertIn("GitHub Actions check:", stdout)
        self.assertIn("Dockerfile check:", stdout)
        self.assertIn("one or more incomplete or failed checks", stdout)
        terraform.assert_called_once_with(temp_dir)
        actions.assert_called_once_with(temp_dir)
        docker.assert_called_once_with(temp_dir)

    def test_project_review_rejects_missing_directory_before_checks(self):
        with patch.object(cli, "terraform_analyze") as terraform:
            code, _, stderr = self.run_captured(cli.project_review, "/path/does/not/exist")

        self.assertEqual(code, 2)
        self.assertIn("does not exist", stderr)
        terraform.assert_not_called()

    def test_aws_security_groups_reports_public_ingress_without_sensitive_values(self):
        response = {
            "SecurityGroupRules": [
                {"IsEgress": False, "CidrIpv4": "0.0.0.0/0", "IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
                 "GroupId": "sg-private-id", "Description": "private-description"},
                {"IsEgress": False, "CidrIpv6": "::/0", "IpProtocol": "-1"},
                {"IsEgress": True, "CidrIpv4": "0.0.0.0/0", "IpProtocol": "-1"},
                {"IsEgress": False, "CidrIpv4": "10.0.0.0/8", "IpProtocol": "tcp"},
            ]
        }
        result = subprocess.CompletedProcess(
            args=["aws"], returncode=0, stdout=json.dumps(response), stderr=""
        )
        with patch.object(cli.shutil, "which", return_value="/fake/aws"), \
                patch.object(cli.subprocess, "run", return_value=result) as run:
            code, stdout, stderr = self.run_captured(cli.aws_security_groups, "us-east-1")

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("region us-east-1", stdout)
        self.assertIn("0.0.0.0/0 (protocol tcp, ports 443-443)", stdout)
        self.assertIn("::/0 (protocol -1 (all protocols; all ports))", stdout)
        self.assertNotIn("sg-private-id", stdout)
        self.assertNotIn("private-description", stdout)
        self.assertEqual(run.call_args.args[0][-2:], ["--region", "us-east-1"])

    def test_aws_security_groups_suppresses_aws_errors_and_invalid_json(self):
        cases = (
            subprocess.CompletedProcess(args=["aws"], returncode=1, stdout="", stderr="private error"),
            subprocess.CompletedProcess(args=["aws"], returncode=0, stdout="private response", stderr=""),
        )
        for result in cases:
            with self.subTest(result=result.returncode, output=result.stdout), \
                    patch.object(cli.shutil, "which", return_value="/fake/aws"), \
                    patch.object(cli.subprocess, "run", return_value=result):
                code, stdout, stderr = self.run_captured(cli.aws_security_groups)
            self.assertEqual(code, 1)
            self.assertNotIn("private", stdout + stderr)

    def test_aws_security_groups_handles_missing_cli(self):
        with patch.object(cli.shutil, "which", return_value=None):
            code, _, stderr = self.run_captured(cli.aws_security_groups)
        self.assertEqual(code, 1)
        self.assertIn("AWS CLI is not installed", stderr)

    def test_ask_uses_only_local_ollama_and_prints_answer(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"message": {"content": "Terraform state records managed resources."}}
        ).encode("utf-8")
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(cli, "build_opener", return_value=opener) as build_opener:
            code, stdout, stderr = self.run_captured(
                cli.ask_local_model, "Explain this finding", "llama3", "Static check saw a public rule."
            )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, "Terraform state records managed resources.\n")
        build_opener.assert_called_once()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:11434/api/chat")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "llama3")
        self.assertFalse(payload["stream"])
        self.assertIn("Explain this finding", payload["messages"][-1]["content"])
        self.assertIn("Static check saw a public rule.", payload["messages"][-1]["content"])
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 180)

    def test_terraform_draft_passes_bounded_requirements_to_local_model(self):
        with patch.object(cli, "ask_local_model", return_value=0) as ask:
            code, stdout, stderr = self.run_captured(
                cli.terraform_draft, "Create a private S3 bucket", "llama3"
            )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("Unreviewed Terraform draft", stdout)
        self.assertIn("not written, validated, or applied", stdout)
        ask.assert_called_once()
        question, model = ask.call_args.args
        self.assertEqual(question, "Create a private S3 bucket")
        self.assertEqual(model, "llama3")
        self.assertIn("Return HCL only", ask.call_args.kwargs["system_instruction"])
        self.assertIn(
            "comment immediately before each top-level block",
            ask.call_args.kwargs["system_instruction"],
        )
        self.assertEqual(ask.call_args.kwargs["max_output_tokens"], 1200)

    def test_terraform_draft_rejects_empty_or_oversized_requirements(self):
        with patch.object(cli, "ask_local_model") as ask:
            empty_code, _, empty_stderr = self.run_captured(cli.terraform_draft, "  ")
            long_code, _, long_stderr = self.run_captured(cli.terraform_draft, "x" * 5001)

        self.assertEqual(empty_code, 2)
        self.assertIn("Please describe", empty_stderr)
        self.assertEqual(long_code, 2)
        self.assertIn("under 5,000 characters", long_stderr)
        ask.assert_not_called()

    def test_terraform_draft_saves_to_new_tf_file(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"message": {"content": 'resource "example" "sample" {}'}}
        ).encode("utf-8")
        opener = MagicMock()
        opener.open.return_value = response
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "main.tf"
            with patch.object(cli, "build_opener", return_value=opener):
                code, stdout, stderr = self.run_captured(
                    cli.terraform_draft,
                    "Create a resource",
                    "llama3",
                    str(target),
                )

            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(target.read_text(encoding="utf-8"), 'resource "example" "sample" {}\n')
            self.assertIn("saved to:", stdout)
            self.assertIn("not been formatted, validated, or applied", stdout)

    def test_terraform_draft_refuses_existing_file_without_changing_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "main.tf"
            target.write_text("keep this file\n", encoding="utf-8")
            with patch.object(cli, "ask_local_model") as ask:
                code, _, stderr = self.run_captured(
                    cli.terraform_draft,
                    "Create a resource",
                    "llama3",
                    str(target),
                )
            self.assertEqual(target.read_text(encoding="utf-8"), "keep this file\n")

        self.assertEqual(code, 2)
        self.assertIn("already exists", stderr)
        ask.assert_not_called()

    def test_terraform_draft_requires_tf_extension_for_output(self):
        with patch.object(cli, "ask_local_model") as ask:
            code, _, stderr = self.run_captured(
                cli.terraform_draft, "Create a resource", "llama3", "draft.txt"
            )

        self.assertEqual(code, 2)
        self.assertIn("end in .tf", stderr)
        ask.assert_not_called()

    def test_terraform_explain_sends_only_sanitized_static_findings(self):
        configuration = {
            "terraform": {"required_version": ">= 1.0"},
            "resource": {
                "aws_security_group": {
                    "private-network-resource-label": {
                        "ingress": [{
                            "protocol": "tcp", "from_port": 443, "to_port": 443,
                            "cidr_blocks": ["0.0.0.0/0"],
                        }],
                        "tags": {"Name": "private-user-data-value"},
                    }
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "internal-network.tf.json").write_text(json.dumps(configuration))
            with patch.object(cli, "ask_local_model", return_value=0) as ask:
                code, stdout, stderr = self.run_captured(
                    cli.terraform_explain, temp_dir, "llama3"
                )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("Potential public ingress", stdout)
        self.assertIn("AI explanation (generated from the static findings above)", stdout)
        ask.assert_called_once()
        question, model = ask.call_args.args[:2]
        context = ask.call_args.kwargs["context"]
        self.assertEqual(model, "llama3")
        self.assertIn("aws_security_group", context)
        self.assertIn("0.0.0.0/0", context)
        self.assertNotIn("internal-network.tf.json", context)
        for private_value in ("private-network-resource-label", "private-user-data-value"):
            self.assertNotIn(private_value, context)
        self.assertNotIn("destroy", question.lower())

    def test_terraform_explanation_context_sanitizes_s3_acl_finding(self):
        report = (
            "Potential public S3 ACL: aws_s3_bucket_acl uses public-read. "
            "This static finding does not confirm effective public access; "
            "bucket or account Block Public Access settings may override it. "
            "(file: private-user-data.tf)."
        )

        context = cli.safe_terraform_explanation_context(report)

        self.assertIn("aws_s3_bucket_acl", context)
        self.assertIn("public-read", context)
        self.assertIn("effective access is unverified", context)
        self.assertNotIn("private-user-data.tf", context)

    def test_terraform_explanation_context_sanitizes_s3_block_finding(self):
        report = (
            "S3 public-access protection disabled: "
            "aws_s3_bucket_public_access_block sets block_public_policy = false. "
            "This is a configuration finding. (file: private.tf)."
        )

        context = cli.safe_terraform_explanation_context(report)

        self.assertIn("block_public_policy", context)
        self.assertIn("effective public access", context)
        self.assertNotIn("private.tf", context)

    def test_terraform_explanation_context_sanitizes_s3_versioning_finding(self):
        report = (
            "Potential S3 versioning disabled: S3 bucket versioning is suspended; "
            "new object writes do not get unique versions. Existing versions and "
            "live bucket state were not assessed. (file: private.tf)."
        )

        context = cli.safe_terraform_explanation_context(report)

        self.assertIn("suspended", context)
        self.assertIn("live bucket state is unverified", context)
        self.assertNotIn("private.tf", context)

    def test_terraform_explanation_context_sanitizes_ebs_encryption_finding(self):
        report = (
            "Potential unencrypted EBS volume setting: aws_ebs_volume explicitly "
            "sets encrypted = false. Account-level settings may override it. "
            "(file: private.tf)."
        )

        context = cli.safe_terraform_explanation_context(report)

        self.assertIn("aws_ebs_volume", context)
        self.assertIn("encrypted=false", context)
        self.assertIn("deployed encryption was not checked", context)
        self.assertNotIn("private.tf", context)

    def test_terraform_explanation_context_allows_supported_instance_block_types(self):
        report = (
            "Potential unencrypted EBS volume setting: "
            "aws_instance.root_block_device explicitly sets encrypted = false. "
            "Account-level defaults may override this."
        )

        context = cli.safe_terraform_explanation_context(report)

        self.assertIn("aws_instance.root_block_device", context)
        self.assertIn("encrypted=false", context)

    def test_terraform_explanation_context_allows_launch_template_block_type(self):
        report = (
            "Potential unencrypted EBS volume setting: "
            "aws_launch_template.block_device_mappings.ebs explicitly sets "
            "encrypted = false. Account-level defaults may override this."
        )

        context = cli.safe_terraform_explanation_context(report)

        self.assertIn("aws_launch_template.block_device_mappings.ebs", context)
        self.assertIn("encrypted=false", context)

    def test_terraform_explanation_context_sanitizes_optional_imdsv2_finding(self):
        report = (
            "Potential IMDSv1 allowed: aws_instance sets http_tokens = optional. "
            "(file: sensitive.tf, label: private_instance)."
        )

        context = cli.safe_terraform_explanation_context(report)

        self.assertIn("http_tokens=optional", context)
        self.assertIn("allows IMDSv1 compatibility", context)
        self.assertNotIn("sensitive.tf", context)
        self.assertNotIn("private_instance", context)

    def test_terraform_explain_does_not_send_unresolved_cidr_values(self):
        configuration = {
            "resource": {
                "aws_security_group": {
                    "web": {"ingress": [{
                        "protocol": "tcp", "cidr_blocks": ["${var.sensitive_cidr}"],
                    }]}
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "main.tf.json").write_text(json.dumps(configuration))
            with patch.object(cli, "ask_local_model", return_value=0) as ask:
                code, _, _ = self.run_captured(cli.terraform_explain, temp_dir)

        self.assertEqual(code, 0)
        context = ask.call_args.kwargs["context"]
        self.assertIn("check is incomplete", context)
        self.assertNotIn("sensitive_cidr", context)

    def test_terraform_explain_skips_ai_when_static_analysis_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "broken.tf.json").write_text("{")
            with patch.object(cli, "ask_local_model") as ask:
                code, stdout, _ = self.run_captured(cli.terraform_explain, temp_dir)

        self.assertEqual(code, 1)
        self.assertIn("AI explanation skipped", stdout)
        ask.assert_not_called()

    def test_ask_suppresses_local_service_errors(self):
        with patch.object(cli, "build_opener", side_effect=URLError("private details")):
            code, stdout, stderr = self.run_captured(cli.ask_local_model, "Explain Terraform")

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("local Ollama service", stderr)
        self.assertNotIn("private details", stderr)

    def test_ask_rejects_blank_question_without_contacting_local_service(self):
        with patch.object(cli, "build_opener") as build_opener:
            code, _, stderr = self.run_captured(cli.ask_local_model, "  ")

        self.assertEqual(code, 2)
        self.assertIn("enter a question", stderr)
        build_opener.assert_not_called()

    def test_git_status_filters_sensitive_entries(self):
        output = (
            "## main\n M app.py\n M .env\n M credentials.json\n"
            "A  added.py\n D deleted.py\n?? new.txt\n"
            "R  credentials.json -> config.py\n"
        )
        result = subprocess.CompletedProcess(args=["git"], returncode=0, stdout=output, stderr="")
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch.object(cli.shutil, "which", return_value="/fake/git"), \
                patch.object(cli.subprocess, "run", return_value=result) as run:
            code, stdout, _ = self.run_captured(cli.git_status, temp_dir)

        self.assertEqual(code, 0)
        self.assertEqual(run.call_args.args[0][1:], ["-C", str(Path(temp_dir).resolve()), "status", "--short", "--branch"])
        self.assertIn("## main", stdout)
        self.assertIn("app.py", stdout)
        self.assertIn("3 status entries", stdout)
        self.assertIn("Changes: 1 modified, 1 added, 1 deleted, 1 untracked", stdout)
        self.assertNotIn(".env", stdout)
        self.assertNotIn("credentials.json", stdout)

    def test_git_status_failure_suppresses_raw_error(self):
        result = subprocess.CompletedProcess(args=["git"], returncode=128, stdout="", stderr="private path")
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch.object(cli.shutil, "which", return_value="/fake/git"), \
                patch.object(cli.subprocess, "run", return_value=result):
            code, _, stderr = self.run_captured(cli.git_status, temp_dir)

        self.assertEqual(code, 1)
        self.assertIn("may not be a Git repository", stderr)
        self.assertIn("raw Git output was suppressed", stderr)
        self.assertNotIn("private path", stderr)


if __name__ == "__main__":
    unittest.main()
