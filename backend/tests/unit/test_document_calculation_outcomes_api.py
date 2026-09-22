import json

from app.models.artifacts import PdfDocument
from app.services.ingestion_service import IngestionService


OUTCOME = {
    'calculation': 'piotroski_f_score', 'status': 'unavailable',
    'reason_code': 'unresolved_source_reconciliation',
    'blocking_reasons': ['period_identity_unavailable'],
}


def _document(db_session, user):
    doc = PdfDocument(user_id=user.id, file_name='diagnostic.pdf', source='upload',
        file_storage_key='/tmp/private-diagnostic.pdf', parse_status='parsed',
        notes='private generic note /Users/private\ncalculation_outcomes: ' + json.dumps({
            'stock_id': 1, 'page_number': 1, 'outcomes': [OUTCOME]}))
    db_session.add(doc)
    db_session.commit()
    return doc


def test_current_documents_expose_only_owned_typed_calculation_diagnostics(
    client, db_session, user_factory, auth_headers,
):
    owner = user_factory('calc-owner@example.com')
    other = user_factory('calc-other@example.com')
    own_doc = _document(db_session, owner)
    foreign_doc = _document(db_session, other)
    response = client.get('/api/v1/documents', headers=auth_headers(owner))
    assert response.status_code == 200
    assert {r['id'] for r in response.json()} == {own_doc.id}
    assert foreign_doc.id != own_doc.id
    row = response.json()[0]
    assert row['calculation_outcomes'] == [OUTCOME]
    assert 'notes' not in row
    assert '/Users/private' not in response.text
    assert 'private generic note' not in response.text


def test_cursor_snapshot_does_not_retrofit_current_calculation_diagnostics(
    client, db_session, user_factory, auth_headers,
):
    owner = user_factory('calc-snapshot-owner@example.com')
    doc = _document(db_session, owner)
    response = client.get('/api/v1/documents?limit=1', headers=auth_headers(owner))
    assert response.status_code == 200
    assert response.headers['X-Pagination-Mode'] == 'cursor'
    assert response.json()[0]['id'] == doc.id
    assert 'calculation_outcomes' not in response.json()[0]
    assert '/Users/private' not in response.text


def test_reparse_response_retains_typed_block_and_ownership(
    client, db_session, user_factory, auth_headers, monkeypatch,
):
    owner = user_factory('calc-reparse-owner@example.com')
    other = user_factory('calc-reparse-other@example.com')
    doc = _document(db_session, owner)
    calls = []

    def completed(self, *, user_id, document_id, reextract_pdf=False):
        calls.append((user_id, document_id))
        return doc

    monkeypatch.setattr(IngestionService, 'reparse_existing_document', completed)
    denied = client.post(f'/api/v1/documents/{doc.id}/reparse', headers=auth_headers(other))
    assert denied.status_code == 404
    assert not calls
    response = client.post(f'/api/v1/documents/{doc.id}/reparse', headers=auth_headers(owner))
    assert response.status_code == 200
    assert response.json()['status'] == 'parsed'
    assert response.json()['calculation_outcomes'] == [OUTCOME]
    assert calls == [(owner.id, doc.id)]
    assert '/Users/private' not in response.text
