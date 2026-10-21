"""Minimal packaging metadata for installing DevOps Copilot and optional extras."""

from setuptools import find_packages, setup

from devops_copilot import __version__


setup(
    name="devops-copilot",
    version=__version__,
    description="Safe, read-only DevOps project and workflow diagnostics",
    packages=find_packages(exclude=("tests", "tests.*")),
    py_modules=["main"],
    python_requires=">=3.9",
    extras_require={"terraform": ["python-hcl2>=8.1.4,<9"]},
    entry_points={"console_scripts": ["devops-copilot=devops_copilot.cli:main"]},
)
