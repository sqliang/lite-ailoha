export const meta = {
  name: 'pr-review-workflow',
  description: 'Parallel multi-dimensional PR review — 5 agents review independently, then findings are verified and synthesized into a structured report.',
  phases: [
    { title: 'Review', detail: '5 parallel dimension-specific review agents' },
    { title: 'Verify', detail: 'Adversarial verification of critical/high findings' },
    { title: 'Synthesize', detail: 'Compile findings into structured markdown report' },
  ],
}

// -- Dimensions and their checklists ------------------------------------------

const DIMENSIONS = [
  { key: 'correctness', label: 'Correctness', checklist: '.claude/skills/pr-review/references/correctness.md' },
  { key: 'security', label: 'Security', checklist: '.claude/skills/pr-review/references/security.md' },
  { key: 'architecture', label: 'Architecture', checklist: '.claude/skills/pr-review/references/architecture.md' },
  { key: 'performance', label: 'Performance', checklist: '.claude/skills/pr-review/references/performance.md' },
  { key: 'style', label: 'Style', checklist: '.claude/skills/pr-review/references/style.md' },
]

// -- JSON Schemas for structured agent output ---------------------------------

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low', 'suggestion'] },
          dimension: { type: 'string', enum: ['correctness', 'security', 'architecture', 'performance', 'style'] },
          summary: { type: 'string', description: 'One-line description of the issue' },
          file: { type: 'string', description: 'File path with optional line number, e.g. server/app/api/analyze.py:42' },
          why: { type: 'string', description: '1-2 sentences explaining real-world impact' },
          fix: { type: 'string', description: 'Specific, actionable fix suggestion' },
        },
        required: ['severity', 'dimension', 'summary', 'file', 'why', 'fix'],
      },
    },
  },
  required: ['findings'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    isReal: { type: 'boolean', description: 'Is this a genuine issue that should be addressed?' },
    confidence: { type: 'integer', minimum: 0, maximum: 100, description: 'How confident are you in this verdict?' },
    reasoning: { type: 'string', description: 'Brief explanation of the verdict' },
  },
  required: ['isReal', 'confidence', 'reasoning'],
}

// -- Args ---------------------------------------------------------------------

const { prNumber, branch, targetBranch, effort = 'medium' } = args

// -- Phase 1: Parallel dimension reviews -------------------------------------

phase('Review')

const reviewPrompts = DIMENSIONS.map(dim => `
You are reviewing PR #${prNumber} (${branch} → ${targetBranch}) for the **lite-ailoha** project.

## Review Focus: ${dim.label}

You must review the changes **exclusively through the lens of ${dim.label.toLowerCase()}**. Ignore issues that belong to other review dimensions.

## Steps

1. **Read the checklist** at \`${dim.checklist}\` — this contains all the specific items you must check for the ${dim.label} dimension.
2. **Fetch the PR diff** by running: \`gh pr diff ${prNumber}\`
3. **Read key files** if the diff lacks context — use Read to examine the full file around changed lines.
4. **Examine every change** in the diff against each item in the checklist.
5. **Return findings** for every checklist item that the diff violates or concerning patterns you identify.

## Project Context

lite-ailoha is a Python FastAPI server + Swift iOS app with:
- **SSE streaming protocol**: every event must have \`event:\`, \`id:\`, \`data:\` lines
- **4 canonical card types**: \`create_meeting\`, \`create_contact\`, \`update_contact\`, \`create_reminder\`
- **Dual-model LLM architecture**: VISION_MODEL (Coordinator) + LLM_MODEL (Subagents)
- **Comment conventions**: Chinese comments for SSE pipeline, data persistence, agent tool I/O, and model config areas
- **Python 3.11+**: \`match\`/\`case\` syntax is expected and encouraged
- **API prefix**: all endpoints use \`/api/v1/\`
- **Mock-first iOS dev**: \`AnalysisService.useMock = true\` for offline development

## Severity Guide

- \`critical\`: data loss, security breach, crash — must fix before merge
- \`high\`: broken functionality, significant risk — should fix before merge
- \`medium\`: code quality, maintainability — fix in this PR or soon
- \`low\`: polish, minor improvements — non-blocking
- \`suggestion\`: optional idea, not a problem

## Output

Return your findings as structured output. Each finding MUST include: severity, dimension (use "${dim.key}"), summary, file (with line number), why, and fix.
If you find no issues after thorough review, return an empty findings array — never fabricate problems.
`)

const reviewResults = await parallel(
  DIMENSIONS.map((dim, i) => () =>
    agent(reviewPrompts[i], {
      label: `review:${dim.key}`,
      phase: 'Review',
      schema: FINDINGS_SCHEMA,
      agentType: 'pr-reviewer',
    })
  )
)

const allFindings = reviewResults
  .filter(Boolean)
  .flatMap(r => r.findings)
  .filter(f => f && f.severity && f.summary)

log(`${allFindings.length} total findings across ${DIMENSIONS.length} dimensions`)

// -- Phase 2: Adversarial verification (high effort only) --------------------

const verifiedFindings = []

if (effort === 'high') {
  phase('Verify')

  const criticalAndHigh = allFindings.filter(f => f.severity === 'critical' || f.severity === 'high')

  if (criticalAndHigh.length > 0) {
    log(`Verifying ${criticalAndHigh.length} critical/high findings...`)

    const verifyResults = await parallel(
      criticalAndHigh.map(f => () =>
        agent(`
You are an adversarial verifier for PR review findings. Your job is to determine whether a reported issue is a **genuine problem** or a **false positive**.

## The Finding to Verify

- **Severity**: ${f.severity}
- **Dimension**: ${f.dimension}
- **Summary**: ${f.summary}
- **File**: ${f.file}
- **Why it matters**: ${f.why}
- **Suggested fix**: ${f.fix}

## Instructions

1. Read the file at \`${f.file.split(':')[0]}\` to understand the surrounding code.
2. Consider whether:
   - The issue is pre-existing (not introduced by this PR)?
   - The code pattern is intentional and justified?
   - The suggested fix would actually improve things?
   - There's a reason the code is written this way that the reviewer may have missed?
3. Default to \`isReal: true\` — only refute if you have concrete evidence the finding is wrong.

Return your verdict as structured output.
`, {
          label: `verify:${f.summary.slice(0, 40)}`,
          phase: 'Verify',
          schema: VERDICT_SCHEMA,
        })
      )
    )

    // Keep findings where verification confirms or is uncertain (confidence >= 50)
    const confirmedSet = new Set()
    criticalAndHigh.forEach((f, i) => {
      const v = verifyResults[i]
      if (v && (v.isReal || v.confidence >= 50)) {
        confirmedSet.add(i)
      } else if (v) {
        log(`Refuted: ${f.summary.slice(0, 60)} (confidence: ${v.confidence})`)
      }
    })

    // Verified critical/high + all medium/low/suggestion pass through
    allFindings.forEach((f, i) => {
      const isCriticalOrHigh = f.severity === 'critical' || f.severity === 'high'
      if (!isCriticalOrHigh) {
        verifiedFindings.push(f)
      } else {
        const idx = criticalAndHigh.indexOf(f)
        if (idx >= 0 && confirmedSet.has(idx)) {
          verifiedFindings.push(f)
        }
      }
    })

    log(`${verifiedFindings.length} findings after verification (${allFindings.length - verifiedFindings.length} refuted)`)
  } else {
    verifiedFindings.push(...allFindings)
    log('No critical/high findings to verify')
  }
} else {
  verifiedFindings.push(...allFindings)
}

// -- Phase 3: Synthesize report ----------------------------------------------

phase('Synthesize')

// Group findings by dimension
const byDimension = {}
DIMENSIONS.forEach(d => { byDimension[d.key] = [] })
verifiedFindings.forEach(f => {
  if (byDimension[f.dimension]) {
    byDimension[f.dimension].push(f)
  }
})

// Count by severity
const severityOrder = ['critical', 'high', 'medium', 'low', 'suggestion']
const countBySeverity = {}
severityOrder.forEach(s => { countBySeverity[s] = verifiedFindings.filter(f => f.severity === s).length })

// Build dimension summary rows
const dimensionRows = DIMENSIONS.map(d => {
  const dimFindings = byDimension[d.key] || []
  const counts = severityOrder.map(s => dimFindings.filter(f => f.severity === s).length)
  return `| ${d.label} | ${counts.join(' | ')} |`
}).join('\n')

const totalRow = `| **Total** | ${severityOrder.map(s => `**${countBySeverity[s]}**`).join(' | ')} |`

const criticalAndHighFindings = verifiedFindings.filter(f => f.severity === 'critical' || f.severity === 'high')

const mustFixSection = criticalAndHighFindings.length > 0
  ? criticalAndHighFindings.map(f => `
### [${f.severity === 'critical' ? '🔴 critical' : '🟠 high'}] ${f.dimension}: ${f.summary}

**File**: \`${f.file}\`
**Why**: ${f.why}
**Fix**: ${f.fix}
`).join('\n')
  : 'No critical or high severity findings. ✅'

const allFindingsSection = DIMENSIONS.map(d => {
  const dimFindings = byDimension[d.key] || []
  if (dimFindings.length === 0) return `### ${d.label}\n\nNo findings. ✅\n`
  return `### ${d.label}\n\n${dimFindings.map(f => `
- **[${f.severity}]** ${f.summary} — \`${f.file}\`\n  ${f.why}
`).join('\n')}`
}).join('\n\n')

const report = `## 🔍 PR Review: #${prNumber}

**Branch**: \`${branch}\` → \`${targetBranch}\`
**Findings**: ${verifiedFindings.length} total
**Effort**: ${effort}
**Reviewed by**: 5 parallel pr-reviewer agents

---

### 📊 Summary

| Dimension | ${severityOrder.map(s => {
  const label = s === 'critical' ? '🔴 Critical' : s === 'high' ? '🟠 High' : s === 'medium' ? '🟡 Medium' : s === 'low' ? '🟢 Low' : '💡 Suggestion'
  return label
}).join(' | ')} |
|-----------|${severityOrder.map(() => ':--:').join('|')}|
${dimensionRows}
${totalRow}

---

### 🚨 Must-Fix Before Merge

${mustFixSection}

---

### 📋 All Findings by Dimension

${allFindingsSection}
`

log(`Report generated: ${verifiedFindings.length} findings`)

return {
  report,
  findings: verifiedFindings,
  summary: {
    total: verifiedFindings.length,
    bySeverity: countBySeverity,
    byDimension: Object.fromEntries(
      DIMENSIONS.map(d => [d.key, (byDimension[d.key] || []).length])
    ),
  },
  prNumber,
  branch,
  targetBranch,
  effort,
}
