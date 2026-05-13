#!/usr/bin/env python3
"""
Web3 Documentation Quality Auditor
Analyzes a GitHub repository's documentation and produces a quality report.
Use as a free lead magnet for the Web3 documentation service.

Usage: python3 doc_audit.py <owner/repo> [--token GITHUB_TOKEN]
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime


def gh_api(endpoint, token=None):
    """Call GitHub API with optional auth."""
    url = f"https://api.github.com{endpoint}"
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "doc-audit-tool"}
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def get_file_content(owner, repo, path, token=None):
    """Get file content from GitHub."""
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "doc-audit-tool"}
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if isinstance(data, dict) and "content" in data:
                import base64
                return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, Exception):
        pass
    return None


def analyze_readme(content):
    """Analyze README quality and return score + findings."""
    if not content:
        return 0, ["No README.md found"]
    
    score = 0
    findings = []
    word_count = len(content.split())
    
    # Length scoring
    if word_count >= 500:
        score += 20
        findings.append(f"README has {word_count} words (good depth)")
    elif word_count >= 200:
        score += 10
        findings.append(f"README has {word_count} words (adequate)")
    else:
        findings.append(f"README only has {word_count} words (too short)")
    
    # Section checks
    sections = {
        "installation": r"(?i)(install|setup|getting.started|quick.start)",
        "usage": r"(?i)(usage|example|how.to|getting.started)",
        "api": r"(?i)(api|endpoint|reference|documentation)",
        "contributing": r"(?i)(contribut|develop|build)",
        "license": r"(?i)(license|mit|apache|gpl)",
        "badges": r"!\[.*?\]\(.*?badge.*?\)|!\[.*?\]\(https://img\.shields\.io",
        "code_blocks": r"```[\s\S]*?```",
        "links": r"\[.*?\]\(.*?\)",
    }
    
    for name, pattern in sections.items():
        matches = re.findall(pattern, content)
        if matches:
            if name in ("installation", "usage"):
                score += 10
                findings.append(f"Has {name} section")
            elif name == "api":
                score += 8
                findings.append(f"Has {name} documentation")
            elif name == "code_blocks":
                count = len(matches)
                if count >= 3:
                    score += 10
                    findings.append(f"Has {count} code examples")
                elif count >= 1:
                    score += 5
                    findings.append(f"Has {count} code example(s)")
            elif name == "badges":
                score += 3
                findings.append("Has status badges")
            elif name == "links":
                if len(matches) >= 3:
                    score += 5
                    findings.append(f"Has {len(matches)} links")
            elif name in ("contributing", "license"):
                score += 3
                findings.append(f"Has {name} section")
    
    return min(score, 100), findings


def check_code_examples(owner, repo, tree, token=None):
    """Check for code examples, tests, and runnable tools."""
    score = 0
    findings = []
    paths = [item["path"] for item in tree]
    
    # Examples directory
    example_dirs = [p for p in paths if re.match(r"^(examples?|demo|sample|tutorial)", p, re.I)]
    if example_dirs:
        score += 15
        findings.append(f"Has examples directory: {example_dirs[0]}")
    
    # Test files
    test_files = [p for p in paths if re.search(r"(test|spec|__test__)\.[\w]+$", p, re.I)]
    if test_files:
        score += 10
        findings.append(f"Has {len(test_files)} test file(s)")
    
    # Scripts/tools directory
    script_dirs = [p for p in paths if re.match(r"^(scripts?|tools?|bin|cli)", p, re.I)]
    if script_dirs:
        score += 12
        findings.append(f"Has tools/scripts directory: {script_dirs[0]}")
    
    # CI/CD
    ci_files = [p for p in paths if ".github/workflows" in p or p in ("Jenkinsfile", ".gitlab-ci.yml", ".circleci/config.yml")]
    if ci_files:
        score += 10
        findings.append(f"Has CI/CD: {ci_files[0]}")
    
    # Docker
    docker_files = [p for p in paths if re.search(r"(Dockerfile|docker-compose)", p, re.I)]
    if docker_files:
        score += 8
        findings.append(f"Has Docker: {docker_files[0]}")
    
    # Config files
    config_patterns = {
        "package.json": 3,
        "tsconfig.json": 2,
        ".env.example": 5,
        "Makefile": 3,
        "Cargo.toml": 3,
        "requirements.txt": 2,
        "pyproject.toml": 3,
    }
    for pattern, pts in config_patterns.items():
        if pattern in paths:
            score += pts
            findings.append(f"Has {pattern}")
    
    return min(score, 100), findings


def check_documentation_files(owner, repo, tree, token=None):
    """Check for dedicated documentation files."""
    score = 0
    findings = []
    paths = [item["path"] for item in tree]
    
    # Docs directory
    doc_dirs = [p for p in paths if re.match(r"^(docs?|documentation|wiki|guides?)", p, re.I)]
    if doc_dirs:
        score += 15
        findings.append(f"Has documentation directory: {doc_dirs[0]}")
    
    # Specific doc files
    doc_files = {
        "CHANGELOG.md": ("changelog", 5),
        "CONTRIBUTING.md": ("contributing guide", 5),
        "SECURITY.md": ("security policy", 8),
        "ARCHITECTURE.md": ("architecture doc", 10),
        "API.md": ("API reference", 10),
        "TROUBLESHOOTING.md": ("troubleshooting guide", 8),
    }
    for filename, (label, pts) in doc_files.items():
        if filename in paths:
            score += pts
            findings.append(f"Has {label} ({filename})")
    
    # Multiple markdown files (depth indicator)
    md_files = [p for p in paths if p.endswith(".md")]
    if len(md_files) >= 5:
        score += 10
        findings.append(f"Has {len(md_files)} markdown files (comprehensive)")
    elif len(md_files) >= 2:
        score += 5
        findings.append(f"Has {len(md_files)} markdown files")
    
    return min(score, 100), findings


def grade(score):
    """Convert score to letter grade."""
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 60: return "C"
    if score >= 50: return "D"
    return "F"


def generate_report(owner, repo, readme_score, readme_findings, code_score, code_findings, doc_score, doc_findings):
    """Generate formatted audit report."""
    total = int(readme_score * 0.4 + code_score * 0.3 + doc_score * 0.3)
    
    report = f"""
{'='*60}
  WEB3 DOCUMENTATION QUALITY AUDIT
  Repository: {owner}/{repo}
  Date: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}
{'='*60}

OVERALL SCORE: {total}/100 (Grade: {grade(total)})

{'─'*60}
  README QUALITY: {readme_score}/100 (Weight: 40%)
{'─'*60}
"""
    for f in readme_findings:
        report += f"  {'✓' if not f.startswith('No') and 'too short' not in f.lower() else '✗'} {f}\n"
    
    report += f"""
{'─'*60}
  CODE AND TOOLING: {code_score}/100 (Weight: 30%)
{'─'*60}
"""
    for f in code_findings:
        report += f"  ✓ {f}\n"
    if not code_findings:
        report += "  ✗ No code examples, tests, or tools found\n"
    
    report += f"""
{'─'*60}
  DOCUMENTATION DEPTH: {doc_score}/100 (Weight: 30%)
{'─'*60}
"""
    for f in doc_findings:
        report += f"  ✓ {f}\n"
    if not doc_findings:
        report += "  ✗ No dedicated documentation files found\n"
    
    # Recommendations
    report += f"""
{'─'*60}
  RECOMMENDATIONS
{'─'*60}
"""
    recs = []
    if readme_score < 50:
        recs.append("HIGH: Expand README with installation, usage, and API sections (target 500+ words)")
    if readme_score < 70:
        recs.append("MED: Add more code examples to README (target 3+ fenced code blocks)")
    if code_score < 50:
        recs.append("HIGH: Add runnable examples/ directory with working code")
    if code_score < 70:
        recs.append("MED: Add test suite and CI/CD pipeline")
    if doc_score < 50:
        recs.append("HIGH: Create docs/ directory with step-by-step tutorials")
    if doc_score < 70:
        recs.append("MED: Add CHANGELOG.md, CONTRIBUTING.md, and SECURITY.md")
    if not any("Docker" in f for f in code_findings):
        recs.append("LOW: Add Docker setup for reproducible development environment")
    
    if not recs:
        recs.append("Documentation quality is good! Consider adding more advanced guides.")
    
    for i, rec in enumerate(recs, 1):
        report += f"  {i}. {rec}\n"
    
    report += f"""
{'='*60}
  Want this audit done professionally? 
  I write developer tutorials with runnable code for Web3 projects.
  
  Free 15-min scope call: richard202605@proton.me
  Portfolio: https://richard202605.github.io/web3-docs-service/
{'='*60}
"""
    return report, total


def main():
    parser = argparse.ArgumentParser(description="Web3 Documentation Quality Auditor")
    parser.add_argument("repo", help="GitHub repository (owner/repo)")
    parser.add_argument("--token", help="GitHub API token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    
    parts = args.repo.strip("/").split("/")
    if len(parts) != 2:
        print("Error: Please provide owner/repo format (e.g., ethereum/go-ethereum)")
        sys.exit(1)
    
    owner, repo = parts
    token = args.token
    
    print(f"Auditing {owner}/{repo}...")
    
    # Get repo info
    repo_data = gh_api(f"/repos/{owner}/{repo}", token)
    if not repo_data:
        print(f"Error: Repository {owner}/{repo} not found")
        sys.exit(1)
    
    # Get file tree
    default_branch = repo_data.get("default_branch", "main")
    tree_data = gh_api(f"/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1", token)
    if not tree_data or "tree" not in tree_data:
        print("Error: Could not fetch repository tree")
        sys.exit(1)
    
    tree = tree_data["tree"]
    
    # Analyze README
    readme_content = get_file_content(owner, repo, "README.md", token)
    if not readme_content:
        readme_content = get_file_content(owner, repo, "readme.md", token)
    readme_score, readme_findings = analyze_readme(readme_content)
    
    # Analyze code/tooling
    code_score, code_findings = check_code_examples(owner, repo, tree, token)
    
    # Analyze documentation
    doc_score, doc_findings = check_documentation_files(owner, repo, tree, token)
    
    if args.json:
        result = {
            "repo": f"{owner}/{repo}",
            "overall_score": int(readme_score * 0.4 + code_score * 0.3 + doc_score * 0.3),
            "readme": {"score": readme_score, "findings": readme_findings},
            "code": {"score": code_score, "findings": code_findings},
            "documentation": {"score": doc_score, "findings": doc_findings},
        }
        print(json.dumps(result, indent=2))
    else:
        report, total = generate_report(owner, repo, readme_score, readme_findings, code_score, code_findings, doc_score, doc_findings)
        print(report)


if __name__ == "__main__":
    main()
