from pathlib import Path
import unittest

import yaml
from jinja2 import Environment, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = ROOT / "window-open-blueprint" / "window_warning_v2_blueprint.yaml"


def _input_constructor(loader, node):
    if isinstance(node, yaml.ScalarNode):
        return node.value
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    raise TypeError(f"Unsupported !input node: {type(node)!r}")


class BlueprintLoader(yaml.SafeLoader):
    pass


BlueprintLoader.add_constructor("!input", _input_constructor)


def load_blueprint():
    with BLUEPRINT.open(encoding="utf-8") as blueprint_file:
        return yaml.load(blueprint_file, Loader=BlueprintLoader)


def make_env(states=None):
    env = Environment(undefined=StrictUndefined)
    _states = states or {"binary_sensor.window": "on"}

    def states_func(entity_id):
        return _states.get(entity_id, "")

    def is_state(entity_id, value):
        return states_func(entity_id) == value

    env.globals.update(
        {
            "states": states_func,
            "is_state": is_state,
        }
    )
    env.tests["is_number"] = lambda value: _is_number(value)
    return env


def _is_number(value):
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def render_string(template, context, states=None):
    env = make_env(states)
    return env.from_string(template).render(**context).strip()


def render_bool(template, context, states=None):
    rendered = render_string(template, context, states)
    return rendered == "True"


class WindowWarningV2BlueprintTest(unittest.TestCase):
    def setUp(self):
        self.blueprint = load_blueprint()
        self.actions = self.blueprint["action"]
        # action[0] = variables
        # action[1] = weather.get_forecasts (service call)
        # action[2] = variables (forecast processing + mode)
        # action[3] = choose (reset dismissed helper)
        # action[4] = repeat loop
        # action[5] = choose (clear on close)
        self.forecast_variables = self.actions[2]["variables"]
        self.repeat_sequence = self.actions[4]["repeat"]["sequence"]

    def test_blueprint_loads_without_errors(self):
        """The blueprint YAML loads correctly with !input tags."""
        self.assertIn("blueprint", self.blueprint)
        self.assertEqual(self.blueprint["blueprint"]["domain"], "automation")

    def test_all_inputs_have_defaults_except_required(self):
        """Only window_sensor and inside_temp_sensor should be required (no default)."""
        required_inputs = set()
        for group_key, group in self.blueprint["blueprint"]["input"].items():
            if "input" in group:
                for input_key, input_def in group["input"].items():
                    if "default" not in input_def:
                        required_inputs.add(input_key)

        self.assertEqual(
            required_inputs,
            {"window_sensor", "inside_temp_sensor"},
            f"Unexpected required inputs (no default): {required_inputs}",
        )

    def test_mode_determination_summer(self):
        """Forecast temp > summer threshold → mode = summer."""
        template = self.forecast_variables["mode"]
        context = {
            "forecast_temp": 28.0,
            "summer_temp_threshold": 25,
            "winter_temp_threshold": 18,
        }
        self.assertEqual(render_string(template, context), "summer")

    def test_mode_determination_winter(self):
        """Forecast temp < winter threshold → mode = winter."""
        template = self.forecast_variables["mode"]
        context = {
            "forecast_temp": 5.0,
            "summer_temp_threshold": 25,
            "winter_temp_threshold": 18,
        }
        self.assertEqual(render_string(template, context), "winter")

    def test_mode_determination_normal(self):
        """Forecast temp between thresholds → mode = normal."""
        template = self.forecast_variables["mode"]
        context = {
            "forecast_temp": 21.0,
            "summer_temp_threshold": 25,
            "winter_temp_threshold": 18,
        }
        self.assertEqual(render_string(template, context), "normal")

    def test_forecast_uses_tomorrow_after_forecast_hour(self):
        """After forecast_hour, use_tomorrow should be true."""
        template = self.forecast_variables["use_tomorrow"]
        env = make_env()
        # Simulate now().hour >= forecast_hour
        from unittest.mock import MagicMock
        from datetime import datetime

        mock_now = MagicMock(return_value=datetime(2026, 7, 18, 20, 0, 0))
        env.globals["now"] = mock_now
        rendered = env.from_string(template).render(forecast_hour=18).strip()
        self.assertEqual(rendered, "True")

    def test_forecast_uses_today_before_forecast_hour(self):
        """Before forecast_hour, use_tomorrow should be false."""
        template = self.forecast_variables["use_tomorrow"]
        env = make_env()
        from unittest.mock import MagicMock
        from datetime import datetime

        mock_now = MagicMock(return_value=datetime(2026, 7, 18, 10, 0, 0))
        env.globals["now"] = mock_now
        rendered = env.from_string(template).render(forecast_hour=18).strip()
        self.assertEqual(rendered, "False")

    def test_summer_warning_condition(self):
        """Summer warning fires when open long enough and not already active."""
        # Find the summer choose branch in repeat sequence
        warning_choose = self.repeat_sequence[2]["choose"]
        summer_condition = warning_choose[0]["conditions"][0]["value_template"]

        context = {
            "warning_active": False,
            "mode": "summer",
            "current_temp_raw": 22.0,
            "open_minutes": 45.0,
            "summer_min_open_minutes": 30.0,
        }
        self.assertTrue(render_bool(summer_condition, context))

    def test_summer_warning_does_not_fire_before_min_open(self):
        """Summer warning does not fire before minimum open time."""
        warning_choose = self.repeat_sequence[2]["choose"]
        summer_condition = warning_choose[0]["conditions"][0]["value_template"]

        context = {
            "warning_active": False,
            "mode": "summer",
            "current_temp_raw": 22.0,
            "open_minutes": 10.0,
            "summer_min_open_minutes": 30.0,
        }
        self.assertFalse(render_bool(summer_condition, context))

    def test_winter_warning_condition(self):
        """Winter warning fires when room temp is below threshold."""
        warning_choose = self.repeat_sequence[2]["choose"]
        winter_condition = warning_choose[1]["conditions"][0]["value_template"]

        context = {
            "warning_active": False,
            "mode": "winter",
            "current_temp_raw": 16.5,
            "winter_room_temp_threshold": 18.0,
        }
        self.assertTrue(render_bool(winter_condition, context))

    def test_winter_warning_does_not_fire_above_threshold(self):
        """Winter warning does not fire when room temp is above threshold."""
        warning_choose = self.repeat_sequence[2]["choose"]
        winter_condition = warning_choose[1]["conditions"][0]["value_template"]

        context = {
            "warning_active": False,
            "mode": "winter",
            "current_temp_raw": 19.0,
            "winter_room_temp_threshold": 18.0,
        }
        self.assertFalse(render_bool(winter_condition, context))

    def test_normal_warning_condition(self):
        """Normal warning fires when open too long."""
        warning_choose = self.repeat_sequence[2]["choose"]
        normal_condition = warning_choose[2]["conditions"][0]["value_template"]

        context = {
            "warning_active": False,
            "mode": "normal",
            "open_minutes": 35.0,
            "normal_open_minutes": 30.0,
        }
        self.assertTrue(render_bool(normal_condition, context))

    def test_normal_warning_does_not_fire_before_time(self):
        """Normal warning does not fire before configured minutes."""
        warning_choose = self.repeat_sequence[2]["choose"]
        normal_condition = warning_choose[2]["conditions"][0]["value_template"]

        context = {
            "warning_active": False,
            "mode": "normal",
            "open_minutes": 20.0,
            "normal_open_minutes": 30.0,
        }
        self.assertFalse(render_bool(normal_condition, context))

    def test_warning_does_not_retrigger_when_already_active(self):
        """No warning condition fires when warning_active is already true."""
        warning_choose = self.repeat_sequence[2]["choose"]

        for i, branch in enumerate(warning_choose):
            template = branch["conditions"][0]["value_template"]
            context = {
                "warning_active": True,
                "mode": ["summer", "winter", "normal"][i],
                "current_temp_raw": 10.0,
                "open_minutes": 100.0,
                "summer_min_open_minutes": 5.0,
                "winter_room_temp_threshold": 18.0,
                "normal_open_minutes": 5.0,
            }
            with self.subTest(mode=["summer", "winter", "normal"][i]):
                self.assertFalse(render_bool(template, context))

    def test_notification_title_uses_placeholders(self):
        """Notification title replaces [ROOM] and [MINUTES] placeholders."""
        notification_vars = self.repeat_sequence[4]["variables"]
        title_template = notification_vars["notification_title"]

        context = {
            "warning_active": True,
            "mode": "winter",
            "summer_title": "[ROOM] Summer",
            "winter_title": "[ROOM] Window open",
            "normal_title": "[ROOM] Normal",
            "area": "Küche",
            "open_minutes": 42.7,
        }
        rendered = render_string(title_template, context)
        self.assertEqual(rendered, "Küche Window open")

    def test_notification_message_uses_placeholders(self):
        """Notification message replaces [ROOM] and [MINUTES] placeholders."""
        notification_vars = self.repeat_sequence[4]["variables"]
        message_template = notification_vars["notification_message"]

        context = {
            "warning_active": True,
            "mode": "normal",
            "summer_message": "summer msg",
            "winter_message": "winter msg",
            "normal_message": "[ROOM] open for [MINUTES] min",
            "area": "Bad",
            "open_minutes": 31.2,
        }
        rendered = render_string(message_template, context)
        self.assertEqual(rendered, "Bad open for 31 min")

    def test_notification_not_sent_when_warning_inactive(self):
        """Notification title is none when warning is not active."""
        notification_vars = self.repeat_sequence[4]["variables"]
        title_template = notification_vars["notification_title"]

        context = {
            "warning_active": False,
            "mode": "normal",
            "summer_title": "x",
            "winter_title": "x",
            "normal_title": "x",
            "area": "Test",
            "open_minutes": 5.0,
        }
        rendered = render_string(title_template, context)
        self.assertEqual(rendered, "None")

    def test_notification_includes_dismiss_action(self):
        """Notification data includes dismiss action button."""
        # Navigate to the notification sending action
        notification_choose = self.repeat_sequence[5]["choose"][0]
        notify_repeat = notification_choose["sequence"][0]["repeat"]
        notify_action = notify_repeat["sequence"][0]["choose"][0]["sequence"][0]

        notify_data = notify_action["data"]["data"]
        self.assertEqual(notify_data["tag"], "{{ notification_tag_full }}")
        self.assertIs(notify_data["alert_once"], True)
        self.assertIn("actions", notify_data)

        action = notify_data["actions"][0]
        self.assertEqual(action["action"], "DISMISS_NOTIFICATION")
        self.assertEqual(action["title"], "{{ dismissal_action_title }}")

    def test_closing_window_clears_notifications(self):
        """When window closes, clear_notification is sent to all targets."""
        clear_choose = self.actions[5]["choose"][0]
        self.assertIn("warning_active", clear_choose["conditions"][0]["value_template"])

        clear_sequence = clear_choose["sequence"]
        # First action: repeat for_each notification_targets → clear
        clear_repeat = clear_sequence[0]["repeat"]["sequence"][0]
        self.assertEqual(clear_repeat["data"]["message"], "clear_notification")
        self.assertEqual(clear_repeat["data"]["data"]["tag"], "{{ notification_tag_full }}")

    def test_default_notification_texts_include_room_and_minutes(self):
        """All default titles/messages contain [ROOM] and [MINUTES] placeholders."""
        grouped_inputs = self.blueprint["blueprint"]["input"]
        for group_key in ("summer_settings", "winter_settings", "normal_settings"):
            inputs = grouped_inputs[group_key]["input"]
            for key, value in inputs.items():
                if key.endswith("_title"):
                    self.assertIn("[ROOM]", value["default"], f"{key} missing [ROOM]")
                if key.endswith("_message"):
                    self.assertIn("[ROOM]", value["default"], f"{key} missing [ROOM]")
                    self.assertIn("[MINUTES]", value["default"], f"{key} missing [MINUTES]")

    def test_winter_warning_does_not_fire_when_temp_unavailable(self):
        """Winter warning does not fire when current_temp_raw is none."""
        warning_choose = self.repeat_sequence[2]["choose"]
        winter_condition = warning_choose[1]["conditions"][0]["value_template"]

        context = {
            "warning_active": False,
            "mode": "winter",
            "current_temp_raw": None,
            "winter_room_temp_threshold": 18.0,
        }
        self.assertFalse(render_bool(winter_condition, context))


if __name__ == "__main__":
    unittest.main()
