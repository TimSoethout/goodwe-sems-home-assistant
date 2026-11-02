const fs = require("node:fs");
const path = require("node:path");

const marker = "<!-- ha-quality-scale-report -->";

function readReport(filename, core) {
  const filePath = path.join("quality-scale-reports", filename);
  if (!fs.existsSync(filePath)) return null;
  if (fs.statSync(filePath).size > 4096) {
    core.warning(`Ignoring oversized report: ${filename}`);
    return null;
  }
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (error) {
    core.warning(`Ignoring invalid report ${filename}: ${error.message}`);
    return null;
  }
}

function isCount(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function coverageResults(report) {
  const bronze = report?.bronze;
  let bronzeResult = "Not available";
  if (
    bronze?.available === true &&
    isCount(bronze.covered) &&
    isCount(bronze.total) &&
    bronze.covered <= bronze.total
  ) {
    if (bronze.total === 0) {
      bronzeResult = "No executable lines measured";
    } else {
      const percent = ((bronze.covered / bronze.total) * 100).toFixed(2);
      bronzeResult =
        `${bronze.covered === bronze.total ? "✅ PASS" : "Below 100%"} ` +
        `(${bronze.covered}/${bronze.total}, ${percent}%)`;
    }
  }

  const silver = report?.silver;
  let silverResult = "Not available";
  if (
    silver?.available === true &&
    isCount(silver.modules) &&
    isCount(silver.below) &&
    silver.below <= silver.modules
  ) {
    silverResult =
      silver.modules === 0
        ? "No modules measured"
        : silver.below === 0
          ? `✅ PASS: all ${silver.modules} modules exceed 95%`
          : `${silver.below}/${silver.modules} modules do not exceed 95%`;
  }
  return { bronzeResult, silverResult };
}

function buildComment(run, coverage, strictTyping) {
  const { bronzeResult, silverResult } = coverageResults(coverage);
  const platinumResult =
    strictTyping?.available === true && typeof strictTyping.passed === "boolean"
      ? strictTyping.passed
        ? "✅ PASS: mypy --strict"
        : "Issues reported by mypy --strict"
      : "Not available";

  return [
    marker,
    "## Home Assistant quality-scale advisory checks",
    "",
    "| Tier | Result |",
    "| --- | --- |",
    `| Bronze | Config-flow line coverage: ${bronzeResult}. Flow scenario coverage still needs review. |`,
    `| Silver | Per-module test coverage: ${silverResult}. |`,
    "| Gold | Requires human review; no automated tier verdict is claimed. |",
    `| Platinum | Strict typing: ${platinumResult}. |`,
    "",
    `These checks are advisory and do not fail CI. See the [workflow run](${run.html_url}) for detailed warnings and diagnostics.`,
    "",
    "_AI/Copilot-generated CI summary._",
  ].join("\n");
}

module.exports = async function publishQualityScaleReport({ github, context, core }) {
  const run = context.payload.workflow_run;
  const pullRequest = run.pull_requests?.[0];
  if (!pullRequest) return;

  const { owner, repo } = context.repo;
  const { data: currentPullRequest } = await github.rest.pulls.get({
    owner,
    repo,
    pull_number: pullRequest.number,
  });
  if (currentPullRequest.head.sha !== run.head_sha) {
    core.notice("Skipping a report for an outdated pull request revision.");
    return;
  }

  const body = buildComment(
    run,
    readReport("quality-scale-coverage.json", core),
    readReport("quality-scale-strict-typing.json", core),
  );
  const comments = await github.paginate(github.rest.issues.listComments, {
    owner,
    repo,
    issue_number: pullRequest.number,
    per_page: 100,
  });
  const existing = comments.find(
    (comment) =>
      comment.user?.login === "github-actions[bot]" &&
      comment.body?.includes(marker),
  );

  if (existing) {
    await github.rest.issues.updateComment({
      owner,
      repo,
      comment_id: existing.id,
      body,
    });
  } else {
    await github.rest.issues.createComment({
      owner,
      repo,
      issue_number: pullRequest.number,
      body,
    });
  }
};
