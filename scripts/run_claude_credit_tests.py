"""One-time, credit-only Claude adapter run; key is transient and never saved."""
import argparse
import getpass
import json
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'claude-haiku-4-5-20251001'
LIMIT_MICRO_USD = 200_000
MAX_OUTPUT = 256
MAX_CALLS = 36
REPORTS = ROOT / 'reports' / 'claude-credit-adapters'

class BudgetStop(RuntimeError):
    pass

class CreditBudget:
    def __init__(self, messages):
        self.messages = messages
        self.reserved = 0
        self.calls = 0
        self.count_calls = 0
        self.details = []
        self.usage = []

    def check(self, kwargs):
        if kwargs.get('model') != MODEL or kwargs.get('max_tokens') != MAX_OUTPUT:
            raise BudgetStop('Fixed model/output cap changed')
        if self.calls >= MAX_CALLS:
            raise BudgetStop('Generation request cap reached')
        if set(kwargs) - {'model', 'messages', 'system', 'tools', 'max_tokens', 'temperature'}:
            raise BudgetStop('Unapproved API option')
        count_kwargs = {k:v for k,v in kwargs.items() if k in {'model','messages','system','tools'}}
        count = self.messages.count_tokens(**count_kwargs)
        self.count_calls += 1
        if not isinstance(count.input_tokens, int) or isinstance(count.input_tokens, bool) or count.input_tokens < 0:
            raise BudgetStop("Invalid provider token estimate")
        estimate = count.input_tokens
        # Count endpoint is free. Reserve far more than its estimate and the
        # serialized request bytes to cover message/schema framing and variance.
        from support.provider_adapter_matrix import plain
        wire_bytes = len(json.dumps(plain(count_kwargs), ensure_ascii=False).encode('utf-8'))
        reserved_input = max(estimate * 2 + 1024, wire_bytes + 2048)
        # Verified Haiku 4.5 rates: $1/M input + $5/M output (micro-USD/token).
        amount = reserved_input + 5 * MAX_OUTPUT
        if self.reserved + amount > LIMIT_MICRO_USD:
            raise BudgetStop('Conservative $0.20 credit reservation reached')
        self.reserved += amount
        self.calls += 1
        self.details.append({'input_estimate':estimate, 'reserved_input_tokens':reserved_input,
                             'max_output_tokens':MAX_OUTPUT, 'reserved_micro_usd':amount})

    def record_usage(self, response):
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        self.usage.append({
            "input_tokens": int(usage.input_tokens),
            "output_tokens": int(usage.output_tokens),
            "cache_creation_input_tokens": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
            "cache_read_input_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        })

    def create(self, **kwargs):
        self.check(kwargs)
        result = self.messages.create(**kwargs)
        self.record_usage(result)
        return result

    def stream(self, **kwargs):
        self.check(kwargs)
        return UsageStream(self.messages.stream(**kwargs), self)


class UsageStream:
    def __init__(self, inner, budget):
        self.inner = inner
        self.budget = budget
        self.active = None

    def __enter__(self):
        self.active = self.inner.__enter__()
        return self

    @property
    def text_stream(self):
        yield from self.active.text_stream

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.budget.record_usage(self.active.get_final_message())
        finally:
            self.inner.__exit__(exc_type, exc, tb)
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Use only existing Claude credit, with no top-up or automatic recharge.")
    args = parser.parse_args(argv)
    if not args.live:
        print("Offline plan only. Use --live in an interactive terminal to enter a temporary key.")
        print("Claude Haiku 4.5, nine scenarios, conservative reservation at most $0.20 from existing credit.")
        return 0
    if not sys.stdin.isatty():
        raise SystemExit('Interactive terminal required; no visible-input fallback.')
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'tests'))
    # Validate SDK availability before requesting the manual input.
    import anthropic
    from support.provider_adapter_matrix import SCENARIOS, grade, run_case

    from core.system import sdk_clients
    del anthropic
    print('OpenWand: Claude-only adapter test, 9 synthetic scenarios.', flush=True)
    print('Model: ' + MODEL + '; no model/provider fallback; SDK retries=0.', flush=True)
    print('Existing credit only. Conservative run reservation <= $0.20; no top-up or account changes.', flush=True)
    print('At most 36 generation calls, 256 output tokens each, plus free token-count checks.', flush=True)
    print('Enter the key yourself below. It will stay hidden and will not be saved.', flush=True)
    key = getpass.getpass('CLAUDE TEST KEY (hidden): ').strip()
    if not key:
        raise SystemExit('No key entered; stopped without requests.')
    REPORTS.mkdir(parents=True, exist_ok=True)
    results = []
    temp_root = ROOT / '.tmp' / 'provider-adapters'
    temp_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='ow-claude-', dir=temp_root) as temp, ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {
            'OPENWAND_SETTINGS_ENV_PATH': str(Path(temp)/'settings.env'),
            'OPENWAND_USER_DATA_DIR': str(Path(temp)/'user-data'),
            'OPENWAND_DATA_ROOT': str(Path(temp)/'data'),
        }))
        from core import secret_store
        stack.enter_context(patch.object(secret_store, 'get_secret', return_value=''))
        client = sdk_clients.anthropic_client(api_key=key, base_url='https://api.anthropic.com', max_retries=0, timeout=30.0)
        stack.callback(client.close)
        budget = CreditBudget(client.messages)
        wrapped = SimpleNamespace(messages=budget)
        for scenario in SCENARIOS:
            trace = run_case('anthropic', MODEL, scenario, wrapped, Path(temp), max_requests=4, max_tokens=MAX_OUTPUT)
            issues = grade(trace, scenario)
            result = {'scenario':scenario.id,'status':'failed' if issues else 'passed','issues':issues,
                      'generation_requests':budget.calls,'reserved_micro_usd':budget.reserved}
            results.append(result)
            report = json.dumps({**trace.to_dict(), 'issues':issues}, ensure_ascii=False, indent=2).replace(key,'[REDACTED]')
            (REPORTS/(scenario.id+'.json')).write_text(report+'\n')
            print(scenario.id + ': ' + result['status'] + (' ' + ','.join(i['category'] for i in issues) if issues else ''),flush=True)
            if trace.error_category:
                print('Stopped on service/budget error; no automatic retry.',flush=True)
                break
        summary = {'provider':'anthropic','model':MODEL,'results':results,'generation_requests':budget.calls,
                   'free_token_count_requests':budget.count_calls,'conservative_reserved_usd':budget.reserved/1e6,
                   'reservation_limit_usd':0.20,'budget_details':budget.details,'reported_usage':budget.usage,
                   'usage_estimated_usd':sum(u['input_tokens'] + 5*u['output_tokens'] for u in budget.usage)/1e6 if len(budget.usage)==budget.calls and budget.calls and all(not u['cache_creation_input_tokens'] and not u['cache_read_input_tokens'] for u in budget.usage) else None,
                   'not_run':[s.id for s in SCENARIOS if s.id not in {r['scenario'] for r in results}],
                   'note':'Reservation is conservative, not an invoice. Provider usage/dashboard establishes actual credit consumption.'}
        (REPORTS/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        print('Finished: '+str(sum(r['status']=='passed' for r in results))+'/'+str(len(SCENARIOS))+' passed; reserved <= $'+format(budget.reserved/1e6,'.6f')+'.',flush=True)
        print('No key was written to reports or settings. You may revoke the temporary key.',flush=True)
    key = ''
    return 0 if len(results) == len(SCENARIOS) and all(r['status'] == 'passed' for r in results) else 1

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nCancelled. No further requests.')
        raise SystemExit(130) from None
    except Exception as exc:
        print('Stopped: '+type(exc).__name__+'. No automatic retry; no exception contents printed.')
        raise SystemExit(1) from None
