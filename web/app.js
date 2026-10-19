'use strict';
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
  const name = role
    ? role.title
    : event.sender === 'codex'
      ? 'Codex'
      : event.sender === 'claude'
        ? 'Claude'
        : event.sender;
  meta.append(
    node('span', name, 'sender'),
    node(
      'span',
      role
        ? role.backend === 'existing'
          ? '当前会话'
          : role.backend === 'claude'
            ? 'Claude'
            : 'Codex'
        : reviewer
          ? '讨论伙伴'
          : '主参与者',
      'role',
    ),
  );
  if (event.round_index) meta.append(node('span', '第 ' + event.round_index + ' 轮', 'round-tag'));
  const time = node(
    'time',
    new Date(event.created).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
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
  if (event.kind === 'proposal') {
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
    body.append(node('span', '结论草案 · ' + label, 'proposal-label'), conclusion(event.body));
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
function render(data) {
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
  document.title = s.topic + ' · Agent Chat';
  $('participants').textContent = s.participants.map(display).join('  +  ');
  $('participant-count').textContent =
    '／ ' + String(s.participants.length).padStart(2, '0') + ' PARTICIPANTS';
  $('round-progress').textContent = isGroup
    ? '第 ' + s.current_round + ' / ' + s.max_rounds + ' 轮 · ' + s.completed_rounds + ' 轮已完成'
    : '长消息可折叠查看';
  $('count').textContent = s.message_count + ' / ' + s.max_messages + ' 条发言';
  let activity;
  if (stopped) {
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
            ? '轮次或讨论时间已到 · 等待主持人提交结论'
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
    activity = '进入总结阶段 · 等待结论草案';
  } else {
    activity = '等待 ' + s.next_speaker + ' 发言';
  }
  $('activity').textContent = activity;
  $('activity').classList.toggle(
    'busy',
    !stopped && (active.length > 0 || model.state === 'calling' || worker.state === 'thinking'),
  );
  $('phase').textContent = stopped
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
  const outcomeSig = JSON.stringify([s.latest_proposal, s.latest_review, s.phase]);
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
        node('div', labels[s.conclusion_status], 'outcome-status ' + s.conclusion_status),
        conclusion(s.latest_proposal.body),
      );
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
          stopped ? '讨论结束，尚无结论草案。' : '结论形成后，共识、分歧与待验证问题会出现在这里。',
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
    a.download = 'agent-chat-report.md';
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    failure(error);
  }
});
poll();
