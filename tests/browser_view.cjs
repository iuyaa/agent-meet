// Optional browser checks: npm's playwright package + a local Chromium installation.
// No model calls. All discussion messages below are explicitly scripted demo data.
const { chromium } = require('playwright');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');

const python = process.env.PYTHON || 'python3';
const scripts = path.resolve(__dirname, '../scripts');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-chat-browser-'));
let room = path.join(root, '演示 讨论.sqlite');
function command(script, action, ...args) {
  return JSON.parse(
    execFileSync(python, [path.join(scripts, script), action, '--room', room, ...args], {
      encoding: 'utf8',
    }),
  );
}
function send(agent, id, text) {
  return command('chat.py', 'send', '--as', agent, '--request-id', id, '--text', text);
}
let browser;
(async () => {
  const brief = {
    question: '演示：让两个 Agent 的讨论过程可见',
    goal: '保留原会话背景，让用户看清观点如何形成结论。',
    current_view:
      '我倾向先做一个轻量的本地群聊页面，展示真实消息和讨论结果。主参与者仍是当前 Codex，Claude 负责提出不同意见并审核结论。',
    constraints: ['保留当前 Codex 的长期上下文', '仅在本机运行，不引入额外服务'],
    decisions: ['第一版只讨论一个问题、两个参与者'],
    rejected_options: ['不通过新建主会话接管原 Codex'],
    code_references: ['scripts/chat.py：真实消息与审核记录'],
    unknowns: ['真实模型联调仍需验证'],
  };
  const briefPath = path.join(root, 'briefing.json');
  fs.writeFileSync(briefPath, JSON.stringify(brief));
  // init validates an executable, but does not run it. No Claude installation is needed for this fixture.
  const executable = execFileSync(python, ['-c', 'import sys; print(sys.executable)'], {
    encoding: 'utf8',
  }).trim();
  command('consult.py', 'init', '--cwd', root, '--briefing-file', briefPath, '--cli', executable);
  const started = command('view.py', 'start');
  browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM || '/usr/bin/chromium',
    args: ['--no-sandbox'],
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1080 },
    acceptDownloads: true,
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(started.url);
  await page.waitForSelector('#event-1');
  assert.match(await page.locator('#briefing').innerText(), /保留当前 Codex/);
  assert.equal(await page.locator('#stop').isEnabled(), true);
  send(
    'claude',
    'demo-2',
    '我赞成把讨论过程展示出来。页面需要区分三种状态：正在回复、等待主参与者判断、等待结论审核。\n\n还要显示保留的分歧，避免把“确认记录”误解为所有建议都已验证。',
  );
  await page.waitForSelector('#event-2');
  send(
    'codex',
    'demo-3',
    '同意。页面先提供消息流、上下文简报、结论卡片、停止和导出。\n\n追问仍在这个原会话里发起；我会结合此前的决策继续判断，不让新会话代替当前上下文。',
  );
  send(
    'claude',
    'demo-4',
    '这个范围足够第一版使用。停止操作应取消正在执行的调用；导出时保留完整原话和审核状态。\n\n建议先验证真实记录的实时更新，再考虑页面内发起新问题。',
  );
  await page.waitForSelector('#event-4');
  if (process.argv[2])
    await page.screenshot({ path: path.resolve(process.argv[2]), fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.locator('#event-4 .event-id').click();
  await page.reload(); // An evidence anchor must never replace the stored authentication token.
  await page.waitForSelector('#event-4');
  send('codex', 'xss-check', '<img src=x onerror="window.__injected=1">');
  send('claude', 'xss-reply', '将输入按纯文本展示。');
  await page.waitForSelector('#event-5');
  assert.equal(await page.locator('#event-5 img').count(), 0);
  assert.equal(await page.evaluate(() => window.__injected), undefined);
  const proposal = {
    summary: '第一版本地展示真实讨论，原 Codex 继续保留主参与者身份。',
    agreements: ['展示消息、简报、审核状态', '支持停止与导出'],
    disagreements: [],
    open_questions: ['真实模型和 Windows 实机联调'],
    evidence_message_ids: [1, 2, 3, 4],
  };
  const proposalFile = path.join(root, 'proposal.json');
  fs.writeFileSync(proposalFile, JSON.stringify(proposal));
  const proposed = command(
    'chat.py',
    'propose',
    '--as',
    'codex',
    '--request-id',
    'demo-proposal',
    '--file',
    proposalFile,
  );
  await page.waitForSelector('#event-' + proposed.event.id);
  assert.match(await page.locator('#outcome').innerText(), /尚未确认/);
  command(
    'chat.py',
    'review',
    '--as',
    'claude',
    '--request-id',
    'demo-review',
    '--proposal',
    String(proposed.event.id),
    '--decision',
    'accept',
    '--text',
    '准确记录了双方观点和未验证问题。',
  );
  await page.waitForFunction(() => document.getElementById('phase').textContent === '已确认记录');
  assert.match(await page.locator('.proposal-label').innerText(), /已确认记录/);
  assert.equal(await page.locator('#stop').isDisabled(), true);
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#export').click();
  const download = await downloadPromise;
  const report = fs.readFileSync(await download.path(), 'utf8');
  assert.match(report, /双方已确认/);
  assert.match(report, /真实模型和 Windows/);
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  command('view.py', 'close');
  room = path.join(root, '停止讨论.sqlite');
  command('consult.py', 'init', '--cwd', root, '--briefing-file', briefPath, '--cli', executable);
  const secondRoom = command('view.py', 'start');
  await page.goto(secondRoom.url);
  await page.waitForSelector('#event-1');
  send('claude', 'stop-reply', '本记录仍需审核。');
  fs.writeFileSync(proposalFile, JSON.stringify({ ...proposal, evidence_message_ids: [1, 2] }));
  command(
    'chat.py',
    'propose',
    '--as',
    'codex',
    '--request-id',
    'stop-proposal',
    '--file',
    proposalFile,
  );
  await page.waitForSelector('.proposal-label');
  await page.locator('#stop').click();
  await page.locator('#stop-dialog button[value="cancel"]').click();
  assert.equal(await page.locator('#stop').isEnabled(), true);
  await page.locator('#stop').click();
  await page.locator('#stop-dialog button[value="stop"]').click();
  await page.waitForFunction(() => document.getElementById('phase').textContent === '已停止');
  assert.match(await page.locator('#outcome').innerText(), /尚未确认/);
  assert.match(await page.locator('.proposal-label').innerText(), /尚未确认/);
  command('view.py', 'close');
  await page.waitForFunction(
    () => document.getElementById('connection').textContent === '连接中断',
  );
  assert.equal(await page.locator('#stop').isDisabled(), true);
  assert.deepEqual(errors, []);
  console.log(
    'Browser checks passed: live updates, context, XSS, reload/anchors, review, export, mobile, stop, disconnect. Scripted data only; no model calls.',
  );
})()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    try {
      command('view.py', 'close');
    } catch (_) {}
    if (browser) await browser.close();
    fs.rmSync(root, { recursive: true, force: true });
  });
