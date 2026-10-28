"""Exercise the production unified UI callbacks and legacy output projection."""
import base64
import json
import sys
import tempfile
import unittest
import zipfile
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import gradio as gr
from app import create_app, parser
from annotation.io import atomic_write, validate_source_mismatch_document
from annotation.workspace import (workspace_issues, materialize_workspace, sync_workspace,
                                  spatial_insert, issues_text)
from annotation.export import collect_annotations, collect_source_mismatches
from PIL import Image


def box(order, **changes):
    return dict(bbox=[order*10,0,order*10+8,8],order=order,status='intact',
                damage_level=None,unknown=False,unavailable_font=False,
                expert_prediction=False,suspicious=False,**changes)


class UnifiedWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        Image.new('RGB',(200,100),'white').save(self.root/'1.png')
        atomic_write(self.root/'source.json',[{'noi_dung':[{'ky_hieu':'1','chuyen_muc':[
            {'tieu_de':'Nguyên văn chữ Hán Nôm','van_ban':'甲乙丙'}]}]}])
        self.options=parser().parse_args(['--image-dir',str(self.root),
            '--source-json',str(self.root/'source.json'),'--output-dir',str(self.root/'out'),
            '--skip-detection'])
        self.app=create_app(self.options)
        self.cb={f.fn.__name__:f.fn for f in self.app.fns.values() if f.fn}
        self.save=self.cb['save_image']
        initial=self.cb['restore_session'](json.dumps({'tab':'workspace'})).session
        opened=self.cb['open_image'](initial,str(self.root/'1.png'))

        self.ctx=list(self.cb['next_with_progress'](opened.session,opened.content_bridge))[-1].session

    def event(self, model, action='checkpoint', **extra):
        result=self.cb['on_workspace_action'](self.ctx,gr.EventData(None,
            dict(action=action,model=model,**extra)))
        self.ctx=result.session
        return result

    def valid_model(self):
        model=deepcopy(self.ctx['active']['workspace'])
        model['boxes']={f'uuid-{i}':box(i) for i in range(1,4)}
        model['confirmed']={uid:entry['char_id'] for uid,entry in
                            zip(model['boxes'],model['entries'])}
        return model

    def test_unified_start_has_no_count_gate_and_warning_matches_download(self):
        self.assertEqual(self.ctx['active']['current_step'],3)
        model=deepcopy(self.ctx['active']['workspace'])
        model['boxes']={'a':box(1),'b':box(2),'c':box(3)}
        model['boxes']['a']['status']=None
        model['boxes']['b'].update(status='damaged',damage_level=None,order=1)
        model['boxes']['c']['order']=5
        result=self.event(model,'continue')
        self.assertEqual(self.ctx['active']['current_step'],3)
        data=result.workspace_board['value']
        reasons='\n'.join(issue['reason'] for issue in data['issues'])
        for message in ('Assign status','Select damage level','Duplicate reading order',
                        'Missing reading orders: 2, 3','integer from 1','Confirm the alignment',
                        'no confirmed box'):
            self.assertIn(message,reasons)
        self.assertEqual(data['report'],issues_text('1.png',data['issues']))
        self.assertIn('Box: b',data['report'])
        self.assertIn('Coordinates: [20, 0, 28, 8]',data['report'])
        self.assertFalse((self.root/'out'/'1.json').exists())

    def test_normal_output_metadata_reload_and_next_image_stays_unified(self):
        model=self.valid_model()
        original_ids=[entry['char_id'] for entry in model['entries']]
        model['preferences'].update(reference_open=False,reference_width=310,reference_scroll=42)
        model['undo']=[{key:deepcopy(model.get(key)) for key in
                       ('entries','boxes','confirmed','selected_box','selected_char','selected_boxes')}]
        result=self.event(model,'continue')
        self.assertEqual(self.ctx['active']['current_step'],6)
        self.ctx=list(self.cb['next_with_progress'](self.ctx,selection='{}'))[-1].session
        self.assertEqual(self.ctx['active']['current_step'],7)
        self.ctx=self.save(self.ctx).session
        self.assertTrue(self.ctx['active']['unified_enabled'])
        doc=json.loads((self.root/'out'/'1.json').read_text())
        self.assertEqual(set(doc),{'image','bounding_boxes','annotations','crop','image_resize'})
        self.assertEqual(doc['annotations'],{'1':'甲','2':'乙','3':'丙'})
        self.assertEqual(collect_annotations([self.root/'1.png'],self.root/'out'),[doc])
        sidecar=json.loads((self.root/'out'/'.state'/'1.json').read_text())
        self.assertEqual(set(sidecar['workspace']['boxes']),set(model['boxes']))
        fresh=create_app(self.options)
        cb={f.fn.__name__:f.fn for f in fresh.fns.values() if f.fn}
        ctx=cb['restore_session']('{}').session
        reopened=cb['open_image'](ctx,str(self.root/'1.png'))

        restored=list(cb['next_with_progress'](reopened.session,reopened.content_bridge))[-1].session['active']['workspace']
        self.assertEqual([entry['char_id'] for entry in restored['entries']],original_ids)
        self.assertEqual(restored['confirmed'],model['confirmed'])
        self.assertEqual(restored['preferences'],model['preferences'])
        self.assertEqual(restored['undo'],model['undo'])

    def test_mixed_corrections_with_equal_source_box_counts_export(self):
        model=self.valid_model()
        model['entries'][1]['excluded']=True
        model['entries'].insert(2,dict(char_id='miss-id',value='MISS',source_index=None,
                                     type='missing',excluded=False))
        active=[entry for entry in model['entries'] if not entry['excluded']]
        model['confirmed']={uid:entry['char_id'] for uid,entry in zip(model['boxes'],active)}
        model['boxes']['uuid-3'].update(status='damaged',damage_level=2,suspicious=True)
        self.event(model,'continue')
        self.assertEqual(self.ctx['active']['current_step'],6)
        self.ctx=list(self.cb['next_with_progress'](self.ctx,selection='{}'))[-1].session
        self.ctx=self.save(self.ctx).session
        path=self.root/'out'/'source_mismatches'/'1.json'
        doc=json.loads(path.read_text())
        self.assertEqual(doc['issue_type'],['missing_text','extra_text'])
        self.assertEqual(doc['annotations'],{'1':'甲','2':'MISS','3':'丙'})
        self.assertEqual(doc['text_sequence'],['甲','MISS','丙','乙'])
        self.assertEqual(doc['excluded_characters'],['乙'])
        self.assertTrue(doc['bounding_boxes']['3']['suspicious'])
        self.assertEqual(doc['bounding_boxes']['3']['damage_level'],2)
        validate_source_mismatch_document(doc,'1.png',[200,100])
        self.assertEqual(collect_source_mismatches([self.root/'1.png'],self.root/'out'),[doc])
        archive=json.loads(self.cb['save_folder']())
        with zipfile.ZipFile(BytesIO(base64.b64decode(archive['content']))) as z:
            self.assertEqual(set(z.namelist()),{'text_annotations.json','inscription_content.json','source_mismatches.json'})
            self.assertEqual(json.loads(z.read('source_mismatches.json')),[doc])
        reopened=self.cb['open_image'](self.ctx,str(self.root/'1.png'))

        restored=list(self.cb['next_with_progress'](reopened.session,reopened.content_bridge))[-1].session['active']['workspace']
        self.assertEqual(restored['entries'],model['entries'])
        self.assertEqual(restored['confirmed'],model['confirmed'])
        self.assertEqual(restored['boxes'],model['boxes'])

    def test_confirmations_survive_edits_and_conflicts_block_continue(self):
        model=self.valid_model(); old=deepcopy(model['boxes'])
        model['entries'].insert(0,dict(char_id='miss',value='MISS',source_index=None,type='missing',excluded=False))
        self.event(model)
        self.assertEqual(self.ctx['active']['workspace']['boxes'],old)
        result=self.event(model,'continue')
        self.assertTrue(any('conflicts' in issue['reason'] for issue in result.workspace_board['value']['issues']))
        self.assertEqual(self.ctx['active']['workspace']['confirmed'],model['confirmed'])
        model['entries'][1]['excluded']=True
        self.event(model,'continue')
        self.assertTrue(any('excluded' in issue['reason'] for issue in self.ctx['active']['workspace_issues']))

    def test_box_insert_preserves_old_relative_order_metadata_and_ids(self):
        model=self.valid_model(); model['boxes']['uuid-2'].update(status='damaged',damage_level=3,suspicious=True)
        model['boxes']['uuid-1']['order']=3
        model['boxes']['uuid-3']['order']=1
        old_order=sorted(model['boxes'],key=lambda uid:model['boxes'][uid]['order'])
        model['boxes']['new']=dict(box(4),bbox=[25,15,30,25])
        self.event(model,'insert',box_id='new')
        actual=self.ctx['active']['workspace']
        ordered=sorted(actual['boxes'],key=lambda uid:actual['boxes'][uid]['order'])
        self.assertEqual([uid for uid in ordered if uid!='new'],old_order)
        self.assertTrue(actual['boxes']['uuid-2']['suspicious'])
        self.assertEqual(actual['boxes']['uuid-2']['damage_level'],3)
        self.assertEqual(actual['confirmed'],model['confirmed'])
        self.assertEqual(sorted(b['order'] for b in actual['boxes'].values()),[1,2,3,4])

    def test_recovery_and_source_integrity(self):
        model=self.valid_model(); model['boxes']['uuid-1'].update(status='damaged',damage_level=None)
        result=self.event(model)
        meta=result.workspace_board['value']['recovery']
        record=dict(metadata=meta,workspace=model)
        restored=self.cb['restore_session'](json.dumps({'tab':'workspace','drafts':{'w':record}}))
        self.assertEqual(restored.session['active']['workspace'],model)
        damaged=restored.session['active']['workspace']['boxes']['uuid-1']
        self.assertEqual(damaged['status'],'damaged');self.assertIsNone(damaged['damage_level'])
        state=deepcopy(self.ctx['active'])
        wrong=deepcopy(model);wrong['entries'][0]['value']='改'
        with self.assertRaisesRegex(ValueError,'Original reference'):
            sync_workspace(state,wrong)
        wrong=deepcopy(model);wrong['entries'][0]['char_id']='new-original-id'
        with self.assertRaisesRegex(ValueError,'IDs cannot change'):
            sync_workspace(state,wrong)
        self.assertEqual(state,self.ctx['active'])

    def test_special_rules_report_conflicts_without_mutating_metadata(self):
        state=deepcopy(self.ctx['active']);model=self.valid_model()
        model['entries'].insert(0,dict(char_id='miss',value='MISS',source_index=None,type='missing',excluded=False))
        model['entries'][1]['excluded']=True
        active=[e for e in model['entries'] if not e['excluded']]
        model['confirmed']={uid:e['char_id'] for uid,e in zip(model['boxes'],active)}
        model['boxes']['uuid-1']['suspicious']=True
        sync_workspace(state,model)
        before=deepcopy(state['regions'])
        issues=workspace_issues(state)
        self.assertTrue(any('mandatory character' in issue['reason'] for issue in issues))
        self.assertEqual(state['regions'],before)

    def test_failed_detection_is_not_retried_when_continuing_workspace(self):
        options=deepcopy(self.options);options.skip_detection=False
        app=create_app(options)
        cb={f.fn.__name__:f.fn for f in app.fns.values() if f.fn}
        opened=cb['open_image'](cb['restore_session']('{}').session,str(self.root/'1.png'))

        with patch('annotation.workflow.detect',side_effect=RuntimeError('detector unavailable')) as detector:
            with self.assertWarnsRegex(UserWarning,'detector unavailable'),self.assertLogs('ui.application',level='ERROR'):
                ctx=list(cb['next_with_progress'](opened.session,opened.content_bridge))[-1].session
            model=deepcopy(ctx['active']['workspace'])
            model['boxes']={f'uuid-{i}':box(i) for i in range(1,4)}
            model['confirmed']={uid:e['char_id'] for uid,e in zip(model['boxes'],model['entries'])}
            result=cb['on_workspace_action'](ctx,gr.EventData(None,dict(action='continue',model=model)))
            self.assertEqual(result.session['active']['current_step'],6)
            self.assertEqual(detector.call_count,1)

    def test_explicit_detection_preserves_content_corrections_and_resets_box_history(self):
        model=self.valid_model();model['entries'][1]['excluded']=True
        options=deepcopy(self.options);options.skip_detection=False
        # The callback closes over its engine options, so use a fresh application.
        app=create_app(options);cb={f.fn.__name__:f.fn for f in app.fns.values() if f.fn}
        with patch('annotation.workflow.detect',return_value={'image':'1.png','bounding_boxes':{
            '1':dict(box(1),bbox=[60,0,68,8]),'2':dict(box(2),bbox=[80,0,88,8])}}):
            result=cb['on_workspace_action'](self.ctx,gr.EventData(None,dict(action='detect',model=model)))
        actual=result.session['active']['workspace']
        self.assertEqual(actual['entries'],model['entries'])
        self.assertEqual(actual['confirmed'],{})
        self.assertEqual(actual['undo'],[])
        self.assertEqual(len(actual['boxes']),2)
        self.assertFalse(set(actual['boxes']) & set(model['boxes']))


if __name__=='__main__':
    unittest.main()
