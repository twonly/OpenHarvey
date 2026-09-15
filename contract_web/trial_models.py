"""Server-only platform connections; public model metadata contains no credentials."""
import json
import os


def trial_models():
    models = {}
    if os.environ.get('CW_TRIAL_MODEL_KEY'):
        mid = os.environ.get('CW_TRIAL_MODEL', 'glm-5.3-flash')
        if mid == 'glm-5.3': mid = 'glm-5.3-flash'
        models[mid] = {
            'id': mid, 'label': 'GLM-5.3-flash' if mid == 'glm-5.3-flash' else mid,
            'context': 1_000_000, 'output': 128_000,
            'key': os.environ['CW_TRIAL_MODEL_KEY'],
            'base_url': os.environ.get('CW_TRIAL_MODEL_BASE_URL', '').rstrip('/'),
            'native': json.loads(os.environ.get('CW_TRIAL_MODEL_NATIVE', '{}')),
        }
    if os.environ.get('CW_TRIAL_DEEPSEEK_KEY'):
        models['deepseek-flash'] = {
            'id': 'deepseek-flash', 'label': 'deepseek-flash',
            'context': 1_000_000, 'output': 384_000,
            'key': os.environ['CW_TRIAL_DEEPSEEK_KEY'],
            'base_url': os.environ.get('CW_TRIAL_DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/'),
            'native': {'reasoning': True, 'tool_call': True,
                       'interleaved': {'field': 'reasoning_content'}},
        }
    return models


def public_trial_models():
    return [{'id': m['id'], 'label': m['label'], 'context': m['context'],
             'output': m['output'], 'enabled': True, 'native': m['native']}
            for m in trial_models().values()]
