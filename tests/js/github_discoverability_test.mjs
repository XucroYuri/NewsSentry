import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const repoRoot = dirname(dirname(dirname(fileURLToPath(import.meta.url))));

function read(path) {
  return readFileSync(join(repoRoot, path), "utf8");
}

function assertIncludes(file, expected) {
  const content = read(file);
  assert(
    content.includes(expected),
    `${file} must include: ${expected}`,
  );
}

function assertNotIncludes(file, unexpected) {
  const content = read(file);
  assert(
    !content.includes(unexpected),
    `${file} must not include stale phrase: ${unexpected}`,
  );
}

const englishReadmeTerms = [
  "AI news intelligence",
  "OSINT monitoring platform",
  "canonical event graph",
  "professional research workflows",
  "source health",
  "multilingual news",
  "human-in-the-loop",
  "Quick Start",
  "Use Cases",
  "Roadmap",
];

for (const term of englishReadmeTerms) {
  assertIncludes("README_en.md", term);
}

const chineseReadmeTerms = [
  "AI 新闻情报",
  "OSINT 监控平台",
  "canonical event graph",
  "专业研究工作流",
  "信源健康",
  "多语言新闻",
  "人在回路",
  "快速开始",
  "典型使用场景",
  "路线图",
];

for (const term of chineseReadmeTerms) {
  assertIncludes("README.md", term);
}

assertIncludes(
  "pyproject.toml",
  'description = "Open-source AI news intelligence and OSINT monitoring platform for multilingual news, social media, canonical event graphs, and research workflows"',
);
assertIncludes("pyproject.toml", '"osint"');
assertIncludes("pyproject.toml", '"news-intelligence"');
assertIncludes("pyproject.toml", '"event-graph"');
assertIncludes("pyproject.toml", '"research-workflow"');
assertNotIncludes(
  "pyproject.toml",
  "Italy Breaking News reference target",
);

assertIncludes(
  "docs/github-discoverability.md",
  "Open-source AI news intelligence and OSINT monitoring platform for multilingual news, social media, canonical event graphs, and research workflows.",
);
assertIncludes("docs/github-discoverability.md", "gh repo edit");
assertIncludes("docs/github-discoverability.md", "osint");
assertIncludes("docs/github-discoverability.md", "event-graph");

const templateFiles = [
  ".github/ISSUE_TEMPLATE/bug_report.md",
  ".github/ISSUE_TEMPLATE/feature_request.md",
  ".github/ISSUE_TEMPLATE/source_request.md",
  ".github/ISSUE_TEMPLATE/research_workflow_request.md",
  ".github/PULL_REQUEST_TEMPLATE.md",
];

for (const file of templateFiles) {
  assertIncludes(file, "News Sentry");
}

assertIncludes(".github/ISSUE_TEMPLATE/bug_report.md", "Pipeline stage");
assertIncludes(".github/ISSUE_TEMPLATE/source_request.md", "## Source Region");
assertIncludes(".github/ISSUE_TEMPLATE/research_workflow_request.md", "## Research Workflow Area");
assertIncludes(".github/PULL_REQUEST_TEMPLATE.md", "## Canonical Contracts");
assertIncludes(".github/PULL_REQUEST_TEMPLATE.md", "## Sensitive Data");
