---
name: pr-review
description: >
  Reviews GitHub Pull Requests across five dimensions: correctness, security, architecture,
  performance, and style. Use this skill whenever the user mentions PR review, pull request
  review, "review this PR", or wants structured feedback on a GitHub pull request.
  Posts findings as PR comments with severity ratings and a summary report.
---

# PR Review

## Architecture

This skill uses a **hybrid architecture**:

```
User triggers /pr-review <PR_NUMBER>
  ↓
Step 1: Fetch PR metadata + count changed files
  ↓
Step 2: Dispatch based on PR size
  ├─ Small PR (<10 files) → FAST PATH: Inline review in main context
  └─ Medium/Large PR (≥10 files) → WORKFLOW PATH: Parallel sub-agent review
```

### Fast Path (Small PRs)

For PRs with fewer than 10 changed files, review happens inline — the main model reads the reference checklists and examines the diff directly. This avoids sub-agent orchestration overhead for quick reviews.

### Workflow Path (Medium/Large PRs)

For PRs with 10 or more changed files, review is delegated to the `pr-review-workflow` which spawns 5 parallel agents (one per dimension), optionally verifies findings adversarially, and synthesizes a structured report. This provides:
- **Parallel review**: 5 agents work simultaneously, reducing wall-clock time
- **Focused context**: each agent only loads its dimension's checklist
- **Deeper analysis**: dedicated context per dimension → more thorough findings
- **Adversarial verification** (high effort): critical/high findings are independently verified to reduce false positives

## Workflow

### Step 1: Fetch PR Info

```bash
gh pr view <PR_NUMBER> --json number,title,headRefName,baseRefName,files,body,commits
```

Extract: `number`, `branch` (headRefName), `targetBranch` (baseRefName), file count (`files.length`), `headCommit` (last commit SHA: `commits[-1].oid`).

### Step 2: Determine Path

Count the number of changed files (`files.length` from the JSON above).

- **<10 files**: Use **Fast Path** (steps 3-5 below)
- **10-50 files**: Use **Workflow Path** with `effort: "medium"`
- **>50 files**: Ask the user if they want a focused review on specific paths, or proceed with `effort: "high"` via Workflow

### Step 3 (Fast Path): Inline Review

For small PRs, review directly in the current context:

1. Fetch the full diff: `gh pr diff <PR_NUMBER>`
2. Read any files that are new or heavily modified to understand full context
3. Read each reference checklist and examine the diff through that lens:

| # | Dimension | Focus | Reference |
|---|-----------|-------|-----------|
| 1 | Correctness | Bugs, logic errors, edge cases, race conditions, error handling gaps | `references/correctness.md` |
| 2 | Security | Injection, auth, data exposure, dependency risks | `references/security.md` |
| 3 | Architecture | Design consistency, coupling, SOLID violations, anti-patterns | `references/architecture.md` |
| 4 | Performance | N+1 queries, blocking calls, memory leaks, inefficient patterns | `references/performance.md` |
| 5 | Style | Naming, comments, code organization, project conventions | `references/style.md` |

4. Compile findings into the report template (see below)
5. Post findings (see Posting Strategy below)

### Step 3 (Workflow Path): Delegate to Sub-Agents

For medium/large PRs, invoke the parallel workflow:

```
Use the Workflow tool with:
  name: "pr-review-workflow"
  args: {
    prNumber: <PR_NUMBER>,
    branch: "<headRefName>",
    targetBranch: "<baseRefName>",
    effort: "medium"  // or "high" for >50 files with adversarial verification
  }
```

The workflow returns:
```json
{
  "report": "Full markdown report string",
  "findings": [{ "severity": "...", "dimension": "...", "summary": "...", "file": "...", "why": "...", "fix": "..." }],
  "summary": { "total": N, "bySeverity": {...}, "byDimension": {...} },
  "prNumber": N,
  "branch": "...",
  "targetBranch": "...",
  "effort": "..."
}
```

4. Use the returned `report` as the PR comment body
5. Post findings using the returned `findings` array (see Posting Strategy below)

## Severity Classification

Tag every finding with exactly one severity:

| Severity | Meaning | Examples |
|----------|---------|---------|
| `🔴 critical` | Must fix before merge — data loss, security breach, crash | SQL injection, unhandled exception crashing server, credential leak |
| `🟠 high` | Should fix before merge — broken functionality, significant risk | Logic error changing behavior, missing auth check, N+1 on hot path |
| `🟡 medium` | Fix in this PR or soon after — code quality, maintainability | Duplicated logic, misleading variable name, missing error handling |
| `🟢 low` | Nice to have, non-blocking — polish, minor improvements | Comment typo, slightly suboptimal pattern, missing docstring |
| `💡 suggestion` | Optional improvement idea, not a problem | Alternative approach worth considering, future optimization idea |

## Report Template

Generate the following markdown report. Replace `{PLACEHOLDER}` with actual content.

```markdown
## 🔍 PR Review: #{PR_NUMBER}

**Branch**: `{SOURCE_BRANCH}` → `{TARGET_BRANCH}`
**Files Changed**: {N} files
**Reviewed At**: {TIMESTAMP}

---

### 📊 Summary

| Dimension | 🔴 Critical | 🟠 High | 🟡 Medium | 🟢 Low | 💡 Suggestion |
|-----------|:-----------:|:--------:|:---------:|:------:|:-------------:|
| Correctness | {N} | {N} | {N} | {N} | {N} |
| Security | {N} | {N} | {N} | {N} | {N} |
| Architecture | {N} | {N} | {N} | {N} | {N} |
| Performance | {N} | {N} | {N} | {N} | {N} |
| Style | {N} | {N} | {N} | {N} | {N} |
| **Total** | **{N}** | **{N}** | **{N}** | **{N}** | **{N}** |

### 🚨 Must-Fix Before Merge

<!-- Only list 🔴 critical + 🟠 high findings here -->

{CRITICAL_AND_HIGH_FINDINGS}

---

### 📋 All Findings

{ALL_FINDINGS_GROUPED_BY_DIMENSION}

---

### ✅ Positives

<!-- What was done well — good patterns, clean code, smart solutions -->

{POSITIVES}
```

## Finding Format

Each individual finding must use this exact format:

```markdown
### [{SEVERITY_LABEL}] {DIMENSION}: {ONE_LINE_SUMMARY}

**File**: `{FILE_PATH}:{LINE}`
**Why**: {1-2 sentences explaining why this matters}
**Fix**: {Specific fix suggestion}

<!-- optional: code diff showing the fix -->
\`\`\`diff
- old code
+ new code
\`\`\`
```

## Posting Strategy

### Inline Line-Specific Comments (Critical & High findings)

For each `🔴 critical` or `🟠 high` finding, post an **inline PR review comment** that appears directly on the code line in the diff view:

```bash
# Parse the file path and line number from the finding
FILE_PATH="<finding.file without line number>"   # e.g. "server/app/api/analyze.py"
LINE_NUM="<line number from finding.file>"        # e.g. "42"

# Post inline review comment on the specific code line
gh api "repos/$(gh repo view --json nameWithOwner -q .nameWithOwner)/pulls/<PR_NUMBER>/comments" \
  -f body="### [{SEVERITY_LABEL}] {DIMENSION}: {ONE_LINE_SUMMARY}

**Why**: {1-2 sentences explaining why this matters}
**Fix**: {Specific fix suggestion}" \
  -f commit_id="<HEAD_COMMIT_SHA>" \
  -f path="$FILE_PATH" \
  -f line="$LINE_NUM"
```

**Key requirement**: `commit_id` MUST be the PR head commit SHA (obtained in Step 1). The `line` parameter refers to the line number in the **changed file** (not the diff position).

### Full Report Comment

After posting all inline comments, post the full report as a **PR summary comment**:

```bash
# For fast path: save report to file, then post
gh pr comment <PR_NUMBER> --body-file <report.md>

# For workflow path: report is already in the workflow output
gh pr comment <PR_NUMBER> --body "$REPORT_TEXT"
```

### Approval

If there are zero critical + high findings, start the PR review with a ✅ approval:

```bash
gh pr review <PR_NUMBER> --approve -b "✅ PR Review passed — no critical or high severity findings."
```

### Summary of the Flow

```
For each critical/high finding:
  → gh api .../pulls/{N}/comments (inline on code line, visible in diff view)

After all inline comments:
  → gh pr comment {N} --body "$REPORT" (full summary report)

If zero critical+high:
  → gh pr review {N} --approve (with explanation)
```

## Before Starting

- Verify `gh` CLI is authenticated and the repo is correct.
- Confirm the PR number with the user if not explicitly provided.
