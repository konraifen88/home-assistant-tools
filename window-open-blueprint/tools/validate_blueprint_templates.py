import yaml
from jinja2 import Environment, StrictUndefined
from jinja2 import Environment, StrictUndefined
import yaml as _yaml
from types import SimpleNamespace
import sys
from pathlib import Path
from datetime import datetime

bp_path = Path(__file__).parent.parent / 'window_warning_no_helpers_blueprint.yaml'

def _input_constructor(loader, node):
    # handle scalar, sequence and mapping nodes for !input tags
    if isinstance(node, _yaml.ScalarNode):
        return node.value
    if isinstance(node, _yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, _yaml.MappingNode):
        return loader.construct_mapping(node)

_yaml.SafeLoader.add_constructor('!input', _input_constructor)

with open(bp_path, 'r', encoding='utf-8') as f:
    data = _yaml.safe_load(f)

# Collect all string templates in the YAML
templates = []

def collect(obj, path=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            collect(v, path + '/' + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            collect(v, path + f'[{i}]')
    elif isinstance(obj, str):
        if '{{' in obj or '{%' in obj:
            templates.append((path, obj))

collect(data)

# Mock states and attributes
mock_states = {
    'sensor.indoor_temp': '21.3',
    'binary_sensor.window': 'on',
    'sensor.outside_temp': '19.0',
}
mock_attrs = {
    'binary_sensor.window': {'friendly_name': 'Window Sensor'}
}

# Jinja environment
env = Environment(undefined=StrictUndefined)

# helpers

def states(entity_id):
    return mock_states.get(entity_id, '')

def state_attr(entity_id, attr):
    return mock_attrs.get(entity_id, {}).get(attr)

def is_state(entity_id, value):
    return states(entity_id) == value

def area_name(entity_id):
    return 'Living Room'

def now():
    return datetime.now()

def as_timestamp(dt):
    try:
        return dt.timestamp()
    except Exception:
        return 0

# filters

def to_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        try:
            return float(default)
        except Exception:
            return 0.0

env.globals.update({
    'states': states,
    'state_attr': state_attr,
    'is_state': is_state,
    'area_name': area_name,
    'now': now,
    'as_timestamp': as_timestamp,
})
env.tests['is_number'] = lambda v: True if (v is not None and isinstance(v, (int, float))) or (isinstance(v, str) and v.replace('.', '', 1).isdigit()) else False
env.tests['is_number'] = lambda v: True if (v is not None and isinstance(v, (int, float))) or (isinstance(v, str) and v.replace('.', '', 1).isdigit()) else False
env.filters['is_number'] = lambda v: env.tests['is_number'](v)
env.filters['float'] = to_float

# provide additional mock variables commonly used in templates
mock_repeat = SimpleNamespace(item='notify.test')
env.globals.update({
    'repeat': mock_repeat,
    'area': 'Living Room',
    'warning_reason': 'none',
    'winter_enabled': True,
    'summer_enabled': True,
    'open_too_long_enabled': True,
    'open_minutes': 10.0,
    'inside_temp': 21.3,
    'start_temp': 22.6,
    'min_temp': 20.0,
    'summer_outside_guard_enabled': False,
    'summer_outside_margin': 0.5,
    'winter_temp_threshold': 18.0,
    'rise_from_min': 0.5,
    'outside_guard_ok': True,
    'notification_tag': 'window_warning',
    'notification_clear_service': 'notify.test',
    'notification_title': 'Test title',
    'notification_message': 'Test message',
    'notification_tag_full': 'window_warning_binary_sensor_window',
})

# Render all templates
errors = []
print(f'Found {len(templates)} templates to validate.\n')
for path, tpl in templates:
    try:
        j = env.from_string(tpl)
        rendered = j.render(
            window_entity='binary_sensor.window',
            inside_temp_entity='sensor.indoor_temp',
            outside_temp_entity='sensor.outside_temp',
            open_state_value='on',
            closed_state_value='off',
            notify_services=['notify.test'],
            # provide numeric named vars used in templates to avoid undefined
            start_temp='21.3',
            min_temp='20.0',
            start_ts=as_timestamp(now()),
        )
        print(f'[{path}] OK -> {rendered[:200]!s}')
    except Exception as e:
        errors.append((path, tpl, str(e)))
        print(f'[{path}] ERROR -> {e}')

if errors:
    print('\nSummary: errors encountered in templates:')
    for p, t, err in errors:
        print(f'- {p}: {err}')
    sys.exit(2)
else:
    print('\nAll templates rendered without exceptions (with mock context).')
    sys.exit(0)
