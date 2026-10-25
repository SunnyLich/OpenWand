"""Offline guards for the explicit, existing-credit-only Claude runner."""
from __future__ import annotations

import socket
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import run_claude_credit_tests as runner


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError('These budget tests must never use the network')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)


@pytest.fixture
def kwargs():
    return {'model': runner.MODEL, 'max_tokens': 256, 'messages': [{'role': 'user', 'content': 'hello'}]}


def endpoint(count=1000):
    return SimpleNamespace(
        count_tokens=Mock(return_value=SimpleNamespace(input_tokens=count)),
        create=Mock(return_value=SimpleNamespace(usage=SimpleNamespace(input_tokens=1000, output_tokens=12))),
        stream=Mock(),
    )


def test_default_is_offline_and_never_prompts(monkeypatch, capsys):
    monkeypatch.setattr(runner.getpass, 'getpass', Mock(side_effect=AssertionError('must not ask for a key')))
    assert runner.main([]) == 0
    assert 'Offline plan only' in capsys.readouterr().out


def test_live_refuses_noninteractive_visible_key_input(monkeypatch):
    monkeypatch.setattr(runner.sys.stdin, 'isatty', lambda: False)
    monkeypatch.setattr(runner.getpass, 'getpass', Mock(side_effect=AssertionError('must not ask for a key')))
    with pytest.raises(SystemExit, match='Interactive terminal required'):
        runner.main(['--live'])


@pytest.mark.parametrize('change', [
    {'model': 'claude-expensive-other'}, {'max_tokens': 257}, {'thinking': {'type': 'enabled'}},
    {'cache_control': {}}, {'extra_headers': {}},
])
def test_unapproved_model_tokens_or_features_fail_before_any_request(kwargs, change):
    api = endpoint()
    budget = runner.CreditBudget(api)
    with pytest.raises(runner.BudgetStop):
        budget.create(**{**kwargs, **change})
    api.count_tokens.assert_not_called()
    api.create.assert_not_called()


def test_preflight_reserves_padded_input_and_full_output_before_generation(kwargs):
    api = endpoint()
    budget = runner.CreditBudget(api)
    budget.create(**kwargs)
    assert budget.reserved == (2 * 1000 + 1024) + (256 * 5)
    assert budget.details[0]['reserved_input_tokens'] == 3024
    assert budget.calls == budget.count_calls == 1
    assert budget.usage == [{'input_tokens': 1000, 'output_tokens': 12,
                             'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0}]
    assert 'max_tokens' not in api.count_tokens.call_args.kwargs
    assert api.create.call_count == 1


def test_high_input_preflight_stops_without_generation(kwargs):
    api = endpoint(count=100000)
    budget = runner.CreditBudget(api)
    with pytest.raises(runner.BudgetStop, match='reservation reached'):
        budget.create(**kwargs)
    assert budget.reserved == 0
    assert budget.count_calls == 1
    assert budget.calls == 0
    api.create.assert_not_called()


def test_request_cap_prevents_even_another_count_call(kwargs):
    api = endpoint(count=100)
    budget = runner.CreditBudget(api)
    for _ in range(36):
        budget.create(**kwargs)
    with pytest.raises(runner.BudgetStop, match='request cap'):
        budget.create(**kwargs)
    assert api.count_tokens.call_count == api.create.call_count == 36
    assert budget.reserved <= 200000


def test_cumulative_reservation_stops_before_twenty_cents(kwargs):
    api = endpoint(count=15000)
    budget = runner.CreditBudget(api)
    with pytest.raises(runner.BudgetStop, match='reservation reached'):
        while True:
            budget.create(**kwargs)
    assert budget.calls == api.create.call_count == 6
    assert budget.reserved == 6 * (31024 + 1280)
    assert budget.reserved <= 200000


def test_unknown_generation_failure_keeps_full_reservation(kwargs):
    api = endpoint()
    api.create.side_effect = ConnectionError('fixture failure')
    budget = runner.CreditBudget(api)
    with pytest.raises(ConnectionError):
        budget.create(**kwargs)
    assert budget.reserved == 4304
    assert budget.calls == 1
    assert not budget.usage


def test_failed_free_preflight_does_not_generate_or_reserve(kwargs):
    api = endpoint()
    api.count_tokens.side_effect = ConnectionError('fixture failure')
    budget = runner.CreditBudget(api)
    with pytest.raises(ConnectionError):
        budget.create(**kwargs)
    assert budget.calls == budget.reserved == budget.count_calls == 0
    api.create.assert_not_called()


@pytest.mark.parametrize('invalid', [-1, True, '100'])
def test_invalid_count_fails_closed(kwargs, invalid):
    api = endpoint(count=invalid)
    budget = runner.CreditBudget(api)
    with pytest.raises(runner.BudgetStop, match='Invalid provider'):
        budget.create(**kwargs)
    api.create.assert_not_called()


def test_serialized_input_floor_covers_long_payload_even_if_estimate_is_small(kwargs):
    api = endpoint(count=1)
    budget = runner.CreditBudget(api)
    kwargs['messages'][0]['content'] = 'x' * 10000
    budget.create(**kwargs)
    assert budget.details[0]['reserved_input_tokens'] > 12048


def test_stream_tracks_usage_and_closes(kwargs):
    api = endpoint()
    active = SimpleNamespace(text_stream=iter(['42']), get_final_message=Mock(return_value=api.create.return_value))
    manager = Mock()
    manager.__enter__ = Mock(return_value=active)
    manager.__exit__ = Mock(return_value=False)
    api.stream.return_value = manager
    budget = runner.CreditBudget(api)
    with budget.stream(**kwargs) as stream:
        assert list(stream.text_stream) == ['42']
    assert len(budget.usage) == 1
    manager.__exit__.assert_called_once()


@pytest.mark.parametrize('issues,expected_exit', [([], 0), ([{'category': 'transport'}], 1)])
def test_main_reports_failure_as_nonzero_without_network(monkeypatch, tmp_path, issues, expected_exit):
    from support import provider_adapter_matrix as matrix

    from core.system import sdk_clients

    client = SimpleNamespace(messages=endpoint(), close=Mock())
    trace = SimpleNamespace(error_category='transport' if issues else None, to_dict=lambda: {})
    monkeypatch.setattr(runner.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(runner.getpass, 'getpass', lambda _prompt: 'fixture')
    monkeypatch.setattr(runner, 'REPORTS', tmp_path)
    monkeypatch.setattr(matrix, 'SCENARIOS', [SimpleNamespace(id='no_tools')])
    monkeypatch.setattr(matrix, 'run_case', Mock(return_value=trace))
    monkeypatch.setattr(matrix, 'grade', lambda *_args: issues)
    monkeypatch.setattr(sdk_clients, 'anthropic_client', Mock(return_value=client))

    assert runner.main(['--live']) == expected_exit
    client.messages.count_tokens.assert_not_called()
    client.messages.create.assert_not_called()
    client.close.assert_called_once()
