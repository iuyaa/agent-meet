// Optional browser check. All worker output uses the simulated CLI from test_task.py.
const { chromium } = require('playwright');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const python = process.env.PYTHON || 'python3';
const scripts = path.resolve(__dirname, '../scripts');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-meet-task-browser-'));
const project = path.join(root, 'project');
const room = path.join(project, '.agent-meet', 'demo', 'discussion.sqlite');
const cli = path.join(root, 'fake-claude');
function command(script, action, ...args) {
  return JSON.parse(
    execFileSync(python, [path.join(scripts, script), action, '--room', room, ...args], {
      encoding: 'utf8',
    }),
  );
}
function git(...args) {
  return execFileSync('git', ['-C', project, ...args], { encoding: 'utf8' });
}
let browser;
(async () => {
  fs.mkdirSync(project);
  git('init', '-q');
  git('config', 'user.name', 'Browser Test');
  git('config', 'user.email', 'browser@test.invalid');
  fs.writeFileSync(path.join(project, 'app.py'), 'def answer():\n    return 0\n');
  fs.writeFileSync(path.join(project, '.gitignore'), '__pycache__/\n');
  git('add', '.');
  git('commit', '-qm', 'initial');
  const fake = execFileSync(
    python,
    [
      '-c',
      'import sys; sys.path.insert(0, sys.argv[1]); from test_task import FAKE; print(FAKE)',
      __dirname,
    ],
    { encoding: 'utf8' },
  );
  fs.writeFileSync(cli, fake, { mode: 0o755 });
  fs.writeFileSync(path.join(root, 'control.json'), '{}');
  const specFile = path.join(root, 'task.json');
  fs.writeFileSync(
    specFile,
    JSON.stringify({
      title: '任务演示：修复答案并验收',
      instructions: '让 **answer()** 返回 42，补上回归测试。',
      context: '沿用原主持人的约束与判断。',
      constraints: ['保留原项目改动'],
      acceptance_criteria: ['返回 42', '测试通过'],
    }),
  );
  command(
    'task.py',
    'init',
    '--cwd',
    project,
    '--main',
    'pi',
    '--task-file',
    specFile,
    '--cli',
    cli,
  );
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
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(started.url);
  await page.waitForFunction(() => document.getElementById('phase').textContent === '待执行');
  assert.match(await page.locator('#assessment').innerText(), /返回 42/);
  const first = command('task.py', 'run', '--request-id', 'run-1');
  await page.waitForFunction(
    () => document.getElementById('phase').textContent === '等待主持人验收',
  );
  await page.locator('#expand-all').click();
  assert.equal(await page.locator('.task_result strong').first().innerText(), '实现');
  assert.match(await page.locator('.task_result').innerText(), /尚非主持人验证/);
  assert.match(await page.locator('#outcome').innerText(), /test_app.py/);
  await page.locator('.task_result .message-toggle').click();
  await page.reload();
  await page.waitForSelector('.task_result');
  assert.equal(await page.locator('.task_result .message-body').isVisible(), false);
  const argvFile = path.join(root, 'check.json');
  fs.writeFileSync(argvFile, JSON.stringify([python, '-m', 'unittest', '-v']));
  command('task.py', 'check', '--as', 'pi', '--request-id', 'check-1', '--command-file', argvFile);
  await page.waitForSelector('.task_check');
  await page.locator('#expand-all').click();
  assert.match(await page.locator('.task_check').innerText(), /检查通过/);
  const feedback = path.join(root, 'feedback.txt');
  fs.writeFileSync(feedback, '已检查差异与测试，接受这次实现。');
  command(
    'task.py',
    'review',
    '--as',
    'pi',
    '--request-id',
    'accept-1',
    '--decision',
    'accept',
    '--snapshot',
    first.evidence.snapshot,
    '--text-file',
    feedback,
    '--check-id',
    'check-1',
  );
  await page.waitForFunction(() => document.getElementById('phase').textContent === '验收通过');
  assert.match(await page.locator('#activity').innerText(), /仍在隔离工作副本/);
  assert.match(fs.readFileSync(path.join(project, 'app.py'), 'utf8'), /return 0/);
  command('task.py', 'apply', '--as', 'pi', '--request-id', 'apply-1');
  await page.waitForFunction(
    () => document.getElementById('phase').textContent === '已应用到原项目',
  );
  const downloaded = page.waitForEvent('download');
  await page.locator('#export').click();
  const download = await downloaded;
  const exported = path.join(root, 'export.md');
  await download.saveAs(exported);
  assert.match(fs.readFileSync(exported, 'utf8'), /task_applied/);
  const snapshot = await page.evaluate(async () =>
    (
      await fetch('/api/state', {
        headers: { Authorization: 'Bearer ' + sessionStorage.getItem('agent-chat-token') },
      })
    ).json(),
  );
  assert(!JSON.stringify(snapshot).includes('native_session_id'));
  assert(!JSON.stringify(snapshot).includes('stdout_file'));
  if (process.argv[2])
    await page.screenshot({ path: path.resolve(process.argv[2]), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.deepEqual(errors, []);
  console.log(
    'Task browser checks passed: Markdown, state updates, folding, actual checks, acceptance/application, export, private fields, mobile layout.',
  );
})()
  .finally(async () => {
    try {
      command('view.py', 'close');
    } catch (_) {}
    if (browser) await browser.close();
    fs.rmSync(root, { recursive: true, force: true });
  })
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
