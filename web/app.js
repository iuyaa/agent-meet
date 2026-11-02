'use strict';
function engineName(backend) {
  return { codex: 'Codex', claude: 'Claude', pi: 'pi', opencode: 'OpenCode' }[backend] || backend;
}

const $ = (id) => document.getElementById(id);
const fragment = location.hash.slice(1);
if (/^[A-Za-z0-9_-]{40,}$/.test(fragment)) {
  sessionStorage.setItem('agent-chat-token', fragment);
  history.replaceState(null, '', location.pathname);
}
const token = sessionStorage.getItem('agent-chat-token') || '';
let lastEvents = '',
  lastBriefing = '',
  lastOutcome = '',
  lastRoster = '',
  lastAssessment = '',
  stopped = false;
let foldState;
try {
  foldState = JSON.parse(sessionStorage.getItem('agent-chat-folds'));
} catch (_) {}
if (!foldState || typeof foldState !== 'object') foldState = {};
foldState.events ||= {};
foldState.details ||= {};
function saveFolds() {
  try {
    sessionStorage.setItem('agent-chat-folds', JSON.stringify(foldState));
  } catch (_) {}
}
function foldMessage(article, collapsed) {
  article.querySelector('.message-body').hidden = collapsed;
  article.querySelector('.message-preview').hidden = !collapsed;
  const button = article.querySelector('.message-toggle');
  button.textContent = collapsed ? '展开' : '折叠';
  button.setAttribute('aria-expanded', String(!collapsed));
  article.classList.toggle('collapsed', collapsed);
}
function node(tag, text, cls) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
}
function escapeHTML(text) {
  return text.replace(
    /[&<>"']/g,
    (char) =>
      ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      })[char],
  );
}
const markdownParser = new marked.Marked({
  gfm: true,
  breaks: true,
  renderer: {
    // Raw HTML remains visible text. Images become links, avoiding automatic remote requests.
    html: ({ text }) => escapeHTML(text),
    image: ({ href, text }) =>
      `<a href="${escapeHTML(href)}">图片：${escapeHTML(text || '查看图片')}</a>`,
    checkbox: ({ checked }) => (checked ? '☑ ' : '☐ '),
  },
});
function markdown(text, cls = '') {
  const el = node('div', undefined, 'markdown ' + cls);
  try {
    const fragment = DOMPurify.sanitize(markdownParser.parse(String(text)), {
      ALLOWED_TAGS: [
        'p',
        'br',
        'hr',
        'h1',
        'h2',
        'h3',
        'h4',
        'h5',
        'h6',
        'strong',
        'em',
        'del',
        'code',
        'pre',
        'blockquote',
        'ul',
        'ol',
        'li',
        'a',
        'table',
        'thead',
        'tbody',
        'tr',
        'th',
        'td',
      ],
      ALLOWED_ATTR: ['href', 'title', 'class', 'start', 'align'],
      ALLOW_DATA_ATTR: false,
      ALLOW_ARIA_ATTR: false,
      RETURN_DOM_FRAGMENT: true,
    });
    el.append(fragment);
    for (const link of el.querySelectorAll('a')) {
      const href = link.getAttribute('href') || '';
      if (/^#event-\d+$/.test(href)) continue;
      let protocol;
      try {
        protocol = new URL(href).protocol;
      } catch (_) {
        /* Not an absolute URL. */
      }
      if (!['https:', 'http:', 'mailto:'].includes(protocol)) {
        link.removeAttribute('href');
      } else {
        link.setAttribute('rel', 'noopener noreferrer');
        link.setAttribute('target', '_blank');
      }
    }
    for (const table of el.querySelectorAll('table')) {
      const scroll = node('div', undefined, 'table-scroll');
      scroll.tabIndex = 0;
      scroll.setAttribute('role', 'region');
      scroll.setAttribute('aria-label', '表格，可横向滚动');
      table.replaceWith(scroll);
      scroll.append(table);
    }
  } catch (_) {
    // Rendering failures must not hide an agent's message or interrupt the discussion.
    el.textContent = String(text);
    el.classList.add('plain-fallback');
  }
  return el;
}
async function api(path, method = 'GET') {
  const response = await fetch(path, {
    method,
    headers: { Authorization: 'Bearer ' + token },
    cache: 'no-store',
  });
  if (!response.ok) {
    if (response.status === 401) throw new Error('请使用启动命令返回的完整本地链接打开页面。');
    const error = await response.json();
    throw new Error(error.error || '无法读取讨论记录');
  }
  return response;
}
function list(parent, title, items) {
  parent.append(node('h3', title));
  if (!items || !items.length) {
    parent.append(node('p', '未提供', 'muted'));
    return;
  }
  const ul = node('ul');
  items.forEach((item) => {
    const li = node('li');
    li.append(markdown(item));
    ul.append(li);
  });
  parent.append(ul);
}
function conclusion(body) {
  const el = node('div', undefined, 'structured');
  el.append(markdown(body.summary, 'summary'));
  list(el, '共识', body.agreements);
  list(el, '保留分歧', body.disagreements);
  list(el, '待验证', body.open_questions);
  const refs = node('div', '依据消息', 'evidence');
  body.evidence_message_ids.forEach((id) => {
    const a = node('a', '#' + id);
    a.href = '#event-' + id;
    refs.append(a);
  });
  el.append(refs);
  return el;
}
function reviewResolutions(body) {
  const el = node('div', undefined, 'review-resolutions');
  const labels = {
    incorporated: '已采纳',
    already_covered: '原文已覆盖',
    not_adopted: '未采纳',
    follow_up: '后续验证',
  };
  el.append(node('h3', '最后审核意见处理'));
  for (const item of body.resolutions) {
    el.append(
      node('h4', '#' + item.review_id + ' · ' + labels[item.disposition]),
      markdown(item.point),
      markdown(item.resolution),
    );
  }
  if (body.change_type === 'clarification')
    el.append(node('p', '基于已审核草案补充说明；主持人整理后的措辞未再次送审。', 'muted'));
  return el;
}
function assessmentView(value) {
  const el = node('div', undefined, 'structured');
  el.append(
    node(
      'span',
      value.decision === 'conclude' ? '可以总结' : '建议继续讨论',
      'outcome-status ' + (value.decision === 'conclude' ? '' : 'unconfirmed'),
    ),
    markdown(value.reason),
  );
  for (const [key, title] of [
    ['blocking_questions', '关键缺口'],
    ['accepted_uncertainties', '明确保留的不确定性'],
    ['next_steps', '下一步'],
  ]) {
    if (value[key].length) list(el, title, value[key]);
  }
  return el;
}
function message(event, data) {
  const role = data.roles?.find((role) => role.id === event.sender);
  const reviewer = role ? event.sender !== data.main : event.sender === data.reviewer;
  const el = node('article', undefined, 'message ' + (reviewer ? 'reviewer ' : '') + event.kind);
  el.id = 'event-' + event.id;
  el.append(
    node('div', role ? role.title.charAt(0) : event.sender.charAt(0).toUpperCase(), 'avatar'),
  );
  const content = node('div');
  const meta = node('div', undefined, 'message-meta');
  const isTask = data.status.mode === 'task';
  const name = isTask && reviewer ? 'Claude' : role ? role.title : engineName(event.sender);
  meta.append(
    node('span', name, 'sender'),
    node(
      'span',
      isTask
        ? reviewer
          ? '任务执行者'
          : '原会话主持'
        : role
          ? role.backend === 'existing'
            ? '当前会话'
            : engineName(role.backend)
          : reviewer
            ? '讨论伙伴'
            : '主参与者',
      'role',
    ),
  );
  if (event.round_index) meta.append(node('span', '第 ' + event.round_index + ' 轮', 'round-tag'));
  const time = node(
    'time',
    new Date(event.created).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    }),
    'time',
  );
  time.dateTime = event.created;
  time.title = new Date(event.created).toLocaleString();
  const id = node('a', '#' + event.id, 'event-id');
  id.href = '#event-' + event.id;
  meta.append(time, id);
  content.append(meta);
  const bubble = node('div', undefined, 'bubble');
  const body = node('div', undefined, 'message-body');
  body.id = 'body-' + event.id;
  if (event.kind.startsWith('task_')) {
    body.append(taskEvent(event));
  } else if (event.kind === 'finalization') {
    const historical = data.status.latest_finalization?.id !== event.id;
    body.append(
      node('div', historical ? '历史最终结论' : '最终结论 · 已处理最后审核意见', 'proposal-label'),
      conclusion(event.body.conclusion),
      reviewResolutions(event.body),
    );
  } else if (event.kind === 'assessment') {
    body.append(
      node('div', '主持人结束前评估', 'decision-label'),
      assessmentView(event.body.assessment),
    );
  } else if (event.kind === 'extension') {
    body.append(
      node('span', '已追加讨论 · 第 ' + event.body.epoch + ' 次续聊', 'decision-label'),
      node(
        'p',
        '追加 ' + event.body.added_rounds + ' 轮 · 延长 ' + event.body.added_minutes + ' 分钟',
      ),
      markdown(event.body.reason),
    );
    if (event.body.previous_proposal_id)
      body.append(
        node(
          'p',
          '旧草案 #' + event.body.previous_proposal_id + ' 及审核保留为历史，本次继续后重新评估。',
          'muted',
        ),
      );
  } else if (event.kind === 'proposal') {
    const reviews = data.events.filter(
      (item) => item.kind === 'review' && item.reply_to === event.id,
    );
    const review = reviews[0];
    const label =
      data.status.mode === 'group'
        ? reviews.some((r) => r.body.decision === 'reject')
          ? '有角色提出异议'
          : reviews.length === data.roles.length - 1
            ? '全体已确认记录'
            : '审核 ' + reviews.length + ' / ' + (data.roles.length - 1)
        : review
          ? review.body.decision === 'accept'
            ? '已确认记录'
            : '对方提出异议'
          : data.status.phase === 'closed'
            ? '尚未确认'
            : '等待对方审核';
    const historical = data.status.latest_extension && event.id < data.status.latest_extension.id;
    body.append(
      node(
        'span',
        historical
          ? '历史草案 · 已进入追加讨论'
          : '结论草案 · ' +
              (data.status.finalization_required &&
              data.status.latest_proposal?.id === event.id &&
              data.status.finalization_status === 'pending'
                ? '已审核，待主持人处理最后意见'
                : label),
        'proposal-label',
      ),
      conclusion(event.body),
    );
  } else if (event.kind === 'review') {
    const accepted = event.body.decision === 'accept';
    body.append(
      node(
        'span',
        accepted ? '✓ 已确认记录准确' : '提出异议 · 需要修订',
        'review-label ' + (accepted ? '' : 'rejected'),
      ),
      markdown(event.body.comment),
    );
  } else if (data.briefing && event.request_id === 'consult-opening') {
    body.append(
      node('div', '带入本次讨论的上下文', 'opening-label'),
      markdown(data.briefing.current_view, 'opening-view'),
    );
    const details = node('details');
    details.append(node('summary', '查看完整开场简报'), markdown(event.body, 'full-brief'));
    body.append(details);
  } else {
    body.append(markdown(event.body));
  }
  const preview = node(
    'div',
    body.textContent.trim().slice(0, 180) + (body.textContent.length > 180 ? '…' : ''),
    'message-preview',
  );
  const toggle = node('button', '折叠', 'message-toggle');
  toggle.setAttribute('aria-controls', body.id);
  toggle.addEventListener('click', () => {
    const collapsed = !body.hidden;
    foldState.events[event.id] = collapsed;
    foldMessage(el, collapsed);
    saveFolds();
  });
  meta.insertBefore(toggle, time);
  for (const [index, details] of [...body.querySelectorAll('details')].entries()) {
    const key = event.id + ':' + index;
    details.open = Boolean(foldState.details[key]);
    details.addEventListener('toggle', () => {
      foldState.details[key] = details.open;
      saveFolds();
    });
  }
  bubble.append(preview, body);
  content.append(bubble);
  el.append(content);
  const long =
    JSON.stringify(event.body).length > 1200 || String(event.body).split('\n').length > 18;
  foldMessage(
    el,
    foldState.events[event.id] ?? (foldState.mode ? foldState.mode === 'collapsed' : long),
  );
  return el;
}
function taskEvent(event) {
  const b = event.body;
  const el = node('div', undefined, 'structured');
  const labels = {
    created: '任务要求',
    started: '开始执行',
    result: 'Claude 提交结果',
    check: '主持人检查',
    review: '主持人验收',
    applied: '已应用到原项目',
    failed: '调用未完成',
    extended: '追加任务预算',
  };
  el.append(node('div', labels[event.kind.slice(5)] || event.kind, 'proposal-label'));
  if (event.kind === 'task_created') {
    el.append(markdown(b.spec.instructions), markdown(b.spec.context));
    list(el, '约束', b.spec.constraints);
    list(el, '验收标准', b.spec.acceptance_criteria);
  } else if (event.kind === 'task_result') {
    el.append(markdown(b.worker_report.summary));
    list(el, 'Claude 报告的检查（尚非主持人验证）', b.worker_report.tests);
    list(el, '剩余问题', b.worker_report.remaining_issues);
    list(el, 'Git 记录的改动文件', b.git.changed_files);
    el.append(markdown('```text\n' + b.git.stat + '\n```'));
  } else if (event.kind === 'task_check') {
    el.append(
      node('strong', b.passed ? '检查通过' : '检查未通过'),
      node('p', '退出码：' + b.exit_code),
      node('code', JSON.stringify(b.argv)),
    );
    if (b.error) el.append(markdown(b.error));
    const log = node('details');
    log.append(node('summary', '查看检查输出'), node('pre', b.stdout + '\n' + b.stderr));
    if (b.stdout_truncated || b.stderr_truncated)
      log.append(node('p', '输出已截断，完整日志由原主持人在本地查看。', 'muted'));
    el.append(log);
    if (b.snapshot !== b.after_snapshot)
      el.append(node('p', '检查修改了文件，需重新检查当前快照。'));
  } else if (event.kind === 'task_review') {
    el.append(
      node(
        'strong',
        b.decision === 'accept' ? '验收通过 · 等待应用' : '要求返工 · 恢复原 Claude 会话',
      ),
      markdown(b.comment),
    );
    if (b.no_check_reason) el.append(markdown('未运行检查的理由：' + b.no_check_reason));
  } else if (event.kind === 'task_started') {
    el.append(node('p', '第 ' + b.attempt + ' 次执行'));
    if (b.feedback) el.append(markdown(b.feedback.comment));
  } else if (event.kind === 'task_failed') {
    el.append(markdown(b.summary), markdown(b.reason));
  } else if (event.kind === 'task_extended') {
    el.append(
      node('p', '追加 ' + b.attempts + ' 次执行，' + b.minutes + ' 分钟'),
      markdown(b.reason),
    );
  } else if (event.kind === 'task_applied') {
    el.append(markdown(b.note));
    list(el, '已应用文件', b.changed_files);
  }
  return el;
}

function renderTask(data) {
  const s = data.status;
  stopped = s.phase === 'closed';
  const labels = {
    ready: '待执行',
    running: 'Claude 执行中',
    ready_for_review: '等待主持人验收',
    blocked: '需要主持人处理',
    failed: '执行未完成',
    changes_requested: '待原会话返工',
    accepted: '验收通过',
  };
  const label = s.applied
    ? '已应用到原项目'
    : s.close_reason === 'expired'
      ? '时间已到'
      : s.close_reason?.startsWith('stopped:')
        ? '已停止'
        : labels[s.task_state] || s.task_state;
  $('topic').textContent = s.topic;
  document.title = s.topic + ' · Agent-Meet 任务';
  document.querySelector('.local').textContent = '本地任务';
  document.querySelector('.eyebrow').firstChild.textContent = 'TASK ROOM ';
  $('participants').textContent = s.main + ' 主持 / Claude 执行';
  $('participant-count').textContent = '／ TASK WORKTREE';
  $('count').textContent = s.attempts + ' / ' + s.max_attempts + ' 次执行';
  $('round-progress').textContent = '时间上限：' + new Date(s.expires_at).toLocaleString();
  $('phase').textContent = label;
  $('phase').classList.toggle('closed', stopped);
  $('activity').textContent =
    label + (s.task_state === 'accepted' && !s.applied ? ' · 改动仍在隔离工作副本' : '');
  $('activity').classList.toggle('busy', !stopped && s.task_state === 'running');
  $('notice').hidden = true;
  $('stop').textContent = '停止任务';
  $('stop').disabled = stopped;
  $('export').disabled = false;
  document.querySelector('#stop-dialog h2').textContent = '停止这次任务？';
  document.querySelector('#stop-dialog p').textContent =
    '取消正在执行的调用或检查；保留工作副本、原生会话和已有记录。';
  document.querySelector('#stop-dialog button[value="cancel"]').textContent = '继续任务';
  document.querySelector('#stop-dialog button[value="stop"]').textContent = '停止任务';
  document.querySelector('.compose-hint div').textContent =
    '在发起任务的原会话中审查、要求返工和应用结果。';
  document.querySelector('.sidebar-note').textContent =
    'Claude 的完成说明与主持人实际检查分别记录。验收通过后仍需应用到原项目。';
  document.querySelector('#assessment-panel h2').textContent = '验收标准';
  document.querySelector('.conclusion-panel h2').textContent = '任务结果';
  const signature = JSON.stringify([s, data.events]);
  if (signature === lastEvents) return;
  const nearBottom =
    window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 180;
  const initial = !lastEvents;
  $('messages').replaceChildren(...data.events.map((event) => message(event, data)));
  $('briefing').replaceChildren(markdown(s.spec.instructions), markdown(s.spec.context));
  list($('briefing'), '约束', s.spec.constraints);
  $('assessment').replaceChildren();
  list($('assessment'), '主持人按这些要求检查实际改动', s.spec.acceptance_criteria);
  const out = $('outcome');
  out.replaceChildren(node('strong', label));
  if (s.last_result) out.append(markdown(s.last_result.summary));
  list(out, 'Git 记录的改动文件', s.changed_files);
  out.append(node('p', '已记录 ' + s.checks.length + ' 次主持人检查'));
  if (s.snapshot) out.append(node('p', '快照：' + s.snapshot.slice(0, 12), 'muted'));
  lastEvents = signature;
  if (!initial && nearBottom) $('activity').scrollIntoView({ block: 'nearest' });
}

function render(data) {
  if (data.status.mode === 'task') return renderTask(data);
  const s = data.status,
    model = data.model,
    worker = data.worker;
  stopped = s.phase === 'closed';
  const isGroup = s.mode === 'group';
  const display = (id) => data.roles?.find((role) => role.id === id)?.title || id;
  const active = Object.entries(data.workers || {}).filter(([, w]) =>
    ['thinking', 'calling', 'response_ready'].includes(w.state),
  );
  const failed = Object.entries(data.workers || {}).filter(([, w]) => w.state === 'failed');
  $('topic').textContent = s.topic;
  document.title = s.topic + ' · Meet';
  $('participants').textContent = s.participants.map(display).join('  +  ');
  $('participant-count').textContent =
    '／ ' + String(s.participants.length).padStart(2, '0') + ' PARTICIPANTS';
  $('round-progress').textContent = isGroup
    ? '第 ' + s.current_round + ' / ' + s.max_rounds + ' 轮 · ' + s.completed_rounds + ' 轮已完成'
    : '长消息可折叠查看';
  $('count').textContent = s.message_count + ' / ' + s.max_messages + ' 条发言';
  let activity;
  if (s.continuation_needs_approval) {
    activity = '主持人建议继续 · 等待用户决定是否追加讨论';
  } else if (s.phase === 'finalizing') {
    activity = '草案已审核 · 等待主持人处理最后意见并保存最终结论';
  } else if (stopped) {
    activity =
      s.close_reason === 'agreement'
        ? isGroup
          ? '讨论结束 · 全体角色已确认记录'
          : '讨论结束 · 双方已确认记录'
        : s.close_reason === 'expired'
          ? '讨论期限已到 · 未确认的草案仍保留原状态'
          : '讨论已停止 · 已有记录已保留';
  } else if (isGroup) {
    activity = active.length
      ? active.map(([id]) => display(id)).join('、') + ' 正在回复…'
      : failed.length
        ? failed.map(([id]) => display(id)).join('、') + ' 调用失败 · 请在原会话处理'
        : s.pending_reviewers.length
          ? '等待审核：' + s.pending_reviewers.map(display).join('、')
          : s.phase === 'summarizing'
            ? '轮次或讨论时间已到 · 等待主持人评估是否结束'
            : s.pending_speakers.length
              ? '等待发言：' + s.pending_speakers.map(display).join('、')
              : '本轮已完成 · 等待原主持人追问或总结';
  } else if (model.state === 'failed' || worker.state === 'failed') {
    activity = '本轮调用失败 · 请在原会话检查后处理';
  } else if (model.state === 'calling' || worker.state === 'thinking') {
    activity = data.reviewer + ' 正在回复…';
  } else if (s.latest_proposal && !s.latest_review) {
    activity = '等待结论审核';
  } else if (s.phase === 'summarizing') {
    activity = '预算已用完 · 等待主持人评估结束或申请继续';
  } else {
    activity = '等待 ' + s.next_speaker + ' 发言';
  }
  $('activity').textContent = activity;
  $('activity').classList.toggle(
    'busy',
    !stopped && (active.length > 0 || model.state === 'calling' || worker.state === 'thinking'),
  );
  $('phase').textContent =
    s.phase === 'finalizing'
      ? '待整理最终结论'
      : stopped
        ? s.close_reason === 'agreement'
          ? '已确认记录'
          : s.close_reason === 'expired'
            ? '已超时'
            : '已停止'
        : s.phase === 'summarizing'
          ? '总结中'
          : '讨论中';
  $('phase').classList.toggle('closed', stopped);
  const error =
    !stopped &&
    (isGroup
      ? failed.map(([id, w]) => display(id) + '：' + (w.detail || '调用失败')).join('\n')
      : model.state === 'failed'
        ? model.detail
        : worker.state === 'failed'
          ? worker.detail
          : null);
  $('notice').hidden = !error;
  $('notice').textContent = error || '';
  $('stop').disabled = stopped;
  $('export').disabled = false;
  const assessmentSig = JSON.stringify([
    s.latest_assessment,
    s.assessment_fresh,
    s.epoch,
    s.phase,
    s.continuation_needs_approval,
  ]);
  if (assessmentSig !== lastAssessment) {
    const area = $('assessment');
    area.replaceChildren();
    if (s.latest_assessment) {
      area.append(assessmentView(s.latest_assessment.body.assessment));
      if (s.continuation_needs_approval)
        area.append(
          node('p', '请在发起讨论的原会话确认追加轮次或时间；确认后恢复原角色会话。', 'muted'),
        );
      else if (!s.assessment_fresh && !stopped)
        area.append(node('p', '有新发言或审核，下一份草稿前需重新评估。', 'muted'));
    } else
      area.append(
        node(
          'p',
          s.epoch
            ? '已继续原讨论；本轮结束后重新评估。'
            : '结论草稿前先判断是否已讨论充分，或仍有关键缺口。',
          'muted',
        ),
      );
    lastAssessment = assessmentSig;
  }
  const sig = JSON.stringify([data.events, s.phase]);
  if (sig !== lastEvents) {
    const nearBottom =
      window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 180;
    const initial = !lastEvents;
    const elements = [];
    let round = 0;
    for (const event of data.events) {
      if (isGroup && event.round_index !== round) {
        round = event.round_index;
        elements.push(node('div', '第 ' + round + ' 轮', 'round-divider'));
      }
      elements.push(message(event, data));
    }
    $('messages').replaceChildren(...elements);
    if (!data.events.length)
      $('messages').append(node('p', '讨论室已就绪，等待第一条发言。', 'empty'));
    lastEvents = sig;
    // Follow new messages only when the reader was already near the latest message.
    if (!initial && nearBottom) $('activity').scrollIntoView({ block: 'nearest' });
  }
  const briefSig = JSON.stringify(data.briefing);
  if (briefSig !== lastBriefing) {
    $('briefing').replaceChildren();
    if (data.briefing) {
      const b = data.briefing;
      $('briefing').append(node('h3', '讨论目标'), markdown(b.goal));
      list($('briefing'), '约束', b.constraints);
      list($('briefing'), '已有决策', b.decisions);
      const more = node('details');
      more.append(node('summary', '否决方案、依据与未知信息'));
      list(more, '已否决方案', b.rejected_options);
      list(more, '代码与证据', b.code_references);
      list(more, '未知信息', b.unknowns);
      $('briefing').append(more);
    } else {
      $('briefing').append(node('p', '此讨论没有保存结构化简报；请阅读开场消息。', 'muted'));
    }
    lastBriefing = briefSig;
  }
  const outcomeSig = JSON.stringify([
    s.latest_proposal,
    s.reviews,
    s.latest_review,
    s.latest_finalization,
    s.phase,
  ]);
  if (outcomeSig !== lastOutcome) {
    const out = $('outcome');
    out.replaceChildren();
    if (s.latest_proposal) {
      const labels = {
        unconfirmed: '草案 · 尚未确认',
        confirmed: '双方已确认记录',
        disputed: '有异议 · 尚未确认',
      };
      if (isGroup)
        Object.assign(labels, {
          unconfirmed: '草案 · 等待全体审核',
          confirmed: '全体角色已确认记录',
          disputed: '有角色异议 · 尚未全体确认',
        });
      out.append(
        node(
          'div',
          s.latest_finalization
            ? '最终结论 · 已处理最后审核意见'
            : s.finalization_status === 'pending'
              ? '草案已审核 · 等待主持人整理'
              : labels[s.conclusion_status],
          'outcome-status ' + s.conclusion_status,
        ),
        conclusion(
          s.latest_finalization ? s.latest_finalization.body.conclusion : s.latest_proposal.body,
        ),
      );
      if (s.latest_finalization) out.append(reviewResolutions(s.latest_finalization.body));
      if (isGroup)
        out.prepend(
          node(
            'p',
            '已审核 ' + s.reviews.length + ' / ' + (data.roles.length - 1),
            'review-progress',
          ),
        );
    } else {
      out.append(
        node(
          'p',
          s.epoch
            ? '追加讨论进行中；旧结论及审核保留在消息历史中。'
            : stopped
              ? '讨论结束，尚无结论草案。'
              : '结论形成后，共识、分歧与待验证问题会出现在这里。',
          'muted',
        ),
      );
    }
    lastOutcome = outcomeSig;
  }
  const rosterSig = JSON.stringify([
    data.roles,
    data.workers,
    s.current_round,
    s.phase,
    s.pending_speakers,
    s.reviews,
  ]);
  if (isGroup && rosterSig !== lastRoster) {
    $('roles-panel').hidden = false;
    $('roles-list').replaceChildren(
      ...data.roles.map((role) => {
        const row = node('div', undefined, 'role-card');
        const w = data.workers[role.id] || {};
        const review = s.reviews.find((item) => item.sender === role.id);
        const currentMessage = data.events.some(
          (event) =>
            event.sender === role.id &&
            event.kind === 'message' &&
            event.round_index === s.current_round,
        );
        const label =
          role.backend === 'existing'
            ? '原会话主持'
            : stopped
              ? review?.body.decision === 'accept'
                ? '已确认'
                : review
                  ? '保留异议'
                  : '已结束'
              : ['thinking', 'calling', 'response_ready'].includes(w.state)
                ? '回复中'
                : w.state === 'failed'
                  ? '调用失败'
                  : s.pending_reviewers.includes(role.id)
                    ? '待审核'
                    : review
                      ? review.body.decision === 'accept'
                        ? '已确认记录'
                        : '保留异议'
                      : currentMessage
                        ? '本轮已回复'
                        : '待发言';
        row.append(
          node('strong', role.title),
          node('span', (role.backend === 'existing' ? '当前会话' : role.backend) + ' · ' + label),
          node('p', role.focus),
        );
        return row;
      }),
    );
    lastRoster = rosterSig;
  }
}
function failure(error) {
  $('connection').textContent = '连接中断';
  $('connection').classList.add('offline');
  $('notice').hidden = false;
  $('notice').textContent = error.message + '（已有记录仍保留；页面会自动重连。）';
  $('activity').textContent = '连接中断 · 暂停更新状态';
  $('activity').classList.remove('busy');
  $('stop').disabled = true;
  $('export').disabled = true;
}
async function poll() {
  try {
    const data = await (await api('/api/state')).json();
    render(data);
    $('connection').textContent = '已同步';
    $('connection').classList.remove('offline');
  } catch (error) {
    failure(error);
  }
  setTimeout(poll, 1000);
}
$('stop').addEventListener('click', () => {
  if (!stopped) $('stop-dialog').showModal();
});
for (const [id, collapsed] of [
  ['expand-all', false],
  ['collapse-all', true],
]) {
  $(id).addEventListener('click', () => {
    foldState.mode = collapsed ? 'collapsed' : 'expanded';
    foldState.events = {};
    document.querySelectorAll('.message').forEach((article) => foldMessage(article, collapsed));
    saveFolds();
  });
}
addEventListener('hashchange', () => {
  if (!/^#event-\d+$/.test(location.hash)) return;
  const article = document.getElementById(location.hash.slice(1));
  if (article) {
    foldState.events[location.hash.slice(7)] = false;
    foldMessage(article, false);
    saveFolds();
  }
});
$('stop-dialog').addEventListener('close', async () => {
  if ($('stop-dialog').returnValue !== 'stop') return;
  $('stop').disabled = true;
  try {
    await api('/api/stop', 'POST');
    render(await (await api('/api/state')).json());
  } catch (error) {
    failure(error);
  }
});
$('export').addEventListener('click', async () => {
  try {
    const blob = await (await api('/api/export')).blob();
    const url = URL.createObjectURL(blob);
    const a = node('a');
    a.href = url;
    a.download = 'agent-meet-report.md';
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    failure(error);
  }
});
poll();
