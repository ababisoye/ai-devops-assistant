"""Command line interface for safe project and repository checks."""

from __future__ import annotations

import argparse
from bisect import bisect_right
from contextlib import redirect_stdout
import importlib
import ipaddress
import io
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

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
PUBLIC_S3_ACLS = {"public-read", "public-read-write"}
KNOWN_S3_CANNED_ACLS = {
    "private", "public-read", "public-read-write", "aws-exec-read",
    "authenticated-read", "bucket-owner-read", "bucket-owner-full-control",
    "log-delivery-write",
}
S3_PUBLIC_ACCESS_BLOCK_FIELDS = {
    "block_public_acls", "block_public_policy", "ignore_public_acls",
    "restrict_public_buckets",
}
WORKFLOW_WRITE_ALL_PATTERN = re.compile(
    r"^permissions\s*:\s*['\"]?write-all['\"]?\s*(?:#.*)?$"
)
DOCKER_FROM_PATTERN = re.compile(
    r"^\s*FROM\s+(?:(?:--platform=\S+)\s+)?(\S+)", re.IGNORECASE
)


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


def terraform_configuration_files(root: Path) -> list[Path]:
    """Find Terraform files under a project, excluding generated trees."""
    config_files = []
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            name for name in dirs if not should_skip_directory(Path(current, name))
        )
        for name in files:
            path = Path(current, name)
            if (
                (name.endswith(".tf") or name.endswith(".tf.json"))
                and not path.is_symlink()
            ):
                config_files.append(path)
    return sorted(config_files)


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


def find_json_public_s3_acls(document: dict) -> tuple[set[tuple[str, str]], bool]:
    """Find explicitly public canned ACLs without evaluating Terraform expressions."""
    resources = document.get("resource", {})
    if not isinstance(resources, dict):
        return set(), False

    resource_types = {
        "aws_s3_bucket", "aws_s3_bucket_acl", "aws_s3_object",
        "aws_s3_bucket_object",
    }
    findings = set()
    unresolved_acl = False
    for resource_type in resource_types:
        instances = resources.get(resource_type)
        if not isinstance(instances, dict):
            continue
        for body in instances.values():
            if not isinstance(body, dict) or "acl" not in body:
                continue
            values = _as_string_values(body.get("acl"))
            if not values:
                unresolved_acl = True
            for acl in values:
                if acl in PUBLIC_S3_ACLS:
                    findings.add((resource_type, acl))
                elif acl not in KNOWN_S3_CANNED_ACLS:
                    unresolved_acl = True
    return findings, unresolved_acl


def find_json_disabled_s3_public_access_block(
    document: dict,
) -> tuple[set[str], bool]:
    """Find literal false settings in bucket-level S3 public-access blocks."""
    resources = document.get("resource", {})
    if not isinstance(resources, dict):
        return set(), False
    instances = resources.get("aws_s3_bucket_public_access_block", {})
    if not isinstance(instances, dict):
        return set(), False
    findings = set()
    unresolved = False
    for body in instances.values():
        if not isinstance(body, dict):
            continue
        for field in S3_PUBLIC_ACCESS_BLOCK_FIELDS:
            if field not in body:
                continue
            value = body[field]
            if value is False:
                findings.add(field)
            elif value is not True:
                unresolved = True
    return findings, unresolved


def find_json_s3_versioning_not_enabled(document: dict) -> tuple[set[tuple[str, str]], bool]:
    """Find explicit suspended or disabled S3 bucket versioning settings."""
    resources = document.get("resource", {})
    if not isinstance(resources, dict):
        return set(), False
    findings = set()
    unresolved = False
    for resource_type in ("aws_s3_bucket_versioning", "aws_s3_bucket"):
        instances = resources.get(resource_type, {})
        if not isinstance(instances, dict):
            continue
        for body in instances.values():
            if not isinstance(body, dict):
                continue
            if resource_type == "aws_s3_bucket_versioning":
                configurations = _as_dict_blocks(body.get("versioning_configuration"))
                for configuration in configurations:
                    if "status" not in configuration:
                        continue
                    status = configuration["status"]
                    if isinstance(status, str) and status.lower() in {"disabled", "suspended"}:
                        findings.add((resource_type, status.lower()))
                    elif not isinstance(status, str) or status.lower() != "enabled":
                        unresolved = True
            else:
                versioning_blocks = _as_dict_blocks(body.get("versioning"))
                for configuration in versioning_blocks:
                    if "enabled" not in configuration:
                        continue
                    enabled = configuration["enabled"]
                    if enabled is False:
                        findings.add((resource_type, "disabled"))
                    elif enabled is not True:
                        unresolved = True
    return findings, unresolved


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


def normalized_hcl_resources(document: dict) -> dict:
    """Convert python-hcl2 resource blocks to a type-to-instance mapping."""
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
    return resources


def hcl_literal_attribute_lines(parse_tree) -> dict[tuple[str, tuple[str, ...], str, object], set[int]]:
    """Map literal HCL attributes to line numbers using parser positions."""
    locations = {}

    def child_nodes(node):
        return getattr(node, "children", [])

    def node_data(node):
        return str(getattr(node, "data", ""))

    def scalar_value(node):
        data = node_data(node)
        children = child_nodes(node)
        if data == "expr_term" and len(children) == 1:
            return scalar_value(children[0])
        if data == "literal_value" and len(children) == 1:
            token = children[0]
            token_type = getattr(token, "type", "")
            if token_type == "FALSE":
                return False
            if token_type == "TRUE":
                return True
            return None
        if data == "int_lit" and len(children) == 1:
            try:
                return int(getattr(children[0], "value", ""))
            except (TypeError, ValueError):
                return None
        if data == "float_lit" and len(children) == 1:
            try:
                return float(getattr(children[0], "value", ""))
            except (TypeError, ValueError):
                return None
        if data == "string":
            parts = []
            for child in children:
                if node_data(child) == "string_part":
                    tokens = child_nodes(child)
                    if len(tokens) != 1 or getattr(tokens[0], "type", "") != "STRING_CHARS":
                        return None
                    parts.append(str(getattr(tokens[0], "value", "")))
                elif getattr(child, "type", "") != "DBLQUOTE":
                    return None
            return "".join(parts)
        return None

    def literal_values(node):
        value = scalar_value(node)
        if value is not None:
            return [value]
        if node_data(node) == "expr_term" and len(child_nodes(node)) == 1:
            return literal_values(child_nodes(node)[0])
        if node_data(node) == "tuple":
            values = []
            for child in child_nodes(node):
                if node_data(child) != "expr_term":
                    continue
                child_value = scalar_value(child)
                if child_value is None:
                    return []
                values.append(child_value)
            return values
        return []

    def identifier(node):
        children = child_nodes(node)
        if node_data(node) == "identifier" and children:
            return str(getattr(children[0], "value", ""))
        return None

    def visit(node, resource_type=None, block_path=(), context_valid=True):
        data = node_data(node)
        if data == "block":
            children = child_nodes(node)
            block_name = identifier(children[0]) if children else None
            current_type = resource_type
            current_path = block_path
            current_context_valid = context_valid
            if resource_type is None and block_name == "resource" and len(children) > 1:
                current_type = scalar_value(children[1])
                current_path = ()
                if current_type == "aws_security_group_rule":
                    body = next(
                        (child for child in children if node_data(child) == "body"), None
                    )
                    current_context_valid = any(
                        node_data(attribute) == "attribute"
                        and child_nodes(attribute)
                        and identifier(child_nodes(attribute)[0]) == "type"
                        and len(child_nodes(attribute)) > 2
                        and scalar_value(child_nodes(attribute)[2]) == "ingress"
                        for attribute in child_nodes(body) if body is not None
                    )
            elif resource_type is not None and block_name:
                current_path = block_path + (block_name,)
            for child in children:
                if node_data(child) == "body":
                    visit(child, current_type, current_path, current_context_valid)
        elif data == "body":
            for child in child_nodes(node):
                visit(child, resource_type, block_path, context_valid)
        elif data == "attribute" and resource_type is not None and context_valid:
            children = child_nodes(node)
            name = identifier(children[0]) if children else None
            values = literal_values(children[2]) if len(children) > 2 else []
            line = getattr(getattr(node, "meta", None), "line", None)
            if name and isinstance(line, int):
                for value in values:
                    key = (resource_type, block_path, name, value)
                    locations.setdefault(key, set()).add(line)
        else:
            for child in child_nodes(node):
                visit(child, resource_type, block_path, context_valid)

    visit(parse_tree)
    return locations


def format_file_line_location(filename: str, line_numbers: set[int] | list[int]) -> str:
    """Format a visible source filename and any parser-provided HCL line numbers."""
    lines = sorted(set(line_numbers))
    location = f"(file: {filename}"
    if lines:
        location += f", line{'s' if len(lines) > 1 else ''}: "
        location += ", ".join(str(line) for line in lines)
    return location + ")"


def json_literal_attribute_lines(
    document: dict, source_text: str,
) -> dict[tuple[str, tuple[str, ...], str, object], set[int]]:
    """Map literal Terraform JSON attributes to their source lines."""
    if not isinstance(document, dict):
        return {}
    decoder = json.JSONDecoder()
    positions = {}
    line_starts = [0] + [index + 1 for index, char in enumerate(source_text) if char == "\n"]

    def skip_whitespace(index):
        while index < len(source_text) and source_text[index].isspace():
            index += 1
        return index

    def line_for(index):
        return bisect_right(line_starts, index)

    def parse_value(index, path):
        index = skip_whitespace(index)
        start = index
        if source_text[index] == "{":
            result = {}
            index = skip_whitespace(index + 1)
            if source_text[index] == "}":
                return result, index + 1
            while True:
                key, index = decoder.raw_decode(source_text, index)
                index = skip_whitespace(index)
                index += 1  # colon; the full document was already validated by json.loads
                value_start = skip_whitespace(index)
                value, index = parse_value(value_start, path + (key,))
                result[key] = value
                positions[path + (key,)] = (value, line_for(value_start))
                index = skip_whitespace(index)
                if source_text[index] == "}":
                    return result, index + 1
                index = skip_whitespace(index + 1)  # comma
        if source_text[index] == "[":
            result = []
            index = skip_whitespace(index + 1)
            if source_text[index] == "]":
                return result, index + 1
            while True:
                value, index = parse_value(index, path + (len(result),))
                result.append(value)
                index = skip_whitespace(index)
                if source_text[index] == "]":
                    return result, index + 1
                index = skip_whitespace(index + 1)  # comma
        value, index = decoder.raw_decode(source_text, index)
        positions[path] = (value, line_for(start))
        return value, index

    parse_value(0, ())
    locations = {}
    resources = document.get("resource", {})
    if not isinstance(resources, dict):
        return locations
    positions_by_resource = {}
    for path, value_and_line in positions.items():
        if len(path) >= 4 and path[0] == "resource":
            positions_by_resource.setdefault(path[:3], []).append((path, value_and_line))
    for resource_type, instances in resources.items():
        if not isinstance(instances, dict):
            continue
        for label, body in instances.items():
            if not isinstance(body, dict):
                continue
            if resource_type == "aws_security_group_rule" and body.get("type") != "ingress":
                continue
            prefix = ("resource", resource_type, label)
            for path, (value, line) in positions_by_resource.get(prefix, []):
                if len(path) < 4:
                    continue
                relative_string_parts = [part for part in path[3:] if isinstance(part, str)]
                if len(relative_string_parts) < 1:
                    continue
                attribute = relative_string_parts[-1]
                if not isinstance(attribute, str) or not isinstance(value, (str, bool, int, float)):
                    continue
                block_path = tuple(relative_string_parts[:-1])
                key = (resource_type, block_path, attribute, value)
                locations.setdefault(key, set()).add(line)
    return locations


def find_hcl_public_security_group_ingress(
    document: dict,
) -> tuple[set[tuple[str, str, str]], bool]:
    """Convert python-hcl2's block representation to the JSON rule's input shape."""
    normalized_document = dict(document)
    normalized_document["resource"] = normalized_hcl_resources(document)
    return find_json_public_security_group_ingress(normalized_document)


def find_hcl_public_s3_acls(document: dict) -> tuple[set[tuple[str, str]], bool]:
    """Check supported S3 canned ACL values in parsed HCL resources."""
    normalized_document = dict(document)
    normalized_document["resource"] = normalized_hcl_resources(document)
    return find_json_public_s3_acls(normalized_document)


def find_hcl_disabled_s3_public_access_block(document: dict) -> tuple[set[str], bool]:
    """Check literal boolean values in parsed S3 public-access block resources."""
    normalized_document = dict(document)
    normalized_document["resource"] = normalized_hcl_resources(document)
    return find_json_disabled_s3_public_access_block(normalized_document)


def find_hcl_s3_versioning_not_enabled(document: dict) -> tuple[set[str], bool]:
    """Check literal S3 bucket versioning settings in parsed HCL."""
    normalized_document = dict(document)
    normalized_document["resource"] = normalized_hcl_resources(document)
    return find_json_s3_versioning_not_enabled(normalized_document)


def find_json_unencrypted_ebs_volumes(document: dict) -> tuple[set[str], bool]:
    """Find literal encrypted=false on supported managed EBS configurations."""
    resources = document.get("resource", {})
    if not isinstance(resources, dict):
        return set(), False
    findings = set()
    unresolved = False

    def check_encryption(blocks, finding_type):
        nonlocal unresolved
        if isinstance(blocks, dict):
            blocks = [blocks]
        if not isinstance(blocks, list):
            unresolved = True
            return
        for block in blocks:
            if not isinstance(block, dict) or "encrypted" not in block:
                continue
            value = block["encrypted"]
            if value is False:
                findings.add(finding_type)
            elif value is not True:
                unresolved = True

    volume_resources = resources.get("aws_ebs_volume", {})
    if isinstance(volume_resources, dict):
        for body in volume_resources.values():
            if isinstance(body, dict):
                check_encryption(body, "aws_ebs_volume")

    instance_resources = resources.get("aws_instance", {})
    if isinstance(instance_resources, dict):
        for body in instance_resources.values():
            if not isinstance(body, dict):
                continue
            for block_type in ("root_block_device", "ebs_block_device"):
                if block_type in body:
                    check_encryption(body[block_type], f"aws_instance.{block_type}")

    launch_templates = resources.get("aws_launch_template", {})
    if isinstance(launch_templates, dict):
        for body in launch_templates.values():
            if not isinstance(body, dict):
                continue
            mappings = body.get("block_device_mappings", [])
            if isinstance(mappings, dict):
                mappings = [mappings]
            if not isinstance(mappings, list):
                unresolved = True
                continue
            for mapping in mappings:
                if isinstance(mapping, dict) and "ebs" in mapping:
                    check_encryption(
                        mapping["ebs"], "aws_launch_template.block_device_mappings.ebs"
                    )
    return findings, unresolved


def find_hcl_unencrypted_ebs_volumes(document: dict) -> tuple[set[str], bool]:
    """Check literal boolean encryption settings in parsed HCL resources."""
    normalized_document = dict(document)
    normalized_document["resource"] = normalized_hcl_resources(document)
    return find_json_unencrypted_ebs_volumes(normalized_document)


def find_json_optional_imdsv2(document: dict) -> tuple[set[str], bool]:
    """Find explicit token-optional settings on EC2 instances and launch templates."""
    resources = document.get("resource", {})
    if not isinstance(resources, dict):
        return set(), False
    findings = set()
    unresolved = False
    for resource_type in ("aws_instance", "aws_launch_template"):
        instances = resources.get(resource_type, {})
        if not isinstance(instances, dict):
            continue
        for body in instances.values():
            if not isinstance(body, dict) or "metadata_options" not in body:
                continue
            blocks = body["metadata_options"]
            if isinstance(blocks, dict):
                blocks = [blocks]
            if not isinstance(blocks, list):
                unresolved = True
                continue
            for block in blocks:
                if not isinstance(block, dict) or "http_tokens" not in block:
                    continue
                values = _as_string_values(block["http_tokens"])
                if values == ["optional"]:
                    findings.add(resource_type)
                elif values != ["required"]:
                    unresolved = True
    return findings, unresolved


def find_hcl_optional_imdsv2(document: dict) -> tuple[set[str], bool]:
    """Check literal http_tokens values in parsed EC2 HCL resources."""
    normalized_document = dict(document)
    normalized_document["resource"] = normalized_hcl_resources(document)
    return find_json_optional_imdsv2(normalized_document)


def find_json_public_rds_instances(document: dict) -> tuple[set[str], bool]:
    """Find explicitly public RDS DB instance settings in Terraform JSON."""
    resources = document.get("resource", {})
    if not isinstance(resources, dict):
        return set(), False
    instances = resources.get("aws_db_instance", {})
    if not isinstance(instances, dict):
        return set(), False
    findings = set()
    unresolved = False
    for body in instances.values():
        if not isinstance(body, dict) or "publicly_accessible" not in body:
            continue
        value = body["publicly_accessible"]
        if value is True:
            findings.add("aws_db_instance")
        elif value is not False:
            unresolved = True
    return findings, unresolved


def find_hcl_public_rds_instances(document: dict) -> tuple[set[str], bool]:
    """Check literal public accessibility settings in parsed RDS HCL."""
    normalized_document = dict(document)
    normalized_document["resource"] = normalized_hcl_resources(document)
    return find_json_public_rds_instances(normalized_document)


def find_json_unencrypted_rds_instances(document: dict) -> tuple[set[str], bool]:
    """Find literal storage_encrypted=false on RDS DB instance resources."""
    resources = document.get("resource", {})
    if not isinstance(resources, dict):
        return set(), False
    instances = resources.get("aws_db_instance", {})
    if not isinstance(instances, dict):
        return set(), False
    findings = set()
    unresolved = False
    for body in instances.values():
        if not isinstance(body, dict) or "storage_encrypted" not in body:
            continue
        value = body["storage_encrypted"]
        if value is False:
            findings.add("aws_db_instance")
        elif value is not True:
            unresolved = True
    return findings, unresolved


def find_hcl_unencrypted_rds_instances(document: dict) -> tuple[set[str], bool]:
    """Check literal storage_encrypted values in parsed RDS HCL."""
    normalized_document = dict(document)
    normalized_document["resource"] = normalized_hcl_resources(document)
    return find_json_unencrypted_rds_instances(normalized_document)


def find_json_unprotected_rds_instances(document: dict) -> tuple[set[str], bool]:
    """Find explicit deletion_protection=false on RDS DB instances."""
    resources = document.get("resource", {})
    if not isinstance(resources, dict):
        return set(), False
    instances = resources.get("aws_db_instance", {})
    if not isinstance(instances, dict):
        return set(), False
    findings = set()
    unresolved = False
    for body in instances.values():
        if not isinstance(body, dict) or "deletion_protection" not in body:
            continue
        value = body["deletion_protection"]
        if value is False:
            findings.add("aws_db_instance")
        elif value is not True:
            unresolved = True
    return findings, unresolved


def find_hcl_unprotected_rds_instances(document: dict) -> tuple[set[str], bool]:
    """Check literal deletion-protection settings in parsed RDS HCL."""
    normalized_document = dict(document)
    normalized_document["resource"] = normalized_hcl_resources(document)
    return find_json_unprotected_rds_instances(normalized_document)


def find_json_rds_skip_final_snapshot(document: dict) -> tuple[set[str], bool]:
    """Find explicit skip_final_snapshot=true on RDS DB instances."""
    resources = document.get("resource", {})
    if not isinstance(resources, dict):
        return set(), False
    instances = resources.get("aws_db_instance", {})
    if not isinstance(instances, dict):
        return set(), False
    findings = set()
    unresolved = False
    for body in instances.values():
        if not isinstance(body, dict) or "skip_final_snapshot" not in body:
            continue
        value = body["skip_final_snapshot"]
        if value is True:
            findings.add("aws_db_instance")
        elif value is not False:
            unresolved = True
    return findings, unresolved


def find_hcl_rds_skip_final_snapshot(document: dict) -> tuple[set[str], bool]:
    """Check literal final-snapshot behavior in parsed RDS HCL."""
    normalized_document = dict(document)
    normalized_document["resource"] = normalized_hcl_resources(document)
    return find_json_rds_skip_final_snapshot(normalized_document)


def find_json_rds_automated_backups_disabled(document: dict) -> tuple[set[str], bool]:
    """Find backup_retention_period=0 on RDS DB instance resources."""
    resources = document.get("resource", {})
    if not isinstance(resources, dict):
        return set(), False
    instances = resources.get("aws_db_instance", {})
    if not isinstance(instances, dict):
        return set(), False
    findings = set()
    unresolved = False
    for body in instances.values():
        if not isinstance(body, dict) or "backup_retention_period" not in body:
            continue
        value = body["backup_retention_period"]
        if type(value) is int and value == 0:
            findings.add("aws_db_instance")
        elif type(value) is not int:
            unresolved = True
    return findings, unresolved


def find_hcl_rds_automated_backups_disabled(document: dict) -> tuple[set[str], bool]:
    """Check literal automated-backup retention in parsed RDS HCL."""
    normalized_document = dict(document)
    normalized_document["resource"] = normalized_hcl_resources(document)
    return find_json_rds_automated_backups_disabled(normalized_document)


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
    config_files = terraform_configuration_files(root)
    visible_files = [path for path in config_files if not is_sensitive_name(path.name)]
    display_names = {
        path: path.relative_to(root).as_posix() for path in visible_files
    }
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
    public_s3_acl_findings = set()
    unresolved_s3_acl = False
    disabled_s3_pab_fields = set()
    unresolved_s3_pab = False
    non_versioned_s3_statuses = set()
    unresolved_s3_versioning = False
    explicit_unencrypted_ebs = set()
    unresolved_ebs_encryption = False
    optional_imdsv2_resources = set()
    unresolved_imdsv2 = False
    public_rds_resources = set()
    unresolved_rds_public_access = False
    unencrypted_rds_resources = set()
    unresolved_rds_encryption = False
    unprotected_rds_resources = set()
    unresolved_rds_deletion_protection = False
    rds_skip_snapshot_resources = set()
    unresolved_rds_snapshot = False
    rds_no_automated_backups_resources = set()
    unresolved_rds_backup_retention = False
    source_lines_by_file = {}
    for path in visible_files:
        if path.name.endswith(".tf") and hcl2 is None:
            skipped_hcl_files += 1
            continue
        try:
            with path.open("r", encoding="utf-8") as config_file:
                if path.name.endswith(".tf.json"):
                    source_text = config_file.read()
                    document = json.loads(source_text)
                    source_lines_by_file[display_names[path]] = json_literal_attribute_lines(
                        document, source_text
                    )
                else:
                    source_text = config_file.read()
                    document = hcl2.load(io.StringIO(source_text))
                    parse_to_tree = getattr(hcl2, "parse_to_tree", None)
                    if callable(parse_to_tree):
                        try:
                            parse_tree = parse_to_tree(io.StringIO(source_text))
                            source_lines_by_file[display_names[path]] = hcl_literal_attribute_lines(parse_tree)
                        except Exception:
                            # Parsing succeeded; locations are optional presentation data.
                            source_lines_by_file[display_names[path]] = {}
        except json.JSONDecodeError as error:
            print(
                f"Could not parse {display_names[path]} at line {error.lineno}, column {error.colno}; "
                "file contents and parser details were suppressed."
            )
            failed_files += 1
            continue
        except Exception:
            print(f"Could not parse {display_names[path]}; parser details were suppressed.")
            failed_files += 1
            continue

        if not isinstance(document, dict):
            failed_files += 1
            print(f"Could not summarize {display_names[path]}; parser details were suppressed.")
            continue
        analyzed_files += 1
        if path.name.endswith(".tf.json"):
            analyzed_json_files += 1
            ingress_findings, unresolved_cidr = find_json_public_security_group_ingress(document)
            s3_acl_findings, unresolved_acl = find_json_public_s3_acls(document)
            pab_fields, unresolved_pab = find_json_disabled_s3_public_access_block(document)
            s3_versioning_statuses, unresolved_versioning = find_json_s3_versioning_not_enabled(document)
            unencrypted_ebs, unresolved_ebs = find_json_unencrypted_ebs_volumes(document)
            imdsv2_findings, unresolved_imds = find_json_optional_imdsv2(document)
            rds_findings, unresolved_rds = find_json_public_rds_instances(document)
            unencrypted_rds, unresolved_rds_storage = find_json_unencrypted_rds_instances(document)
            unprotected_rds, unresolved_rds_protection = find_json_unprotected_rds_instances(document)
            skip_snapshot_rds, unresolved_rds_snapshot_value = find_json_rds_skip_final_snapshot(document)
            no_backup_rds, unresolved_rds_retention = find_json_rds_automated_backups_disabled(document)
        else:
            analyzed_hcl_files += 1
            ingress_findings, unresolved_cidr = find_hcl_public_security_group_ingress(document)
            s3_acl_findings, unresolved_acl = find_hcl_public_s3_acls(document)
            pab_fields, unresolved_pab = find_hcl_disabled_s3_public_access_block(document)
            s3_versioning_statuses, unresolved_versioning = find_hcl_s3_versioning_not_enabled(document)
            unencrypted_ebs, unresolved_ebs = find_hcl_unencrypted_ebs_volumes(document)
            imdsv2_findings, unresolved_imds = find_hcl_optional_imdsv2(document)
            rds_findings, unresolved_rds = find_hcl_public_rds_instances(document)
            unencrypted_rds, unresolved_rds_storage = find_hcl_unencrypted_rds_instances(document)
            unprotected_rds, unresolved_rds_protection = find_hcl_unprotected_rds_instances(document)
            skip_snapshot_rds, unresolved_rds_snapshot_value = find_hcl_rds_skip_final_snapshot(document)
            no_backup_rds, unresolved_rds_retention = find_hcl_rds_automated_backups_disabled(document)
        unresolved_ingress_cidr = unresolved_ingress_cidr or unresolved_cidr
        public_ingress_findings.update(
            (display_names[path], resource_type, cidr, context)
            for resource_type, cidr, context in ingress_findings
        )
        public_s3_acl_findings.update(
            (display_names[path], resource_type, acl)
            for resource_type, acl in s3_acl_findings
        )
        unresolved_s3_acl = unresolved_s3_acl or unresolved_acl
        disabled_s3_pab_fields.update((display_names[path], field) for field in pab_fields)
        unresolved_s3_pab = unresolved_s3_pab or unresolved_pab
        non_versioned_s3_statuses.update(
            (display_names[path], resource_type, status)
            for resource_type, status in s3_versioning_statuses
        )
        unresolved_s3_versioning = unresolved_s3_versioning or unresolved_versioning
        explicit_unencrypted_ebs.update(
            (display_names[path], finding_type) for finding_type in unencrypted_ebs
        )
        unresolved_ebs_encryption = unresolved_ebs_encryption or unresolved_ebs
        optional_imdsv2_resources.update(
            (display_names[path], resource_type) for resource_type in imdsv2_findings
        )
        unresolved_imdsv2 = unresolved_imdsv2 or unresolved_imds
        public_rds_resources.update((display_names[path], resource_type) for resource_type in rds_findings)
        unresolved_rds_public_access = unresolved_rds_public_access or unresolved_rds
        unencrypted_rds_resources.update(
            (display_names[path], resource_type) for resource_type in unencrypted_rds
        )
        unresolved_rds_encryption = unresolved_rds_encryption or unresolved_rds_storage
        unprotected_rds_resources.update(
            (display_names[path], resource_type) for resource_type in unprotected_rds
        )
        unresolved_rds_deletion_protection = (
            unresolved_rds_deletion_protection or unresolved_rds_protection
        )
        rds_skip_snapshot_resources.update(
            (display_names[path], resource_type) for resource_type in skip_snapshot_rds
        )
        unresolved_rds_snapshot = unresolved_rds_snapshot or unresolved_rds_snapshot_value
        rds_no_automated_backups_resources.update(
            (display_names[path], resource_type) for resource_type in no_backup_rds
        )
        unresolved_rds_backup_retention = unresolved_rds_backup_retention or unresolved_rds_retention
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
            version = ipaddress.ip_network(cidr).version
            if resource_type == "aws_vpc_security_group_ingress_rule":
                attribute = "cidr_ipv4" if version == 4 else "cidr_ipv6"
                block_path = ()
            else:
                attribute = "cidr_blocks" if version == 4 else "ipv6_cidr_blocks"
                block_path = ("ingress",) if resource_type == "aws_security_group" else ()
            location = format_file_line_location(
                filename,
                source_lines_by_file.get(filename, {}).get(
                    (resource_type, block_path, attribute, cidr), set()
                ),
            )
            print(
                f"Potential public ingress: {resource_type} rule open to "
                f"{cidr} ({context}). "
                f"Static analysis cannot confirm deployed exposure. {location}."
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
    if public_s3_acl_findings:
        for filename, resource_type, acl in sorted(public_s3_acl_findings):
            line_numbers = source_lines_by_file.get(filename, {}).get(
                (resource_type, (), "acl", acl), set()
            )
            print(
                f"Potential public S3 ACL: {resource_type} uses {acl}. "
                "This static finding does not confirm effective public access; "
                "bucket or account Block Public Access settings may override it. "
                f"{format_file_line_location(filename, line_numbers)}."
            )
    if unresolved_s3_acl:
        print(
            "S3 ACL check incomplete: one or more ACL values could not be "
            "resolved; their values were not printed."
        )
    elif not public_s3_acl_findings and analyzed_files:
        print(
            "S3 ACL check: no supported literal public canned ACLs found. "
            "Policies and grant blocks are outside this check."
        )
    if disabled_s3_pab_fields:
        for filename, field in sorted(disabled_s3_pab_fields):
            line_numbers = source_lines_by_file.get(filename, {}).get(
                ("aws_s3_bucket_public_access_block", (), field, False), set()
            )
            print(
                f"S3 public-access protection disabled: "
                f"aws_s3_bucket_public_access_block sets {field} = false. "
                "This is a configuration finding; account or organization-level "
                f"settings and effective access were not checked. "
                f"{format_file_line_location(filename, line_numbers)}."
            )
    if unresolved_s3_pab:
        print(
            "S3 public-access block check incomplete: one or more protection "
            "settings could not be resolved; their values were not printed."
        )
    for filename, resource_type, status in sorted(non_versioned_s3_statuses):
        if status == "suspended":
            key = (resource_type, ("versioning_configuration",), "status", "Suspended")
            message = (
                "S3 bucket versioning is suspended; new object writes do not get "
                "unique versions. Existing versions and live bucket state were not assessed."
            )
        else:
            block_path, attribute, value = (
                ("versioning",), "enabled", False
            ) if resource_type == "aws_s3_bucket" else (
                ("versioning_configuration",), "status", "Disabled"
            )
            key = (resource_type, block_path, attribute, value)
            message = (
                "S3 bucket versioning is explicitly disabled; object version history "
                "is not configured by this setting. Live bucket state was not assessed."
            )
        location = format_file_line_location(
            filename, source_lines_by_file.get(filename, {}).get(key, set())
        )
        print(f"Potential S3 versioning disabled: {message} {location}.")
    if unresolved_s3_versioning:
        print(
            "S3 versioning check incomplete: one or more versioning settings "
            "could not be resolved; their values were not printed."
        )
    ebs_source_paths = {
        "aws_ebs_volume": ("aws_ebs_volume", (), "encrypted", False),
        "aws_instance.root_block_device": (
            "aws_instance", ("root_block_device",), "encrypted", False,
        ),
        "aws_instance.ebs_block_device": (
            "aws_instance", ("ebs_block_device",), "encrypted", False,
        ),
        "aws_launch_template.block_device_mappings.ebs": (
            "aws_launch_template", ("block_device_mappings", "ebs"), "encrypted", False,
        ),
    }
    for filename, finding_type in sorted(explicit_unencrypted_ebs):
        key = ebs_source_paths[finding_type]
        location = format_file_line_location(
            filename, source_lines_by_file.get(filename, {}).get(key, set())
        )
        print(
            f"Potential unencrypted EBS volume setting: {finding_type} explicitly "
            "sets encrypted = false. Account-level EBS encryption by default may "
            f"override this setting; deployed encryption was not checked. {location}."
        )
    if unresolved_ebs_encryption:
        print(
            "EBS encryption check incomplete: one or more supported EBS "
            "encryption settings could not be resolved; their values were not printed."
        )
    for filename, resource_type in sorted(optional_imdsv2_resources):
        location = format_file_line_location(
            filename,
            source_lines_by_file.get(filename, {}).get(
                (resource_type, ("metadata_options",), "http_tokens", "optional"), set()
            ),
        )
        print(
            f"Potential IMDSv1 allowed: {resource_type} sets "
            "http_tokens = optional. This is a static configuration finding; "
            "account settings, launch overrides, and deployed behavior were not checked. "
            f"{location}."
        )
    if unresolved_imdsv2:
        print(
            "IMDS token setting check incomplete: one or more http_tokens values "
            "could not be resolved; their values were not printed."
        )
    for filename, resource_type in sorted(public_rds_resources):
        location = format_file_line_location(
            filename,
            source_lines_by_file.get(filename, {}).get(
                (resource_type, (), "publicly_accessible", True), set()
            ),
        )
        print(
            f"Potential publicly accessible RDS configuration: {resource_type} "
            "sets publicly_accessible = true. This requests public accessibility; "
            "reachability also depends on subnet routing and network rules. "
            f"Static analysis did not inspect deployed state. {location}."
        )
    if unresolved_rds_public_access:
        print(
            "RDS public-access check incomplete: one or more publicly_accessible "
            "values could not be resolved; their values were not printed."
        )
    for filename, resource_type in sorted(unencrypted_rds_resources):
        location = format_file_line_location(
            filename,
            source_lines_by_file.get(filename, {}).get(
                (resource_type, (), "storage_encrypted", False), set()
            ),
        )
        print(
            f"Potential unencrypted RDS storage: {resource_type} explicitly sets "
            "storage_encrypted = false. This is a static configuration finding; "
            "cross-region read-replica behavior may differ, and deployed encryption "
            f"was not checked. {location}."
        )
    if unresolved_rds_encryption:
        print(
            "RDS storage-encryption check incomplete: one or more "
            "storage_encrypted values could not be resolved; their values were not printed."
        )
    for filename, resource_type in sorted(unprotected_rds_resources):
        location = format_file_line_location(
            filename,
            source_lines_by_file.get(filename, {}).get(
                (resource_type, (), "deletion_protection", False), set()
            ),
        )
        print(
            f"Potential RDS deletion protection disabled: {resource_type} explicitly "
            "sets deletion_protection = false. AWS permissions are still required "
            "to delete a database; live settings were not checked. "
            f"{location}."
        )
    if unresolved_rds_deletion_protection:
        print(
            "RDS deletion-protection check incomplete: one or more "
            "deletion_protection values could not be resolved; their values were not printed."
        )
    for filename, resource_type in sorted(rds_skip_snapshot_resources):
        location = format_file_line_location(
            filename,
            source_lines_by_file.get(filename, {}).get(
                (resource_type, (), "skip_final_snapshot", True), set()
            ),
        )
        print(
            f"Potential RDS final snapshot skipped: {resource_type} explicitly sets "
            "skip_final_snapshot = true. If Terraform later deletes this instance, "
            "no final snapshot is requested; other backups were not assessed. "
            f"{location}."
        )
    if unresolved_rds_snapshot:
        print(
            "RDS final-snapshot check incomplete: one or more "
            "skip_final_snapshot values could not be resolved; their values were not printed."
        )
    for filename, resource_type in sorted(rds_no_automated_backups_resources):
        location = format_file_line_location(
            filename,
            source_lines_by_file.get(filename, {}).get(
                (resource_type, (), "backup_retention_period", 0), set()
            ),
        )
        print(
            f"Potential RDS automated backups disabled: {resource_type} explicitly "
            "sets backup_retention_period = 0. This disables RDS automated backups "
            "where the setting applies; AWS Backup plans and other snapshots were "
            f"not assessed. {location}."
        )
    if unresolved_rds_backup_retention:
        print(
            "RDS automated-backup check incomplete: one or more "
            "backup_retention_period values could not be resolved; their values were not printed."
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


def terraform_review(
    directory: str, explain: bool = False, model: str = "qwen3:1.7b"
) -> int:
    """Run local Terraform checks and optionally explain safe findings."""
    print("Terraform formatting and validation checks:")
    check_status = terraform_check(directory)
    if check_status == 2:
        return check_status

    print("\nTerraform static analysis:")
    analysis_output = io.StringIO()
    if explain:
        with redirect_stdout(analysis_output):
            analysis_status = terraform_analyze(directory)
        report = analysis_output.getvalue()
        print(report, end="")
    else:
        analysis_status = terraform_analyze(directory)
        report = ""

    if analysis_status != 0:
        if explain:
            print("AI explanation skipped because Terraform analysis was incomplete.")
        return 1

    if explain:
        context = safe_terraform_explanation_context(report)
        if context:
            print("AI explanation (generated from the static findings above):")
            explanation_status = ask_local_model(
                "Explain these Terraform findings to a beginner. Separate what the static "
                "check observed from what remains unknown. Give safe review steps, and do "
                "not claim the deployed environment is secure or exposed.",
                model,
                context=context,
            )
            if explanation_status != 0:
                return explanation_status
        else:
            print("No supported Terraform finding was available to explain.")

    if check_status != 0:
        return 1
    print("Review finished. Read the findings above before using this configuration.")
    return 0


def safe_terraform_explanation_context(analysis_output: str) -> str:
    """Build model context from fixed, allowlisted static-analysis summaries."""
    facts = []
    s3_acl_pattern = re.compile(
        r"Potential public S3 ACL: (aws_s3_bucket|aws_s3_bucket_acl|"
        r"aws_s3_object|aws_s3_bucket_object) uses (public-read|public-read-write)\."
    )
    s3_pab_pattern = re.compile(
        r"S3 public-access protection disabled: aws_s3_bucket_public_access_block "
        r"sets (block_public_acls|block_public_policy|ignore_public_acls|"
        r"restrict_public_buckets) = false\."
    )
    finding_pattern = re.compile(
        r"(?: contains an |Potential public ingress: )"
        r"(aws_security_group|aws_security_group_rule|"
        r"aws_vpc_security_group_ingress_rule) rule open to (0\.0\.0\.0/0|::/0) "
        r"\(([^()]*)\)\."
    )
    for line in analysis_output.splitlines():
        if len(facts) >= 20:
            facts.append("Additional findings were omitted from the AI explanation for brevity.")
            break
        if line.startswith("Potential public ingress:"):
            match = finding_pattern.search(line)
            if match:
                resource_type, cidr, context = match.groups()
                facts.append(
                    f"Potential internet-wide inbound rule: {resource_type}, "
                    f"{cidr}, {context}. This is a static Terraform finding; "
                    "deployed exposure is unverified."
                )
        elif line.startswith("Public-ingress check incomplete:"):
            facts.append(
                "The public-ingress check is incomplete because some CIDRs "
                "could not be resolved; their values were omitted."
            )
        elif line.startswith("Public-ingress check: no internet-wide ingress found"):
            facts.append(
                "The static check found no internet-wide ingress in the analyzed "
                "Terraform security group rules. This does not prove the deployed "
                "environment is secure."
            )
        elif line.startswith("Potential public S3 ACL:"):
            match = s3_acl_pattern.search(line)
            if match:
                resource_type, acl = match.groups()
                facts.append(
                    f"Potential public S3 ACL in {resource_type}: {acl}. This is "
                    "a static configuration finding; bucket or account Block Public "
                    "Access settings may override it, and effective access is unverified."
                )
        elif line.startswith("S3 ACL check incomplete:"):
            facts.append(
                "The static S3 ACL check is incomplete because one or more ACL "
                "values could not be resolved; their values were omitted."
            )
        elif line.startswith("S3 ACL check: no supported literal public canned ACLs found."):
            facts.append(
                "The static check found no supported literal public S3 canned ACLs. "
                "Bucket policies and grant blocks were not analyzed."
            )
        elif line.startswith("S3 public-access protection disabled:"):
            match = s3_pab_pattern.search(line)
            if match:
                facts.append(
                    f"The bucket-level S3 public-access protection setting "
                    f"{match.group(1)} is explicitly false. This does not confirm "
                    "effective public access; account and organization settings "
                    "were not checked."
                )
        elif line.startswith("Potential S3 versioning disabled:"):
            match = re.search(
                r"Potential S3 versioning disabled: (S3 bucket versioning is "
                r"(?:suspended|explicitly disabled)[^.]*\.)", line
            )
            if match:
                facts.append(match.group(1) + " This is a static Terraform finding; live bucket state is unverified.")
        elif line.startswith("S3 versioning check incomplete:"):
            facts.append(
                "The S3 versioning check is incomplete because a setting could "
                "not be resolved; its value was omitted."
            )
        elif line.startswith("S3 public-access block check incomplete:"):
            facts.append(
                "The S3 public-access block check is incomplete because a setting "
                "could not be resolved; its value was omitted."
            )
        elif line.startswith("Potential unencrypted EBS volume setting:"):
            match = re.search(
                r"Potential unencrypted EBS volume setting: "
                r"(aws_ebs_volume|aws_instance\.(?:root_block_device|ebs_block_device)|"
                r"aws_launch_template\.block_device_mappings\.ebs) explicitly",
                line,
            )
            if match:
                facts.append(
                    f"Terraform explicitly sets encrypted=false on {match.group(1)}. "
                    "Account-level EBS encryption by default may override this; "
                    "deployed encryption was not checked."
                )
        elif line.startswith("EBS encryption check incomplete:"):
            facts.append(
                "The EBS encryption check is incomplete because a setting could "
                "not be resolved; its value was omitted."
            )
        elif line.startswith("Potential IMDSv1 allowed:"):
            match = re.search(
                r"Potential IMDSv1 allowed: (aws_instance|aws_launch_template) sets",
                line,
            )
            if match:
                facts.append(
                    f"Terraform sets http_tokens=optional on {match.group(1)}, which "
                    "allows IMDSv1 compatibility. Account settings, launch overrides, "
                    "and deployed behavior were not checked."
                )
        elif line.startswith("IMDS token setting check incomplete:"):
            facts.append(
                "The IMDS token setting check is incomplete because a value could "
                "not be resolved; the value was omitted."
            )
        elif line.startswith("Potential publicly accessible RDS configuration:"):
            if re.search(
                r"Potential publicly accessible RDS configuration: aws_db_instance "
                r"sets publicly_accessible = true\.",
                line,
            ):
                facts.append(
                    "Terraform sets publicly_accessible=true on aws_db_instance. "
                    "This requests public accessibility, but actual reachability "
                    "depends on subnet routing and network rules; deployed state "
                    "was not checked."
                )
        elif line.startswith("RDS public-access check incomplete:"):
            facts.append(
                "The RDS public-access check is incomplete because a setting "
                "could not be resolved; its value was omitted."
            )
        elif line.startswith("Potential unencrypted RDS storage:"):
            if re.search(
                r"Potential unencrypted RDS storage: aws_db_instance explicitly "
                r"sets storage_encrypted = false\.",
                line,
            ):
                facts.append(
                    "Terraform explicitly sets storage_encrypted=false on "
                    "aws_db_instance. Cross-region read-replica behavior may differ; "
                    "deployed encryption was not checked."
                )
        elif line.startswith("RDS storage-encryption check incomplete:"):
            facts.append(
                "The RDS storage-encryption check is incomplete because a setting "
                "could not be resolved; its value was omitted."
            )
        elif line.startswith("Potential RDS deletion protection disabled:"):
            if re.search(
                r"Potential RDS deletion protection disabled: aws_db_instance "
                r"explicitly sets deletion_protection = false\.",
                line,
            ):
                facts.append(
                    "Terraform explicitly sets deletion_protection=false on "
                    "aws_db_instance. AWS permissions are still required to delete "
                    "it; live settings were not checked."
                )
        elif line.startswith("RDS deletion-protection check incomplete:"):
            facts.append(
                "The RDS deletion-protection check is incomplete because a setting "
                "could not be resolved; its value was omitted."
            )
        elif line.startswith("Potential RDS final snapshot skipped:"):
            if re.search(
                r"Potential RDS final snapshot skipped: aws_db_instance explicitly "
                r"sets skip_final_snapshot = true\.",
                line,
            ):
                facts.append(
                    "Terraform sets skip_final_snapshot=true on aws_db_instance. "
                    "A later Terraform deletion would not request a final snapshot; "
                    "other backups were not assessed."
                )
        elif line.startswith("RDS final-snapshot check incomplete:"):
            facts.append(
                "The RDS final-snapshot check is incomplete because a setting "
                "could not be resolved; its value was omitted."
            )
        elif line.startswith("Potential RDS automated backups disabled:"):
            if re.search(
                r"Potential RDS automated backups disabled: aws_db_instance explicitly "
                r"sets backup_retention_period = 0\.",
                line,
            ):
                facts.append(
                    "Terraform sets backup_retention_period=0 on aws_db_instance. "
                    "This disables RDS automated backups where the setting applies; "
                    "AWS Backup plans and other snapshots were not assessed."
                )
        elif line.startswith("RDS automated-backup check incomplete:"):
            facts.append(
                "The RDS automated-backup check is incomplete because a setting "
                "could not be resolved; its value was omitted."
            )
        elif line == "Recommendation: consider declaring a required_version constraint.":
            facts.append("The analyzed configuration does not declare a Terraform required_version constraint.")
        elif line == "Terraform version constraint: found.":
            facts.append("The analyzed configuration declares a Terraform version constraint.")
    return "\n".join(facts)


def terraform_explain(directory: str, model: str = "qwen3:1.7b") -> int:
    """Explain allowlisted Terraform analyzer findings using the local model."""
    analysis = io.StringIO()
    with redirect_stdout(analysis):
        analysis_status = terraform_analyze(directory)
    report = analysis.getvalue()
    print(report, end="")
    if analysis_status != 0:
        print("AI explanation skipped because Terraform analysis was incomplete.")
        return analysis_status

    context = safe_terraform_explanation_context(report)
    if not context:
        print("No supported Terraform finding was available to explain.")
        return 0

    print("AI explanation (generated from the static findings above):")
    return ask_local_model(
        "Explain these Terraform findings to a beginner. Separate what the static "
        "check observed from what remains unknown. Give safe review steps, and do "
        "not claim the deployed environment is secure or exposed.",
        model,
        context=context,
    )


def aws_security_groups(region: str | None = None) -> int:
    """Read AWS security group rules and report internet-wide ingress only."""
    executable = shutil.which("aws")
    if executable is None:
        print("AWS CLI is not installed or is not available on PATH.", file=sys.stderr)
        return 1

    command = [executable, "ec2", "describe-security-group-rules", "--output", "json", "--no-cli-pager"]
    if region:
        command.extend(["--region", region])
    try:
        result = subprocess.run(
            command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        print("AWS security group check could not be completed.", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(
            "AWS security group check failed. Check your AWS CLI sign-in, permissions, and region; "
            "raw AWS output was suppressed.",
            file=sys.stderr,
        )
        return 1
    try:
        document = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError):
        print("AWS returned an unexpected response; details were suppressed.", file=sys.stderr)
        return 1
    rules = document.get("SecurityGroupRules") if isinstance(document, dict) else None
    if not isinstance(rules, list):
        print("AWS returned an unexpected response; details were suppressed.", file=sys.stderr)
        return 1

    findings = set()
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("IsEgress") is not False:
            continue
        public_cidr = None
        if rule.get("CidrIpv4") == "0.0.0.0/0":
            public_cidr = "0.0.0.0/0"
        elif rule.get("CidrIpv6") == "::/0":
            public_cidr = "::/0"
        if public_cidr:
            normalized_rule = {
                "from_port": rule.get("FromPort"),
                "to_port": rule.get("ToPort"),
                "IpProtocol": rule.get("IpProtocol"),
            }
            findings.add((public_cidr, _ingress_context(normalized_rule, "IpProtocol")))

    if region:
        print(f"AWS security group check: region {region}.")
    else:
        print("AWS security group check: configured default region.")
    if findings:
        for cidr, context in sorted(findings):
            print(f"Potential public ingress: rule open to {cidr} ({context}).")
        print("This is a live AWS rule check; it does not test whether a service is reachable.")
    else:
        print("No internet-wide inbound security group rules found in the returned rules.")
    return 0


def ask_local_model(
    question: str,
    model: str = "qwen3:1.7b",
    context: str | None = None,
    system_instruction: str | None = None,
    max_output_tokens: int = 300,
    output_path: str | None = None,
) -> int:
    """Ask an optional local Ollama model; no project files are sent."""
    if not question.strip():
        print("Please enter a question.", file=sys.stderr)
        return 2
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_instruction or (
                    "You are DevOps Copilot, a beginner-friendly DevOps assistant. "
                    "Give concise, practical explanations. You only know the question and "
                    "optional short diagnostic summary provided here; you cannot inspect "
                    "the user's computer or cloud account. Separate static observations "
                    "from assumptions. Never claim infrastructure changes are safe; "
                    "tell the user to review changes themselves."
                ),
            },
            {
                "role": "user",
                "content": question.strip() + (
                    "\n\nSanitized local diagnostic summary:\n" + context
                    if context else ""
                ),
            },
        ],
        "stream": False,
        "options": {
            "num_ctx": 2048,
            "num_predict": max_output_tokens,
            "temperature": 0.2,
        },
    }
    request = Request(
        "http://localhost:11434/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        # Ignore HTTP proxy environment variables so prompts stay on localhost.
        opener = build_opener(ProxyHandler({}))
        with opener.open(request, timeout=180) as response:
            document = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError):
        print(
            "Could not reach the local Ollama service. Start Ollama and check that the selected model is installed.",
            file=sys.stderr,
        )
        return 1
    except (UnicodeDecodeError, json.JSONDecodeError):
        print("Ollama returned an unexpected response; details were suppressed.", file=sys.stderr)
        return 1

    message = document.get("message") if isinstance(document, dict) else None
    answer = message.get("content") if isinstance(message, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        print("Ollama returned no answer; details were suppressed.", file=sys.stderr)
        return 1
    if output_path is None:
        print(answer.strip())
        return 0

    path = Path(output_path).expanduser()
    try:
        file_descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as draft_file:
            draft_file.write(answer.strip() + "\n")
    except FileExistsError:
        print("Output file already exists; refusing to overwrite it.", file=sys.stderr)
        return 2
    except OSError:
        print("Could not save the draft. Check that the directory exists and is writable.", file=sys.stderr)
        return 1
    print(f"Unverified Terraform draft saved to: {path}")
    print("Review the file before using it; it has not been formatted, validated, or applied.")
    return 0


def terraform_draft(
    requirements: str,
    model: str = "qwen3:1.7b",
    output_path: str | None = None,
) -> int:
    """Print an unverified Terraform draft from requirements using local AI."""
    requirements = requirements.strip()
    if not requirements:
        print("Please describe what the Terraform configuration should create.", file=sys.stderr)
        return 2
    if len(requirements) > 5000:
        print("Requirements are too long; please keep them under 5,000 characters.", file=sys.stderr)
        return 2
    if output_path:
        target = Path(output_path).expanduser()
        if target.suffix.lower() != ".tf":
            print("Output path must end in .tf.", file=sys.stderr)
            return 2
        if target.exists():
            print("Output file already exists; choose a new filename.", file=sys.stderr)
            return 2

    if output_path:
        print("Generating an unverified draft. The output file will not be overwritten.")
    else:
        print("Unreviewed Terraform draft follows. It is not written, validated, or applied.\n")
    return ask_local_model(
        requirements,
        model,
        system_instruction=(
            "You draft Terraform HCL for a beginner to review. Return HCL only, "
            "without Markdown fences or a prose introduction. Use safe defaults: "
            "add a short plain-language HCL comment immediately before each "
            "top-level block, explaining what that block configures. "
            "do not open network access to the whole internet unless the request "
            "clearly requires it; never include real credentials or hard-coded "
            "secrets; avoid remote backend configuration. If a required detail "
            "is missing, add a TODO comment instead of inventing a risky value. "
            "Keep the configuration small and explain uncertain assumptions in "
            "HCL comments. The result is an unverified draft, not validated code. "
            "Do not propose or run terraform apply or terraform destroy."
        ),
        max_output_tokens=1200,
        output_path=output_path,
    )


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


def github_actions_check(directory: str) -> int:
    """Check workflow files for the explicit broad write-all token permission."""
    root = Path(directory).expanduser()
    if not root.exists() or not root.is_dir():
        print(f"Error: project directory does not exist or is not a directory: {root}", file=sys.stderr)
        return 2
    root = root.resolve()
    workflows_dir = root / ".github" / "workflows"
    if (root / ".github").is_symlink() or workflows_dir.is_symlink() or not workflows_dir.is_dir():
        print("No GitHub Actions workflow directory found (.github/workflows).")
        return 0

    try:
        workflow_files = sorted(
            path for path in workflows_dir.iterdir()
            if path.is_file() and not path.is_symlink()
            and path.suffix.lower() in {".yml", ".yaml"}
            and not is_sensitive_name(path.name)
        )
    except OSError:
        print("GitHub Actions workflow files could not be listed.", file=sys.stderr)
        return 1
    if not workflow_files:
        print("No visible GitHub Actions workflow files found.")
        return 0

    print(f"GitHub Actions workflow files checked: {len(workflow_files)}")
    findings = []
    read_errors = 0
    for path in workflow_files:
        try:
            with path.open("r", encoding="utf-8") as workflow_file:
                for line_number, line in enumerate(workflow_file, start=1):
                    if line.lstrip().startswith("#"):
                        continue
                    if WORKFLOW_WRITE_ALL_PATTERN.match(line.rstrip("\r\n")):
                        findings.append((path.relative_to(root).as_posix(), line_number))
        except (OSError, UnicodeError):
            read_errors += 1

    for filename, line_number in findings:
        print(
            f"Potential broad workflow-level GitHub Actions token permissions: explicit "
            f"permissions: write-all in {filename} at line {line_number}. "
            "Consider granting only the permissions the workflow needs."
        )
    if not findings:
        print(
            "No explicit permissions: write-all setting found by this check. "
            "This limited text check does not validate YAML or assess effective permissions."
        )
    if read_errors:
        print(f"{read_errors} workflow file(s) could not be read; those files were skipped.")
    return 1 if findings or read_errors else 0


def dockerfile_check(directory: str) -> int:
    """Flag Dockerfile base images with an implicit or explicit latest tag."""
    root = Path(directory).expanduser()
    if not root.exists() or not root.is_dir():
        print(f"Error: project directory does not exist or is not a directory: {root}", file=sys.stderr)
        return 2
    root = root.resolve()
    dockerfiles = []
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            name for name in dirs if not should_skip_directory(Path(current, name))
        )
        for name in files:
            path = Path(current, name)
            is_dockerfile = (
                name == "Dockerfile" or name.startswith("Dockerfile.")
                or name.endswith(".Dockerfile")
            )
            if is_dockerfile and not is_sensitive_name(name) and not path.is_symlink():
                relative = path.relative_to(root).as_posix()
                if not any(ord(char) < 32 or ord(char) == 127 for char in relative):
                    dockerfiles.append(path)

    if not dockerfiles:
        print("No visible Dockerfiles found.")
        return 0

    findings = []
    unresolved = False
    read_errors = 0
    for path in sorted(dockerfiles):
        filename = path.relative_to(root).as_posix()
        try:
            with path.open("r", encoding="utf-8") as dockerfile:
                for line_number, line in enumerate(dockerfile, start=1):
                    match = DOCKER_FROM_PATTERN.match(line)
                    if not match:
                        continue
                    image = match.group(1)
                    if "$" in image:
                        unresolved = True
                        continue
                    if "@" in image or image.lower() == "scratch":
                        continue
                    final_part = image.rsplit("/", 1)[-1]
                    if ":" not in final_part:
                        findings.append((filename, line_number, "implicit"))
                    elif final_part.rsplit(":", 1)[-1].lower() == "latest":
                        findings.append((filename, line_number, "explicit"))
        except (OSError, UnicodeError):
            read_errors += 1

    print(f"Dockerfiles checked: {len(dockerfiles)}")
    for filename, line_number, tag_kind in findings:
        tag_description = "implicit latest tag" if tag_kind == "implicit" else "explicit latest tag"
        print(
            f"Potential unpinned container base image in {filename} at line "
            f"{line_number}: uses the {tag_description}. Pin a reviewed version "
            "or image digest."
        )
    if not findings:
        print("No implicit or explicit latest base image tags found in supported FROM lines.")
    if unresolved:
        print("Dockerfile check incomplete: one or more FROM image references use variables.")
    if read_errors:
        print(f"{read_errors} Dockerfile(s) could not be read; those files were skipped.")
    return 1 if findings or read_errors else 0


def project_review(directory: str) -> int:
    """Run the local Terraform, GitHub Actions, and Dockerfile static checks."""
    root = Path(directory).expanduser()
    if not root.exists() or not root.is_dir():
        print(f"Error: project directory does not exist or is not a directory: {root}", file=sys.stderr)
        return 2

    checks = (
        ("Terraform analysis", terraform_analyze),
        ("GitHub Actions check", github_actions_check),
        ("Dockerfile check", dockerfile_check),
    )
    failed = False
    for label, check in checks:
        print(f"{label}:")
        if check(str(root)) != 0:
            failed = True
    if failed:
        print("Project review finished with one or more incomplete or failed checks.")
        return 1
    print("Project review finished; all available local checks passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devops-copilot",
        description="Safe, read-only checks for project files, Terraform, Git, GitHub Actions, and Dockerfiles.",
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

    review_parser = subparsers.add_parser(
        "terraform-review", help="run local Terraform checks and static analysis together"
    )
    review_parser.add_argument(
        "directory", nargs="?", default=".", help="Terraform module directory (default: current directory)"
    )
    review_parser.add_argument(
        "--explain", action="store_true", help="explain supported findings with local Ollama"
    )
    review_parser.add_argument(
        "--model", default="qwen3:1.7b", help="installed Ollama model (default: qwen3:1.7b)"
    )

    explain_parser = subparsers.add_parser(
        "terraform-explain", help="explain safe Terraform findings with a local Ollama model"
    )
    explain_parser.add_argument(
        "directory", nargs="?", default=".", help="Terraform module directory (default: current directory)"
    )
    explain_parser.add_argument(
        "--model", default="qwen3:1.7b", help="installed Ollama model (default: qwen3:1.7b)"
    )

    aws_parser = subparsers.add_parser(
        "aws-security-groups", help="read AWS security group rules and flag internet-wide ingress"
    )
    aws_parser.add_argument("--region", help="AWS region (default: AWS CLI configured region)")

    ask_parser = subparsers.add_parser(
        "ask", help="ask a question using an optional local Ollama model"
    )
    ask_parser.add_argument("question", help="question to send to the local model")
    ask_parser.add_argument(
        "--model", default="qwen3:1.7b", help="installed Ollama model (default: qwen3:1.7b)"
    )

    draft_parser = subparsers.add_parser(
        "terraform-draft", help="print an unverified Terraform draft using local Ollama"
    )
    draft_parser.add_argument("requirements", help="plain-language description of the desired infrastructure")
    draft_parser.add_argument(
        "--model", default="qwen3:1.7b", help="installed Ollama model (default: qwen3:1.7b)"
    )
    draft_parser.add_argument(
        "--output", "-o", help="save to a new .tf file; an existing file is never overwritten"
    )

    git_parser = subparsers.add_parser("git-status", help="show status for a Git repository")
    git_parser.add_argument(
        "directory", nargs="?", default=".", help="repository directory (default: current directory)"
    )
    actions_parser = subparsers.add_parser(
        "github-actions-check",
        help="check local workflow files for explicit write-all token permissions",
    )
    actions_parser.add_argument(
        "directory", nargs="?", default=".", help="project directory (default: current directory)"
    )
    docker_parser = subparsers.add_parser(
        "dockerfile-check", help="check local Dockerfiles for mutable default/latest base image tags"
    )
    docker_parser.add_argument(
        "directory", nargs="?", default=".", help="project directory (default: current directory)"
    )
    project_review_parser = subparsers.add_parser(
        "project-review", help="run local Terraform, workflow, and Dockerfile checks"
    )
    project_review_parser.add_argument(
        "directory", nargs="?", default=".", help="project directory (default: current directory)"
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
    if args.command == "terraform-review":
        return terraform_review(args.directory, args.explain, args.model)
    if args.command == "terraform-explain":
        return terraform_explain(args.directory, args.model)
    if args.command == "aws-security-groups":
        return aws_security_groups(args.region)
    if args.command == "ask":
        return ask_local_model(args.question, args.model)
    if args.command == "terraform-draft":
        return terraform_draft(args.requirements, args.model, args.output)
    if args.command == "git-status":
        return git_status(args.directory)
    if args.command == "github-actions-check":
        return github_actions_check(args.directory)
    if args.command == "dockerfile-check":
        return dockerfile_check(args.directory)
    if args.command == "project-review":
        return project_review(args.directory)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
