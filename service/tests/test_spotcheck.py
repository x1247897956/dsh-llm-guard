"""Review coverage uses the original corpus, and judgments stay blind."""
import csv
import json

import pytest

from eval.spotcheck import make_sheet, score_sheet


@pytest.fixture
def inputs(tmp_path):
    dataset = tmp_path / 'dataset.jsonl'
    predictions = tmp_path / 'predictions.jsonl'
    records = [dict(id=f's{i}', text=f'example {i}', category='test', label=i % 2)
               for i in range(20)]
    dataset.write_text('\n'.join(json.dumps(r) for r in records))
    predictions.write_text('\n'.join(json.dumps(dict(id=r['id'], mode='rules+semantic', pred=r['label'])) for r in records))
    return dataset, predictions, tmp_path / 'sheet.csv', tmp_path / 'result.json'


def write_review(path, count, **extra):
    rows = [dict(id=f's{i}', text=f'example {i}', human_label=str(i % 2), human_note='reviewed', **extra)
            for i in range(count)]
    with path.open('w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_blind_sheet_contains_no_answer_hints(inputs):
    dataset, predictions, sheet, _ = inputs
    assert make_sheet(dataset, predictions, sheet, 'rules+semantic', .25, 10) == 0
    with sheet.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 6
    assert set(rows[0]) == {'id', 'text', 'human_label', 'human_note'}
    assert all(row['human_label'] == '' for row in rows)


def test_coverage_uses_full_dataset_and_fails_below_twenty_percent(inputs):
    dataset, predictions, sheet, result = inputs
    write_review(sheet, 3)
    assert score_sheet(sheet, result, dataset, predictions) == 1
    scored = json.loads(result.read_text())
    assert scored['n_dataset'] == 20
    assert scored['spotcheck_frac'] == .15
    assert scored['coverage_requirement_met'] is False


def test_score_joins_trusted_sources_not_sheet_labels(inputs):
    dataset, predictions, sheet, result = inputs
    write_review(sheet, 4, author_label='wrong', machine_pred='wrong', category='wrong')
    assert score_sheet(sheet, result, dataset, predictions) == 0
    scored = json.loads(result.read_text())
    assert scored['spotcheck_frac'] == .2
    assert scored['agreement_machine_vs_human_label'] == 1
    assert scored['agreement_human_vs_author_label'] == 1


@pytest.mark.parametrize('alter', ['duplicate', 'unknown', 'text', 'label'])
def test_invalid_review_cannot_inflate_or_corrupt_score(inputs, alter):
    dataset, predictions, sheet, result = inputs
    write_review(sheet, 4)
    with sheet.open() as fh:
        rows = list(csv.DictReader(fh))
    if alter == 'duplicate':
        rows.append(rows[0])
    elif alter == 'unknown':
        rows[0]['id'] = 'unknown'
    elif alter == 'text':
        rows[0]['text'] = 'different example'
    else:
        rows[0]['human_label'] = '2'
    with sheet.open('w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError):
        score_sheet(sheet, result, dataset, predictions)
    assert not result.exists()


def test_blank_sheet_is_not_human_evidence(inputs):
    dataset, predictions, sheet, result = inputs
    make_sheet(dataset, predictions, sheet, 'rules+semantic', .25, 10)
    assert score_sheet(sheet, result, dataset, predictions) == 1
    assert not result.exists()
