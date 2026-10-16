"""Command line interface for safe project and repository checks."""

from __future__ import annotations

import argparse
import importlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from devops_copilot import __version__


SECRET_NAME = re.compile(
    r"(^|[._-])(secret|secrets|credential|credentials|password|passwd|token|private.?key)([._-]|$)",
    re.IGNORECASE,
)
SENSITIVE_SUFFIXES = (".tfstate", ".tfstate.backup", ".pem", ".key", ".p12", ".pfx")
GENERATED_DIRECTORY_NAMES = {"venv", "env", "virtualenv", "__pycache__", "node_modules"}
VERSION_PATTERNS = {
    "Git": re.compile(r"^git version (\d+(?:\.\d+)+)", re.IGNORECASE),
    "Python": re.compile(r"^Python (\d+(?:\.\d+)+)", re.IGNORECASE),
    "Terraform": re.compile(r"^Terraform v(\d+(?:\.\d+)+)", re.IGNORECASE),
}
TERRAFORM_BLOCK_PATTERN = re.compile(r"\bterraform\s*\{")
REQUIRED_VERSION_PATTERN = re.compile(r"\brequired_version\s*=")


def find_required_version_line(lines) -> int | None:
    """Find the line of required_version in a top-level terraform block."""
    in_block_comment = False
    brace_depth = 0
    terraform_depth = None
    for line_number, line in enumerate(lines, start=1):
        code = []
        index = 0
        in_string = False
        escaped = False
        while index < len(line):
            if in_block_comment:
                end = line.find("*/", index)
                if end == -1:
                    break
                in_block_comment = False
                index = end + 2
                continue

            char = line[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                index += 1
                continue

            if line.startswith("/*", index):
                in_block_comment = True
                index += 2
            elif line.startswith("//", index) or char == "#":
                break
            else:
                code.append(char)
                if char == '"':
                    in_string = True
                index += 1

        clean_line = "".join(code)
        index = 0
        while index < len(clean_line):
            if terraform_depth is None and brace_depth == 0:
                block_match = TERRAFORM_BLOCK_PATTERN.match(clean_line, index)
                if block_match:
                    brace_depth += 1
                    terraform_depth = brace_depth
                    index = block_match.end()
                    continue

            if terraform_depth is not None and brace_depth == terraform_depth:
                version_match = REQUIRED_VERSION_PATTERN.match(clean_line, index)
                if version_match:
                    return line_number

            char = clean_line[index]
            if char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth -= 1
                if terraform_depth is not None and brace_depth < terraform_depth:
                    terraform_depth = None
            index += 1
    return None


def is_sensitive_name(name: str) -> bool:
    lowered = name.lower()
    return (
        name.startswith(".")
        or SECRET_NAME.search(name) is not None
        or lowered.endswith(SENSITIVE_SUFFIXES)
    )


def should_skip_directory(path: Path) -> bool:
    return (
        is_sensitive_name(path.name)
        or path.name.lower() in GENERATED_DIRECTORY_NAMES
        or path.is_symlink()
    )


def project_summary(root: Path) -> tuple[int, int, Counter]:
    """Count visible files, folders, and extensions in one bounded-memory walk."""
    file_count = 0
    directory_count = 0
    extensions = Counter()
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            name for name in dirs if not should_skip_directory(Path(current, name))
        )
        directory_count += len(dirs)
        for name in sorted(files):
            path = Path(current, name)
            if not is_sensitive_name(name) and not path.is_symlink():
                file_count += 1
                extensions[path.suffix.lower() or "[no extension]"] += 1
    return file_count, directory_count, extensions


def inspect_project(directory: str) -> int:
    root = Path(directory).expanduser()
    if not root.exists() or not root.is_dir():
        print(f"Error: project directory does not exist or is not a directory: {root}", file=sys.stderr)
        return 2

    root = root.resolve()
    file_count, directories, extensions = project_summary(root)

    print(f"Project: {root}")
    print(f"Files: {file_count}")
    print(f"Directories: {directories}")
    if extensions:
        print("File types:")
        for extension, count in sorted(extensions.items(), key=lambda item: (-item[1], item[0])):
            print(f"  {extension}: {count}")
    else:
        print("No visible files found.")
    print("Hidden and sensitive paths, Terraform state files, and virtual environment/cache directories were skipped.")
    return 0


def run_check(command: list[str], cwd: Path, label: str) -> bool:
    """Run a check without relaying raw tool output, which could contain secrets."""
    try:
        result = subprocess.run(
            command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=120,
        )
    except subprocess.TimeoutExpired:
        print(f"{label}: timed out.")
        return False
    except OSError:
        print(f"{label}: could not be started.")
        return False

    if result.returncode == 0:
        print(f"{label}: passed.")
        return True
    print(f"{label}: failed (exit code {result.returncode}); raw tool output was suppressed for safety.")
    if label == "terraform fmt -check":
        print("Run 'terraform fmt -check' locally to see whether formatting or a configuration syntax error caused this failure.")
    elif label == "terraform validate":
        print("To inspect the detailed diagnostic locally, run 'terraform validate' in this directory.")
    return False


def _as_dict_blocks(value) -> list[dict]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _as_string_values(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _safe_integer(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _ingress_context(rule: dict, protocol_field: str) -> str:
    protocol = rule.get(protocol_field)
    if not isinstance(protocol, str):
        return "protocol/port details unavailable"
    protocol = protocol.lower()
    if protocol == "-1":
        return "protocol -1 (all protocols; all ports)"

    first = _safe_integer(rule.get("from_port"))
    last = _safe_integer(rule.get("to_port"))
    if protocol in {"tcp", "udp"} and first is not None and last is not None:
        if 0 <= first <= last <= 65535:
            return f"protocol {protocol}, ports {first}-{last}"
    if protocol in {"icmp", "icmpv6"} and first is not None and last is not None:
        if -1 <= first <= 255 and -1 <= last <= 255:
            return f"protocol {protocol}, type/code {first}/{last}"
    return "protocol/port details unavailable"


def find_json_public_security_group_ingress(
    document: dict,
) -> tuple[set[tuple[str, str, str]], bool]:
    """Find public ingress and note CIDRs that static analysis cannot resolve."""
    resources = document.get("resource", {})
    if not isinstance(resources, dict):
        return set(), False

    findings = set()
    unresolved_cidr = False
    for resource_type, instances in resources.items():
        if resource_type not in {
            "aws_security_group",
            "aws_security_group_rule",
            "aws_vpc_security_group_ingress_rule",
        } or not isinstance(instances, dict):
            continue

        for body in instances.values():
            if not isinstance(body, dict):
                continue
            ingress_rules = []
            if resource_type == "aws_security_group":
                for ingress in _as_dict_blocks(body.get("ingress")):
                    ingress_rules.append((ingress, "protocol"))
            elif resource_type == "aws_security_group_rule":
                if body.get("type") != "ingress":
                    continue
                ingress_rules.append((body, "protocol"))
            else:
                ingress_rules.append((body, "ip_protocol"))

            for rule, protocol_field in ingress_rules:
                cidr_fields = []
                cidr_keys = [("cidr_blocks", 4), ("ipv6_cidr_blocks", 6)]
                if resource_type == "aws_vpc_security_group_ingress_rule":
                    cidr_keys = [("cidr_ipv4", 4), ("cidr_ipv6", 6)]
                for cidr_key, version in cidr_keys:
                    if cidr_key not in rule:
                        continue
                    value = rule[cidr_key]
                    if isinstance(value, str):
                        cidr_fields.append((value, version))
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, str):
                                cidr_fields.append((item, version))
                            else:
                                unresolved_cidr = True
                    else:
                        unresolved_cidr = True
                context = _ingress_context(rule, protocol_field)
                for cidr, version in cidr_fields:
                    try:
                        network = ipaddress.ip_network(cidr, strict=False)
                    except ValueError:
                        unresolved_cidr = True
                        continue
                    if network.version != version:
                        unresolved_cidr = True
                    elif network.prefixlen == 0:
                        findings.add((resource_type, str(network), context))
    return findings, unresolved_cidr


def _normalize_hcl_value(value):
    """Decode parser-serialized HCL string literals without evaluating expressions."""
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value
        return decoded
    if isinstance(value, list):
        return [_normalize_hcl_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_hcl_value(item) for key, item in value.items()}
    return value


def find_hcl_public_security_group_ingress(
    document: dict,
) -> tuple[set[tuple[str, str, str]], bool]:
    """Convert python-hcl2's block representation to the JSON rule's input shape."""
    resources = {}
    for resource_block in _as_dict_blocks(document.get("resource")):
        for encoded_type, instances in resource_block.items():
            resource_type = _normalize_hcl_value(encoded_type)
            if not isinstance(resource_type, str) or not isinstance(instances, dict):
                continue
            normalized_instances = resources.setdefault(resource_type, {})
            normalized_instances.update(
                {
                    label: _normalize_hcl_value(body)
                    for label, body in instances.items()
                }
            )
    normalized_document = dict(document)
    normalized_document["resource"] = resources
    return find_json_public_security_group_ingress(normalized_document)


def report_required_version(config_files: list[Path]) -> None:
    """Give a non-blocking version-compatibility hint without echoing file data."""
    visible_files = [path for path in config_files if not is_sensitive_name(path.name)]
    if not visible_files:
        print("Terraform version constraint: unable to inspect sensitive configuration filenames.")
        return

    found_path = None
    found_line = None
    unreadable = 0
    for path in visible_files:
        try:
            if path.name.endswith(".tf.json"):
                with path.open("r", encoding="utf-8") as config_file:
                    document = json.load(config_file)
                terraform_block = document.get("terraform", {}) if isinstance(document, dict) else {}
                if isinstance(terraform_block, dict) and "required_version" in terraform_block:
                    found_path = path
                    break
            else:
                with path.open("r", encoding="utf-8", errors="replace") as config_file:
                    found_line = find_required_version_line(config_file)
                    if found_line is not None:
                        found_path = path
                        break
        except (OSError, ValueError):
            unreadable += 1

    if found_path is not None:
        location = found_path.name
        if found_line is not None:
            location += f" at line {found_line}"
        print(f"Terraform version constraint: found in {location}.")
    elif unreadable:
        print("Terraform version constraint: could not inspect all configuration files; no recommendation was made.")
    else:
        print("Recommendation: consider adding a Terraform required_version constraint to declare compatible versions.")


def check_tools() -> int:
    """Report whether common local tools can run their version command."""
    tools = (
        ("Git", "git", ["--version"]),
        ("Python", "python3", ["--version"]),
        ("Terraform", "terraform", ["--version"]),
    )
    all_available = True
    for label, executable_name, arguments in tools:
        executable = shutil.which(executable_name)
        if executable is None and label == "Python":
            executable = shutil.which("python")
        if executable is None:
            print(f"{label}: not found on PATH.")
            all_available = False
            continue

        try:
            result = subprocess.run(
                [executable, *arguments], text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, check=False, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            print(f"{label}: found on PATH but its version check could not be completed.")
            all_available = False
            continue

        output = (result.stdout or result.stderr).strip().splitlines()
        match = VERSION_PATTERNS[label].match(output[0].strip()) if output else None
        if result.returncode == 0 and match:
            print(f"{label}: available (version {match.group(1)}).")
        else:
            print(f"{label}: found on PATH but its version could not be determined.")
            all_available = False

    return 0 if all_available else 1


def terraform_check(directory: str) -> int:
    root = Path(directory).expanduser()
    if not root.exists() or not root.is_dir():
        print(f"Error: project directory does not exist or is not a directory: {root}", file=sys.stderr)
        return 2
    root = root.resolve()
    executable = shutil.which("terraform")
    if executable is None:
        print("Terraform is not installed or is not available on PATH.")
        return 1

    # Only inspect the selected module root; do not recurse into nested modules.
    config_files = [
        path
        for pattern in ("*.tf", "*.tf.json")
        for path in root.glob(pattern)
        if path.is_file() and not path.is_symlink()
    ]
    if not config_files:
        print(f"No Terraform configuration files (*.tf or *.tf.json) found directly in {root}; checks were skipped.")
        return 0

    visible_files = sorted(path.name for path in config_files if not is_sensitive_name(path.name))
    suppressed_files = len(config_files) - len(visible_files)
    print(f"Terraform configuration files: {len(visible_files)}")
    for name in visible_files:
        print(f"  {name}")
    if suppressed_files:
        print(f"{suppressed_files} configuration filename(s) suppressed as sensitive.")
    report_required_version(config_files)

    print(f"Terraform found: {executable}")
    fmt_ok = run_check([executable, "fmt", "-check"], root, "terraform fmt -check")

    if (root / ".terraform").is_dir():
        validate_ok = run_check([executable, "validate"], root, "terraform validate")
    else:
        print("terraform validate: skipped because this directory is not initialized (.terraform is missing).")
        print("To enable validation, you can run 'terraform init' manually; it may download provider plugins. DevOps Copilot will not run it.")
        validate_ok = True

    return 0 if fmt_ok and validate_ok else 1


def terraform_analyze(directory: str) -> int:
    """Summarize Terraform declarations using the optional local HCL parser."""
    root = Path(directory).expanduser()
    if not root.exists() or not root.is_dir():
        print(f"Error: Terraform directory does not exist or is not a directory: {root}", file=sys.stderr)
        return 2
    root = root.resolve()
    config_files = sorted(
        path
        for pattern in ("*.tf", "*.tf.json")
        for path in root.glob(pattern)
        if path.is_file() and not path.is_symlink()
    )
    visible_files = [path for path in config_files if not is_sensitive_name(path.name)]
    suppressed = len(config_files) - len(visible_files)
    if not visible_files:
        print("No visible Terraform configuration files found.")
        if suppressed:
            print(f"{suppressed} sensitive configuration filename(s) suppressed.")
        return 0

    hcl_files = [path for path in visible_files if path.name.endswith(".tf")]
    json_files = [path for path in visible_files if path.name.endswith(".tf.json")]
    hcl2 = None
    if hcl_files:
        try:
            hcl2 = importlib.import_module("hcl2")
        except ImportError:
            print(
                "HCL analysis requires the optional parser. From the project "
                "directory, run: python3 -m pip install '.[terraform]'",
                file=sys.stderr,
            )
            if not json_files:
                return 1

    declaration_types = {
        "check", "data", "locals", "module", "moved", "output", "provider",
        "resource", "terraform", "variable",
    }
    found_types = set()
    has_required_version = False
    failed_files = 0
    skipped_hcl_files = 0
    analyzed_files = 0
    analyzed_json_files = 0
    analyzed_hcl_files = 0
    public_ingress_findings = set()
    unresolved_ingress_cidr = False
    for path in visible_files:
        if path.name.endswith(".tf") and hcl2 is None:
            skipped_hcl_files += 1
            continue
        try:
            with path.open("r", encoding="utf-8") as config_file:
                if path.name.endswith(".tf.json"):
                    document = json.load(config_file)
                else:
                    document = hcl2.load(config_file)
        except json.JSONDecodeError as error:
            print(
                f"Could not parse {path.name} at line {error.lineno}, column {error.colno}; "
                "file contents and parser details were suppressed."
            )
            failed_files += 1
            continue
        except Exception:
            print(f"Could not parse {path.name}; parser details were suppressed.")
            failed_files += 1
            continue

        if not isinstance(document, dict):
            failed_files += 1
            print(f"Could not summarize {path.name}; parser details were suppressed.")
            continue
        analyzed_files += 1
        if path.name.endswith(".tf.json"):
            analyzed_json_files += 1
            ingress_findings, unresolved_cidr = find_json_public_security_group_ingress(document)
        else:
            analyzed_hcl_files += 1
            ingress_findings, unresolved_cidr = find_hcl_public_security_group_ingress(document)
        unresolved_ingress_cidr = unresolved_ingress_cidr or unresolved_cidr
        public_ingress_findings.update(
            (path.name, resource_type, cidr, context)
            for resource_type, cidr, context in ingress_findings
        )
        found_types.update(declaration_types.intersection(document))
        terraform_blocks = document.get("terraform", [])
        if isinstance(terraform_blocks, dict):
            terraform_blocks = [terraform_blocks]
        if isinstance(terraform_blocks, list):
            has_required_version = has_required_version or any(
                isinstance(block, dict) and "required_version" in block
                for block in terraform_blocks
            )

    print(f"Terraform configuration files analyzed: {analyzed_files}/{len(visible_files)}")
    if skipped_hcl_files:
        print(f"HCL files skipped: {skipped_hcl_files} (optional parser unavailable).")
    if public_ingress_findings:
        for filename, resource_type, cidr, context in sorted(public_ingress_findings):
            print(
                f"Potential public ingress: {filename} contains an {resource_type} "
                f"rule open to {cidr} ({context}). "
                "Static analysis cannot confirm deployed exposure."
            )
    elif unresolved_ingress_cidr:
        print(
            "Public-ingress check incomplete: one or more ingress CIDRs could not "
            "be resolved; their values were not printed."
        )
    elif analyzed_json_files:
        print(
            "Public-ingress check: no internet-wide ingress found in analyzed "
            "Terraform JSON security group rules."
        )
    elif analyzed_hcl_files:
        print(
            "Public-ingress check: no internet-wide ingress found in analyzed "
            "Terraform HCL security group rules."
        )
    else:
        print("Public-ingress check: no Terraform configuration files were analyzed.")
    if public_ingress_findings and unresolved_ingress_cidr:
        print(
            "Additional ingress rules could not be assessed because one or more "
            "CIDRs were unresolved; their values were not printed."
        )
    if found_types:
        print("Declaration types: " + ", ".join(sorted(found_types)) + ".")
    else:
        print("No recognized top-level declarations were found in parsed files.")
    if has_required_version:
        print("Terraform version constraint: found.")
    elif failed_files or skipped_hcl_files:
        print("Terraform version constraint: could not determine for all files.")
    else:
        print("Recommendation: consider declaring a required_version constraint.")
    if suppressed:
        print(f"{suppressed} sensitive configuration filename(s) suppressed.")
    return 1 if failed_files or skipped_hcl_files else 0


def git_status(directory: str) -> int:
    root = Path(directory).expanduser()
    if not root.exists() or not root.is_dir():
        print(f"Error: repository directory does not exist or is not a directory: {root}", file=sys.stderr)
        return 2
    root = root.resolve()
    executable = shutil.which("git")
    if executable is None:
        print("Git is not installed or is not available on PATH.", file=sys.stderr)
        return 1

    try:
        result = subprocess.run(
            [executable, "-C", str(root), "status", "--short", "--branch"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        print("Git status could not be completed.", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(
            "Git status could not be completed; this directory may not be a Git repository; "
            "raw Git output was suppressed for safety.",
            file=sys.stderr,
        )
        return 1

    lines = result.stdout.splitlines()
    print(f"Repository: {root}")
    safe_lines = []
    hidden = 0
    counts = {"modified": 0, "added": 0, "deleted": 0, "untracked": 0, "other": 0}
    for line in lines:
        # Git's branch header is not a file path. For status rows, suppress sensitive paths.
        if line.startswith("## "):
            safe_lines.append(line)
            continue
        path_part = line[3:]
        renamed_paths = path_part.split(" -> ")
        if any(
            is_sensitive_name(part)
            for renamed_path in renamed_paths
            for part in Path(renamed_path.strip('"')).parts
        ):
            hidden += 1
        else:
            safe_lines.append(line)
            status_code = line[:2]
            if "D" in status_code:
                counts["deleted"] += 1
            elif "A" in status_code:
                counts["added"] += 1
            elif status_code == "??":
                counts["untracked"] += 1
            elif "M" in status_code:
                counts["modified"] += 1
            else:
                counts["other"] += 1
    if safe_lines:
        print("\n".join(safe_lines))
    print(
        "Changes: "
        f"{counts['modified']} modified, {counts['added']} added, "
        f"{counts['deleted']} deleted, {counts['untracked']} untracked."
    )
    if counts["other"]:
        print(f"{counts['other']} other status entr{'y' if counts['other'] == 1 else 'ies'}.")
    if hidden:
        print(f"{hidden} status entr{'y' if hidden == 1 else 'ies'} for hidden or sensitive paths suppressed.")
    if len(lines) <= 1:
        print("Working tree clean.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devops-copilot",
        description="Safe, read-only checks for project files, Terraform, and Git.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="summarize files in a project directory")
    inspect_parser.add_argument(
        "directory", nargs="?", default=".", help="project directory to inspect (default: current directory)"
    )

    status_parser = subparsers.add_parser("status", help="show a read-only project overview")
    status_parser.add_argument(
        "directory", nargs="?", default=".", help="project directory to summarize (default: current directory)"
    )

    subparsers.add_parser("check", help="check availability of Git, Python, and Terraform")

    terraform_parser = subparsers.add_parser("terraform", help="check Terraform formatting and validation")
    terraform_parser.add_argument(
        "directory", nargs="?", default=".", help="Terraform module directory (default: current directory)"
    )

    analyze_parser = subparsers.add_parser(
        "terraform-analyze", help="summarize Terraform configuration using the optional parser"
    )
    analyze_parser.add_argument(
        "directory", nargs="?", default=".", help="Terraform module directory (default: current directory)"
    )

    git_parser = subparsers.add_parser("git-status", help="show status for a Git repository")
    git_parser.add_argument(
        "directory", nargs="?", default=".", help="repository directory (default: current directory)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "inspect":
        return inspect_project(args.directory)
    if args.command == "status":
        return inspect_project(args.directory)
    if args.command == "check":
        return check_tools()
    if args.command == "terraform":
        return terraform_check(args.directory)
    if args.command == "terraform-analyze":
        return terraform_analyze(args.directory)
    if args.command == "git-status":
        return git_status(args.directory)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
