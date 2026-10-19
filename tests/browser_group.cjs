// Local UI integration using five fake CLI processes; no model calls.
const { chromium } = require('playwright');
const { execFileSync, execFile } = require('node:child_process');
const { promisify } = require('node:util');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const run = promisify(execFile);
const python = process.env.PYTHON || 'python3';
const scripts = path.resolve(__dirname, '../scripts');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-chat-group-ui-'));
const room = path.join(root, '五角色.sqlite');
function args(script, action, rest) {
  return [path.join(scripts, script), action, '--room', room, ...rest];
}
function command(script, action, ...rest) {
  return JSON.parse(execFileSync(python, args(script, action, rest), { encoding: 'utf8' }));
}
async function round(id, ...rest) {
  return JSON.parse(
    (
      await run(python, args('group.py', 'round', ['--request-id', id, ...rest]), {
        encoding: 'utf8',
      })
    ).stdout,
  );
}
let browser;
(async () => {
  const cli = path.join(root, 'fake claude');
  execFileSync(python, [
    '-c',
    'import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from test_group import FAKE_ROLE;p=Path(sys.argv[2]);p.write_text(FAKE_ROLE.replace("time.sleep(1)","time.sleep(2)"));p.chmod(0o755)',
    __dirname,
    cli,
  ]);
  const roles = JSON.parse(fs.readFileSync(path.join(scripts, '../examples/roles.json'), 'utf8'));
  roles.forEach((role) => {
    role.cli = cli;
    fs.writeFileSync(path.join(root, 'mode-' + role.id + '.txt'), 'slow');
  });
  const roleFile = path.join(root, 'roles.json');
  fs.writeFileSync(roleFile, JSON.stringify(roles));
  const brief = {
    question: '演示：五个角色评审 Agent 协作方案',
    goal: '从产品、技术、使用体验和业务目标评估第一版范围。',
    current_view: '保留原 Codex 长期上下文，邀请五个独立角色交叉评审，讨论最多 **2 轮**。',
    constraints: ['本次仅讨论，不修改业务代码'],
    decisions: ['当前 Codex 担任主持人'],
    rejected_options: [],
    code_references: [],
    unknowns: ['用户角色为模拟视角，真实用户反馈待验证'],
  };
  const briefFile = path.join(root, 'brief.json');
  fs.writeFileSync(briefFile, JSON.stringify(brief));
  command(
    'group.py',
    'init',
    '--cwd',
    root,
    '--briefing-file',
    briefFile,
    '--roles-file',
    roleFile,
    '--rounds',
    '2',
  );
  const started = command('view.py', 'start');
  browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM || '/usr/bin/chromium',
    args: ['--no-sandbox'],
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1080 },
    acceptDownloads: true,
  });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(started.url);
  await page.waitForSelector('#event-1');
  assert.match(await page.locator('#participant-count').innerText(), /06 PARTICIPANTS/);
  assert.equal(await page.locator('.role-card').count(), 6);
  for (const role of roles)
    assert.match(await page.locator('#roles-list').innerText(), new RegExp(role.title));
  const pending = round('first');
  await page.waitForFunction(() =>
    document.getElementById('roles-list').textContent.includes('回复中'),
  );
  assert.equal((await pending).status.completed_rounds, 1);
  await page.waitForSelector('#event-6');
  assert.equal(await page.locator('.message').count(), 6);
  assert.match(await page.locator('#event-2 .role').innerText(), /Claude/);
  await page.locator('#collapse-all').click();
  assert.equal(await page.locator('#event-2 .message-body').isVisible(), false);
  command(
    'chat.py',
    'send',
    '--as',
    'codex',
    '--request-id',
    'host-second',
    '--text',
    '## 第二轮\n请回应其他角色的不同意见，并说明哪些问题还缺少证据。',
  );
  const second = await round('second');
  assert.equal(second.status.completed_rounds, 2);
  await page.waitForSelector('#event-12');
  assert.equal(await page.locator('.round-divider').count(), 2);
  assert.match(await page.locator('#round-progress').innerText(), /2 \/ 2 轮/);
  assert.equal(await page.locator('#event-2 .message-body').isVisible(), false);
  await page.locator('#expand-all').click();
  if (process.argv[2])
    await page.screenshot({ path: path.resolve(process.argv[2]), fullPage: true });
  const proposal = {
    summary: '保留原主持人上下文，采用 **独立角色 + 有限轮次** 的讨论方式。',
    agreements: ['公开展示各角色的实际发言', '结论需要全体角色审核'],
    disagreements: ['允许保留尚未解决的不同判断'],
    open_questions: ['真实用户反馈和真实模型联调'],
    evidence_message_ids: Array.from({ length: 12 }, (_, i) => i + 1),
  };
  const proposalFile = path.join(root, 'proposal.json');
  fs.writeFileSync(proposalFile, JSON.stringify(proposal));
  command(
    'chat.py',
    'propose',
    '--as',
    'codex',
    '--request-id',
    'proposal-one',
    '--file',
    proposalFile,
  );
  await round('review-one', '--only', roles[0].id);
  await page.waitForFunction(() =>
    document.getElementById('outcome').textContent.includes('已审核 1 / 5'),
  );
  assert.match(await page.locator('#outcome').innerText(), /等待全体审核/);
  fs.writeFileSync(path.join(root, 'mode-' + roles[4].id + '.txt'), 'reject');
  const disputed = await round('review-rest');
  assert.equal(disputed.status.conclusion_status, 'disputed');
  await page.waitForFunction(() =>
    document.getElementById('outcome').textContent.includes('有角色异议'),
  );
  assert.notEqual(await page.locator('#phase').innerText(), '已确认记录');
  fs.writeFileSync(path.join(root, 'mode-' + roles[4].id + '.txt'), 'ok');
  command(
    'chat.py',
    'propose',
    '--as',
    'codex',
    '--request-id',
    'proposal-two',
    '--file',
    proposalFile,
  );
  const confirmed = await round('review-revision');
  assert.equal(confirmed.status.conclusion_status, 'confirmed');
  await page.waitForFunction(() =>
    document.getElementById('outcome').textContent.includes('全体角色已确认'),
  );
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#export').click();
  const download = await downloadPromise;
  const report = fs.readFileSync(await download.path(), 'utf8');
  assert.match(report, /全部角色已确认记录/);
  assert.match(report, /轮次：2 \/ 2 轮完成/);
  roles.forEach((role) => assert.ok(report.includes(role.title)));
  const response = await page.evaluate(async () =>
    (
      await fetch('/api/state', {
        headers: { Authorization: 'Bearer ' + sessionStorage.getItem('agent-chat-token') },
      })
    ).json(),
  );
  assert.ok(!JSON.stringify(response).includes('native_session_id'));
  assert.ok(!JSON.stringify(response).includes(cli));
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.deepEqual(errors, []);
  console.log(
    'Group browser checks passed: five-role progress, parallel calls, rounds, fold persistence, partial/rejected/all reviews, export, privacy and mobile. Fake CLIs only.',
  );
})()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    try {
      command('chat.py', 'stop', '--reason', 'test cleanup');
      command('view.py', 'close');
    } catch (_) {}
    if (browser) await browser.close();
    fs.rmSync(root, { recursive: true, force: true });
  });
