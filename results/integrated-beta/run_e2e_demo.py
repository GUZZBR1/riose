from __future__ import annotations
import json, sys, hashlib
from pathlib import Path
from fastapi.testclient import TestClient
from riose.products.livestock_tracking.adapters.api import create_app
from riose.products.livestock_tracking.adapters.persistence.publication_outbox import SQLitePublicationOutbox
from riose.products.livestock_tracking.adapters.persistence.sqlite_store import Store
from riose.products.livestock_tracking.domain.contracts import Anchor
from riose.simulation_adapter.adapter import convert_result

root = Path(__file__).resolve().parent
run = root / 'simulation' / 'c93252ed65524582abec8f384b8d9ed3'
result_path, manifest_path = run/'result/result.json', run/'manifest.json'
request = json.loads((run/'request/request.json').read_text())
result = json.loads(result_path.read_text())
manifest = json.loads(manifest_path.read_text())
batch = convert_result(result, run_manifest=manifest)
db = root/'e2e'/'demo.sqlite3'
db.parent.mkdir(parents=True, exist_ok=True)
if db.exists(): db.unlink()
app = create_app(db)
with TestClient(app) as client:
    health = client.get('/api/health'); assert health.status_code == 200 and health.json()['evidence'] == 'SIMULATED'
    page = client.get('/demo'); assert page.status_code == 200 and '<html' in page.text.lower()
    created = client.post('/api/animals', json={'animal_id':'riose-animal-001','hardware_id':'riose-tag-001','name':'Simulated animal','property_name':'Simulation demo'})
    assert created.status_code == 201, created.text
    store = app.state.store
    anchors = [Anchor(anchor_id=x['anchor_ref'], x=x['position_m'][0], y=x['position_m'][1], height_m=x['position_m'][2], kind='simulated-frequencia') for x in request['receivers']]
    store.save_anchors(anchors)
    app.state.anchors = anchors
    api_anchors = client.get('/api/anchors').json()
    assert len(api_anchors) == len(anchors)
    accepted = [estimate for estimate, meta in zip(batch.estimates, batch.estimate_provenance) if meta.get('quality_status') == 'ACCEPTED']
    store.save_episode(batch.observations, accepted, (), persist_truth=False)
    run_record = {
      'run_id': manifest['run_id'], 'campaign_id': manifest['campaign_id'], 'scenario_id': manifest['scenario_metadata'].get('scenario_id', result['scenario_id']),
      'classification': 'SIMULATED', 'backend': manifest['backend_used'],
      'request_sha256': manifest['request_sha256'], 'result_sha256': hashlib.sha256(result_path.read_bytes()).hexdigest(),
      'observations_converted': len(batch.observations), 'estimates_converted': len(batch.estimates),
      'accepted_positions_persisted': len(accepted), 'behavior': {'status':'UNAVAILABLE','predictions':[]},
      'truth_persisted': False, 'coordinate_frame': 'ENU_LOCAL',
    }
    store.set_metrics({'integrated_beta_simulation': run_record})
    event = client.post('/api/events', json={'animal_id':'riose-animal-001','event_type':'SIMULATION_RUN_RECORDED','payload':{'run_id':manifest['run_id'],'classification':'SIMULATED','request_sha256':manifest['request_sha256'],'result_sha256':run_record['result_sha256'],'behavior_status':'UNAVAILABLE'}})
    assert event.status_code == 201 and event.json()['chain_valid'] is True, event.text
    event_id = event.json()['event_id']
    outbox = SQLitePublicationOutbox(store)
    pub = outbox.enqueue_event(event_id, destination='solana-memo', network='devnet', idempotency_key='integrated-beta-'+manifest['run_id'])
    assert outbox.verify_local_binding(pub['publication_id'])
    assert len(outbox.list_pending()) == 1
    telemetry = client.get('/api/telemetry', params={'tag_id':'riose-tag-001'}).json()
    positions = client.get('/api/positions/history', params={'tag_id':'riose-tag-001','limit':100}).json()
    chain = client.get('/api/animals/riose-animal-001/events/verify').json()
    assert len(telemetry) == len(batch.observations)
    assert len(positions) == len(accepted) == 0
    assert chain['valid'] is True
    evidence = {'health':health.json(),'demo_http_status':page.status_code,'dashboard_browser_rendering':'NOT_TESTED','animal_created':True,'api_animal_count':len(client.get('/api/animals').json()),'anchors_saved':len(anchors),'anchors_exposed_by_api':len(api_anchors),'telemetry_persisted':len(telemetry),'positions_persisted':len(positions),'behavior_status':'UNAVAILABLE','event_chain_valid':chain['valid'],'publication_status':pub['status'],'local_commitment_binding_valid':True,'real_on_chain':'UNVERIFIED','receipts':0,'run':run_record}
    outbox_ref = pub['publication_id']
# Reopen the same database to verify persistence/recovery across close/reopen.
restarted_app = create_app(db)
with TestClient(restarted_app) as restarted_client:
    assert len(restarted_client.get('/api/anchors').json()) == 4
    assert len(restarted_client.get('/api/animals').json()) == 1
    assert restarted_client.get('/demo').status_code == 200
reopened = Store(db)
assert reopened.verify_animal_chain('riose-animal-001')
assert len(reopened.telemetry(tag_id='riose-tag-001')) == len(batch.observations)
assert reopened.get_metrics()['integrated_beta_simulation']['run_id'] == manifest['run_id']
reopened.close()
evidence['reopen_verification'] = True
evidence['reopen_api_anchors'] = 4
evidence['publication_id'] = outbox_ref
(root/'e2e'/'report.json').write_text(json.dumps(evidence,indent=2)+'\n')
print(json.dumps(evidence,indent=2))
