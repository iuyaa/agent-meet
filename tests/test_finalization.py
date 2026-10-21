import copy
import json
import os
import sys
import unittest
from pathlib import Path

import test_group
from test_peer import FAKE_CLAUDE
import chat
import peer


@unittest.skipIf(os.name == 'nt', 'model fixtures use Unix executable shebangs')
class FinalizationTests(unittest.TestCase):
    def setUp(self):
        self.g = test_group.GroupTests(methodName='test_five_roles_keep_distinct_native_sessions_and_see_previous_round')
        self.g.setUp()
        self.g.roles = self.g.roles[:2]

    def tearDown(self):
        self.g.tearDown()

    def command(self, script, action, *args, **kwargs):
        return self.g.command(script, action, *args, **kwargs)

    def initialize(self, mode='group', finish_reviews=True):
        if mode == 'group':
            self.g.initialize(rounds=1);self.g.run_round()
        else:
            self.g.cli.write_text(FAKE_CLAUDE,encoding='utf-8')
            self.command('consult.py','init','--cwd',self.g.root,'--briefing-file',self.g.brief_file,'--cli',self.g.cli)
            self.command('consult.py','reply','--request-id','peer1')
        self.g.propose()
        self.accepted = 0
        return self.review_all() if finish_reviews else self.command('chat.py','status')['status']

    def review_all(self):
        current=self.command('chat.py','status')['status']
        names=[r['id'] for r in self.g.roles] if current.get('mode')=='group' else ['claude']
        for index,name in enumerate(names):
            if index < self.accepted:continue
            comment='确认准确。' if index == 0 and len(names)>1 else '1. 补充压缩后的验证。\n2. 数据匹配也要考虑来源。'
            result=self.command('chat.py','review','--as',name,'--request-id','review-'+str(current['latest_proposal']['id']),
                '--proposal',current['latest_proposal']['id'],'--decision','accept','--text',comment)
        return result['status']

    def body(self, status=None, changes='clarification'):
        status=status or self.command('chat.py','status')['status']
        conclusion=copy.deepcopy(status['latest_proposal']['body'])
        if changes!='none':conclusion['summary']+='；最终补充：压缩后的验证与数据来源匹配仍需确认。'
        return {'proposal_id':status['latest_proposal']['id'],'review_ids':[r['id'] for r in status['review_feedback']],
            'change_type':changes,'conclusion':conclusion,'resolutions':[
                {'review_id':r['id'],'point':point,'disposition':'already_covered' if '确认准确' in point else 'incorporated',
                 'resolution':'原稿已准确记录；补充事项已写入最终说明，保留待验证边界。'}
                for r in status['review_feedback'] for point in r['body']['comment'].splitlines()]}

    def finalize(self, body, request='final', actor='codex', ok=True):
        path=self.g.root/(request+'.json');path.write_text(json.dumps(body,ensure_ascii=False),encoding='utf-8')
        return self.command('chat.py','finalize','--as',actor,'--request-id',request,'--file',path,ok=ok)

    def test_acceptance_requires_host_reconciliation_and_pending_export_is_labelled(self):
        status=self.initialize()
        self.assertEqual(status['phase'],'finalizing')
        self.assertEqual(status['finalization_status'],'pending')
        self.assertIsNone(status['latest_finalization'])
        self.assertEqual(chat.next_action(status,'codex'),'finalize')
        self.assertEqual(chat.next_action(status,'role0'),'wait')
        path=self.g.root/'pending.md';result=self.command('chat.py','export','--output',path)
        self.assertEqual(result['finalization_status'],'pending')
        self.assertIn('尚无最终结论',path.read_text())
        self.assertNotIn('全部角色已确认记录',path.read_text().split('## 完整记录')[0])

    def test_pair_final_conclusion_and_export_include_last_review_points(self):
        status=self.initialize('pair');body=self.body(status)
        result=self.finalize(body);value=result['status']
        self.assertEqual(value['phase'],'closed');self.assertEqual(value['close_reason'],'agreement')
        self.assertEqual(value['finalization_status'],'finalized')
        self.assertEqual(value['latest_proposal']['body'],status['latest_proposal']['body'])
        self.assertEqual(value['latest_finalization']['body']['conclusion'],body['conclusion'])
        path=self.g.root/'final.md';self.command('chat.py','export','--output',path)
        report=path.read_text();self.assertIn('最终结论',report);self.assertIn(body['conclusion']['summary'],report)
        self.assertIn('最后审核意见处理',report);self.assertIn('措辞未再次送审',report)
        self.assertEqual(value['message_count'],status['message_count'])

    def test_group_requires_all_reviews_and_resolutions_including_last_role(self):
        status=self.initialize(finish_reviews=False)
        self.finalize(self.body(status),ok=False)
        proposal=status['latest_proposal']['id']
        self.command('chat.py','review','--as','role0','--request-id','review-'+str(proposal),'--proposal',proposal,
                     '--decision','accept','--text','确认准确。')
        self.accepted=1;status=self.review_all();body=self.body(status)
        missing=copy.deepcopy(body);missing['review_ids']=body['review_ids'][:-1];self.finalize(missing,'missing-review',ok=False)
        missing=copy.deepcopy(body);missing['resolutions']=[r for r in body['resolutions'] if r['review_id']==body['review_ids'][0]]
        self.finalize(missing,'missing-resolution',ok=False)
        self.assertEqual(self.finalize(body)['status']['phase'],'closed')

    def test_only_original_host_may_publish_final_conclusion(self):
        self.initialize();self.finalize(self.body(),actor='role0',ok=False)

    def test_feedback_quotes_must_come_from_the_current_review(self):
        self.initialize();body=self.body();body['resolutions'][-1]['point']='虚构的审核意见'
        self.finalize(body,ok=False)

    def test_unchanged_finalization_cannot_hide_conclusion_edits(self):
        self.initialize();body=self.body();body['change_type']='none'
        self.finalize(body,'hidden-edit',ok=False)
        body=self.body(changes='none');self.assertEqual(self.finalize(body)['status']['phase'],'closed')

    def test_substantive_change_requires_revised_proposal_and_original_role_sessions(self):
        self.initialize();body=self.body();body['change_type']='substantive'
        self.finalize(body,'substantive',ok=False)
        originals={r['id']:peer.read_status(peer.paths(self.g.room,r['id']))['native_session_id'] for r in self.g.roles}
        self.g.propose(request='revision')
        self.finalize(body,'stale-draft',ok=False)
        self.g.run_round('review-revision')
        self.finalize(self.body(),'revised-final')
        for role in self.g.roles:
            calls=self.g.calls(role['id']);self.assertEqual(calls[-1]['argv'][calls[-1]['argv'].index('--resume')+1],originals[role['id']])

    def test_finalization_is_idempotent_and_conflicting_retry_is_rejected(self):
        self.initialize();body=self.body();first=self.finalize(body)
        second=self.finalize(body);self.assertTrue(second['duplicate']);self.assertEqual(second['event']['id'],first['event']['id'])
        changed=copy.deepcopy(body);changed['resolutions'][0]['resolution']='修改原操作的内容'
        self.finalize(changed,ok=False)

    def test_continuation_preserves_final_history_and_clears_current_final(self):
        self.initialize();body=self.body();first=self.finalize(body)
        self.command('chat.py','extend','--as','codex','--request-id','more','--rounds','1','--reason','用户要求继续')
        current=self.command('chat.py','status')['status'];self.assertIsNone(current['latest_finalization'])
        self.assertIsNone(current['latest_proposal']);self.assertEqual(current['phase'],'discussing')
        replay=self.finalize(body);self.assertTrue(replay['duplicate']);self.assertIsNone(replay['status']['latest_finalization'])
        with chat.database(self.g.room) as conn:self.assertEqual(conn.execute("SELECT COUNT(*) FROM events WHERE kind='finalization'").fetchone()[0],1)

    def test_stop_during_finalization_does_not_publish_a_final_conclusion(self):
        self.initialize();body=self.body();self.command('chat.py','stop','--reason','用户停止')
        self.finalize(body,ok=False)
        self.assertIsNone(self.command('chat.py','status')['status']['latest_finalization'])

    def test_reconciling_saved_reviews_after_deadline_requires_no_new_model_call(self):
        self.initialize();body=self.body()
        with chat.database(self.g.room,write=True) as conn:conn.execute('UPDATE room SET expires=0')
        self.assertEqual(self.finalize(body)['status']['phase'],'closed')

    def test_late_substantive_revision_requires_explicit_more_review_time(self):
        self.initialize()
        with chat.database(self.g.room,write=True) as conn:conn.execute('UPDATE room SET expires=0')
        self.g.propose(request='late-revision',ok=False)

    def test_rejected_review_cannot_be_finalized(self):
        status=self.initialize(finish_reviews=False)
        self.command('chat.py','review','--as','role0','--request-id','reject','--proposal',status['latest_proposal']['id'],
                     '--decision','reject','--text','需要实质修改')
        self.finalize(self.body(),ok=False)

    def test_legacy_manual_protocol_keeps_its_existing_confirmation_behavior(self):
        self.initialize()
        with chat.database(self.g.room,write=True) as conn:conn.execute('DROP TABLE discussion_lifecycle')
        status=self.command('chat.py','status')['status']
        self.assertEqual(status['phase'],'closed');self.assertEqual(status['finalization_status'],'legacy')
        self.assertEqual(self.finalize(self.body(status))['status']['finalization_status'],'finalized')

    def test_host_request_for_more_discussion_takes_priority_over_finalization(self):
        self.initialize()
        status=self.command('chat.py','status')['status']
        path=self.g.root/'continue-assessment.json'
        path.write_text(json.dumps({'decision':'continue','reason':'最后审核暴露关键缺口',
            'blocking_questions':['尚无关键依据'],'accepted_uncertainties':[], 'next_steps':['补齐依据后再审核'],
            'evidence_message_ids':status['latest_proposal']['body']['evidence_message_ids']}),encoding='utf-8')
        assessed=self.command('chat.py','assess','--as','codex','--request-id','need-more','--file',path)['status']
        self.assertEqual(chat.next_action(assessed,'codex'),'await_extension')
        self.assertIn("user's extension decision",self.command('group.py','status')['next_action'])
        self.finalize(self.body(),ok=False)
