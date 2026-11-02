const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");

const publish = require("./publish_quality_scale_report");
const marker = "<!-- ha-quality-scale-report -->";

function createHarness({ comments = [], currentSha = "head-sha" } = {}) {
  const calls = {};
  const github = {
    rest: {
      pulls: {
        get: async (params) => {
          calls.pullRequest = params;
          return { data: { head: { sha: currentSha } } };
        },
      },
      issues: {
        listComments: async () => ({ data: comments }),
        createComment: async (params) => {
          calls.createdComment = params;
        },
        updateComment: async (params) => {
          calls.updatedComment = params;
        },
      },
    },
    paginate: async (_method, params) => {
      calls.listComments = params;
      return comments;
    },
  };
  const context = {
    payload: {
      workflow_run: {
        head_sha: "head-sha",
        html_url: "https://github.com/example/repo/actions/runs/42",
        pull_requests: [{ number: 123 }],
      },
    },
    repo: { owner: "example", repo: "repo" },
  };
  const core = { notice: (message) => (calls.notice = message), warning() {} };
  return { calls, github, context, core };
}

test("publishes quality-scale reports as an up-to-date sticky PR comment", async (t) => {
  const originalCwd = process.cwd();
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "quality-scale-report-"));
  fs.mkdirSync(path.join(tempDir, "quality-scale-reports"));
  fs.writeFileSync(
    path.join(tempDir, "quality-scale-reports", "quality-scale-coverage.json"),
    JSON.stringify({
      bronze: { available: true, covered: 95, total: 95 },
      silver: { available: true, modules: 2, below: 0 },
    }),
  );
  fs.writeFileSync(
    path.join(tempDir, "quality-scale-reports", "quality-scale-strict-typing.json"),
    JSON.stringify({ available: true, passed: true }),
  );
  process.chdir(tempDir);
  t.after(() => {
    process.chdir(originalCwd);
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  await t.test("creates a comment with the report results", async () => {
    const { calls, github, context, core } = createHarness();
    await publish({ github, context, core });

    assert.equal(calls.createdComment.issue_number, 123);
    assert.match(calls.createdComment.body, new RegExp(marker));
    assert.match(calls.createdComment.body, /✅ PASS \(95\/95, 100\.00%\)/);
    assert.match(calls.createdComment.body, /✅ PASS: all 2 modules exceed 95%/);
    assert.match(calls.createdComment.body, /✅ PASS: mypy --strict/);
    assert.equal(calls.updatedComment, undefined);
  });

  await t.test("updates only the existing bot comment", async () => {
    const comments = [
      { id: 1, user: { login: "contributor" }, body: marker },
      { id: 2, user: { login: "github-actions[bot]" }, body: marker },
    ];
    const { calls, github, context, core } = createHarness({ comments });
    await publish({ github, context, core });

    assert.equal(calls.updatedComment.comment_id, 2);
    assert.equal(calls.createdComment, undefined);
  });

  await t.test("skips a report for an outdated PR revision", async () => {
    const { calls, github, context, core } = createHarness({
      currentSha: "newer-sha",
    });
    await publish({ github, context, core });

    assert.match(calls.notice, /outdated pull request revision/);
    assert.equal(calls.listComments, undefined);
    assert.equal(calls.createdComment, undefined);
  });
});
