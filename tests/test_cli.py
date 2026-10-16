"""Regression tests for the safe, read-only CLI commands."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

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
        for command in ("inspect", "status", "check", "terraform", "terraform-analyze", "git-status"):
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
        for command in ("inspect", "status", "terraform", "terraform-analyze", "git-status"):
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
