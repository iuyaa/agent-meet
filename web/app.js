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
  stopped = false;
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
  const reviewer = event.sender === data.reviewer;
  const el = node('article', undefined, 'message ' + (reviewer ? 'reviewer ' : '') + event.kind);
  el.id = 'event-' + event.id;
  el.append(node('div', event.sender.charAt(0).toUpperCase(), 'avatar'));
  const content = node('div');
  const meta = node('div', undefined, 'message-meta');
  const name =
    event.sender === 'codex' ? 'Codex' : event.sender === 'claude' ? 'Claude' : event.sender;
  meta.append(
    node('span', name, 'sender'),
    node('span', reviewer ? '讨论伙伴' : '主参与者', 'role'),
  );
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
  if (event.kind === 'proposal') {
    const review = data.events.find((item) => item.kind === 'review' && item.reply_to === event.id);
    const label = review
      ? review.body.decision === 'accept'
        ? '已确认记录'
        : '对方提出异议'
      : data.status.phase === 'closed'
        ? '尚未确认'
        : '等待对方审核';
    bubble.append(node('span', '结论草案 · ' + label, 'proposal-label'), conclusion(event.body));
  } else if (event.kind === 'review') {
    const accepted = event.body.decision === 'accept';
    bubble.append(
      node(
        'span',
        accepted ? '✓ 已确认记录准确' : '提出异议 · 需要修订',
        'review-label ' + (accepted ? '' : 'rejected'),
      ),
      markdown(event.body.comment),
    );
  } else if (data.briefing && event.request_id === 'consult-opening') {
    bubble.append(
      node('div', '带入本次讨论的上下文', 'opening-label'),
      markdown(data.briefing.current_view, 'opening-view'),
    );
    const details = node('details');
    details.append(node('summary', '查看完整开场简报'), markdown(event.body, 'full-brief'));
    bubble.append(details);
  } else {
    bubble.append(markdown(event.body));
  }
  content.append(bubble);
  el.append(content);
  return el;
}
function render(data) {
  const s = data.status,
    model = data.model,
    worker = data.worker;
  stopped = s.phase === 'closed';
  $('topic').textContent = s.topic;
  document.title = s.topic + ' · Agent Chat';
  $('participants').textContent = s.participants.join('  +  ');
  $('count').textContent = s.message_count + ' / ' + s.max_messages + ' 条发言';
  let activity;
  if (stopped) {
    activity =
      s.close_reason === 'agreement'
        ? '讨论结束 · 双方已确认记录'
        : s.close_reason === 'expired'
          ? '讨论期限已到 · 未确认的草案仍保留原状态'
          : '讨论已停止 · 已有记录已保留';
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
    !stopped && (model.state === 'calling' || worker.state === 'thinking'),
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
    (model.state === 'failed' ? model.detail : worker.state === 'failed' ? worker.detail : null);
  $('notice').hidden = !error;
  $('notice').textContent = error || '';
  $('stop').disabled = stopped;
  $('export').disabled = false;
  const sig = JSON.stringify([data.events, s.phase]);
  if (sig !== lastEvents) {
    const nearBottom =
      window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 180;
    const initial = !lastEvents;
    $('messages').replaceChildren(...data.events.map((event) => message(event, data)));
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
      out.append(
        node('div', labels[s.conclusion_status], 'outcome-status ' + s.conclusion_status),
        conclusion(s.latest_proposal.body),
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
