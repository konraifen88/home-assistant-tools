from pathlib import Path
import unittest

import yaml
from jinja2 import Environment, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = ROOT / "window-open-blueprint" / "window_warning_no_helpers_blueprint.yaml"


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


def make_env(states):
    env = Environment(undefined=StrictUndefined)

    def states_func(entity_id):
        return states.get(entity_id, "")

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


def render_bool(template, context, states=None):
    env = make_env(states or {"binary_sensor.window": "on"})
    rendered = env.from_string(template).render(**context).strip()
    return rendered == "True"


def render_string(template, context, states=None):
    env = make_env(states or {"binary_sensor.window": "on"})
    return env.from_string(template).render(**context).strip()


class WindowWarningBlueprintTest(unittest.TestCase):
    def setUp(self):
        self.blueprint = load_blueprint()
        # action[0] = variables, action[1] = dismiss helper reset choose,
        # action[2] = repeat loop, action[3] = clear on close choose
        repeat_sequence = self.blueprint["action"][2]["repeat"]["sequence"]
        # [0] wait_for_trigger, [1] variables (temps), [2] choose (reason),
        # [3] variables (title/msg), [4] choose (notification sending),
        # [5] variables (dismissed_service), [6] variables (dismissed_services),
        # [7] choose (handle dismiss)
        self.reason_choose = repeat_sequence[2]["choose"]
        self.notification_variables = repeat_sequence[3]["variables"]
        # notification sending: choose[0].sequence[0] = repeat for_each notification_targets
        self.notification_repeat = repeat_sequence[4]["choose"][0]["sequence"][0]["repeat"]
        # Inside the repeat, there's a choose (skip dismissed) -> sequence[0] = service call
        self.notification_action = self.notification_repeat["sequence"][0]["choose"][0][
            "sequence"
        ][0]
        self.dismiss_variables = repeat_sequence[5]["variables"]
        self.dismiss_choose = repeat_sequence[7]["choose"]
        self.clear_action = self.blueprint["action"][3]["choose"][0]

    def test_notification_targets_input_uses_device_selector(self):
        """notify_mobile_app_devices uses device selector with mobile_app integration."""
        notification_inputs = self.blueprint["blueprint"]["input"]["notification_settings"]["input"]
        device_input = notification_inputs["notify_mobile_app_devices"]

        self.assertEqual(device_input["selector"]["device"]["integration"], "mobile_app")
        self.assertTrue(device_input["selector"]["device"]["multiple"])

    def test_notification_updates_reuse_tag_and_alert_once(self):
        notify_data = self.notification_action["data"]["data"]

        self.assertEqual(notify_data["tag"], "{{ notification_tag_full }}")
        self.assertIs(notify_data["alert_once"], True)

    def test_notification_includes_dismiss_action_button(self):
        """Notification data includes an action button for dismissing."""
        notify_data = self.notification_action["data"]["data"]

        self.assertIn("actions", notify_data)
        action = notify_data["actions"][0]
        self.assertEqual(action["action"], "DISMISS_NOTIFICATION")
        self.assertEqual(action["title"], "{{ dismissal_action_title }}")
        self.assertIn("action_data", action)
        self.assertEqual(action["action_data"]["tag"], "{{ notification_tag_full }}")
        self.assertEqual(
            action["action_data"]["notify_service"],
            "{{ repeat.item.service | trim }}",
        )

    def test_notification_skips_dismissed_services(self):
        """The notification repeat skips targets that are in dismissed_services."""
        skip_condition = self.notification_repeat["sequence"][0]["choose"][0]
        template = skip_condition["conditions"][0]["value_template"]

        self.assertIn("dismissed_services", template)
        self.assertIn("repeat.item.service", template)

    def test_notification_message_uses_configured_blueprint_messages(self):
        template = self.notification_variables["notification_message"]
        cases = [
            ("winter", "Configured winter text"),
            ("summer", "Configured summer text"),
            ("open_too_long", "Configured open-too-long text"),
        ]

        for warning_reason, expected_message in cases:
            with self.subTest(warning_reason=warning_reason):
                context = base_context(
                    warning_reason=warning_reason,
                    winter_message="Configured winter text",
                    summer_message="Configured summer text",
                    open_too_long_message="Configured open-too-long text",
                )

                self.assertEqual(render_string(template, context), expected_message)

    def test_default_notification_texts_include_room_and_open_minutes(self):
        grouped_inputs = self.blueprint["blueprint"]["input"]
        defaults = [
            grouped_inputs["winter_settings"]["input"],
            grouped_inputs["summer_settings"]["input"],
            grouped_inputs["open_too_long_settings"]["input"],
        ]

        for inputs in defaults:
            title_default = next(
                value["default"]
                for key, value in inputs.items()
                if key.endswith("_title")
            )
            message_default = next(
                value["default"]
                for key, value in inputs.items()
                if key.endswith("_message")
            )

            self.assertEqual(title_default, "[ROOM] Window open")
            self.assertIn("[ROOM]", message_default)
            self.assertIn("[MINUTES]", message_default)

    def test_notification_placeholders_are_rendered(self):
        title_template = self.notification_variables["notification_title"]
        message_template = self.notification_variables["notification_message"]
        context = base_context(
            warning_reason="winter",
            area="Kitchen",
            open_minutes=32.4,
            winter_title="[ROOM] Window open",
            winter_message="[ROOM] has been open for [MINUTES] minutes.",
        )

        self.assertEqual(render_string(title_template, context), "Kitchen Window open")
        self.assertEqual(
            render_string(message_template, context),
            "Kitchen has been open for 32 minutes.",
        )

    def test_closing_window_clears_tagged_mobile_app_notifications(self):
        clear_sequence = self.clear_action["sequence"]
        # [0] = repeat for_each notification_targets (clear each),
        # [1] = choose (optional clear service),
        # [2] = choose (reset dismissed_targets_helper)
        notify_clear = clear_sequence[0]["repeat"]["sequence"][0]
        optional_clear = clear_sequence[1]["choose"][0]["sequence"][0]

        self.assertEqual(
            self.clear_action["conditions"][0]["value_template"].strip(),
            "{{ warning_reason != 'none' }}",
        )
        self.assertEqual(notify_clear["service"], "{{ repeat.item.service | trim }}")
        self.assertEqual(notify_clear["data"]["message"], "clear_notification")
        self.assertEqual(notify_clear["data"]["data"]["tag"], "{{ notification_tag_full }}")
        self.assertEqual(optional_clear["service"], "{{ notification_clear_service }}")
        self.assertEqual(optional_clear["data"]["tag"], "{{ notification_tag_full }}")

    def test_closing_window_resets_dismissed_targets_helper(self):
        """When window closes, dismissed_targets_helper is reset to empty."""
        clear_sequence = self.clear_action["sequence"]
        helper_reset = clear_sequence[2]["choose"][0]

        self.assertIn("dismissed_targets_helper", helper_reset["conditions"][0]["value_template"])
        reset_action = helper_reset["sequence"][0]
        self.assertEqual(reset_action["service"], "input_text.set_value")
        self.assertEqual(reset_action["data"]["value"], "")

    def test_dismiss_clears_notification_for_dismissed_target(self):
        """When a target is dismissed, clear_notification is sent to that target."""
        dismiss_branch = self.dismiss_choose[0]
        self.assertIn("dismissed_service | length > 0", dismiss_branch["conditions"][0]["value_template"])

        clear_service = dismiss_branch["sequence"][0]
        self.assertEqual(clear_service["service"], "{{ dismissed_service | trim }}")
        self.assertEqual(clear_service["data"]["message"], "clear_notification")
        self.assertEqual(clear_service["data"]["data"]["tag"], "{{ notification_tag_full }}")

    def test_all_dismissed_stops_loop(self):
        """When all targets are dismissed, the automation stops."""
        dismiss_branch = self.dismiss_choose[0]
        # The stop action is inside a nested choose checking all targets dismissed
        stop_choose = dismiss_branch["sequence"][2]["choose"][0]
        self.assertIn("dismissed_services_next | length >= notification_targets | length",
                      stop_choose["conditions"][0]["value_template"])
        self.assertIn("stop", stop_choose["sequence"][0])

    def test_wait_for_trigger_includes_dismiss_events(self):
        """wait_for_trigger listens for mobile_app_notification_action dismiss events."""
        repeat_sequence = self.blueprint["action"][2]["repeat"]["sequence"]
        wait_triggers = repeat_sequence[0]["wait_for_trigger"]

        trigger_ids = [t.get("id") for t in wait_triggers]
        self.assertIn("notification_dismissed", trigger_ids)
        self.assertIn("notification_cleared", trigger_ids)

        dismiss_trigger = next(t for t in wait_triggers if t.get("id") == "notification_dismissed")
        self.assertEqual(dismiss_trigger["platform"], "event")
        self.assertEqual(dismiss_trigger["event_type"], "mobile_app_notification_action")
        self.assertEqual(dismiss_trigger["event_data"]["action"], "DISMISS_NOTIFICATION")

    def test_winter_warning_condition_matches_room_below_threshold(self):
        template = self.reason_choose[0]["conditions"][0]["value_template"]
        context = base_context(
            warning_reason="none",
            winter_enabled=True,
            current_temp_raw=17.9,
            winter_temp_threshold=18.0,
        )

        self.assertTrue(render_bool(template, context))

    def test_summer_warning_condition_matches_warming_after_cooling(self):
        template = self.reason_choose[1]["conditions"][0]["value_template"]
        context = base_context(
            warning_reason="none",
            summer_enabled=True,
            open_minutes=45.0,
            summer_min_open_minutes=30.0,
            cooling=1.2,
            summer_min_cooling=1.0,
            rise_from_min=0.6,
            summer_rise_from_min=0.5,
            outside_guard_ok=True,
        )

        self.assertTrue(render_bool(template, context))

    def test_open_too_long_condition_matches_elapsed_time(self):
        template = self.reason_choose[2]["conditions"][0]["value_template"]
        context = base_context(
            warning_reason="none",
            open_too_long_enabled=True,
            open_minutes=31.0,
            open_too_long_minutes=30.0,
        )

        self.assertTrue(render_bool(template, context))

    def test_warning_conditions_do_not_match_after_window_closed(self):
        states = {"binary_sensor.window": "off"}
        context = base_context(
            warning_reason="none",
            winter_enabled=True,
            current_temp_raw=10.0,
            winter_temp_threshold=18.0,
            summer_enabled=True,
            open_minutes=60.0,
            summer_min_open_minutes=30.0,
            cooling=2.0,
            summer_min_cooling=1.0,
            rise_from_min=1.0,
            summer_rise_from_min=0.5,
            outside_guard_ok=True,
            open_too_long_enabled=True,
            open_too_long_minutes=30.0,
        )

        for choose_branch in self.reason_choose:
            template = choose_branch["conditions"][0]["value_template"]
            self.assertFalse(render_bool(template, context, states=states))

    def test_winter_warning_does_not_trigger_when_indoor_temp_unavailable(self):
        """When inside_temp_entity reports unavailable/unknown, current_temp_raw is none
        and the winter warning must not fire."""
        template = self.reason_choose[0]["conditions"][0]["value_template"]
        context = base_context(
            warning_reason="none",
            winter_enabled=True,
            current_temp_raw=None,
            winter_temp_threshold=18.0,
        )

        self.assertFalse(render_bool(template, context))

    def test_winter_warning_resets_when_temp_recovers(self):
        """warning_reason resets to 'none' when temp rises above threshold."""
        template = self.reason_choose[3]["conditions"][0]["value_template"]
        context = base_context(
            warning_reason="winter",
            current_temp_raw=18.5,
            winter_temp_threshold=18.0,
        )
        self.assertTrue(render_bool(template, context))

    def test_winter_warning_does_not_reset_when_still_cold(self):
        """warning_reason stays 'winter' when temp is still at or below threshold."""
        template = self.reason_choose[3]["conditions"][0]["value_template"]
        context = base_context(
            warning_reason="winter",
            current_temp_raw=17.5,
            winter_temp_threshold=18.0,
        )
        self.assertFalse(render_bool(template, context))

    def test_summer_warning_resets_when_rise_drops(self):
        """warning_reason resets to 'none' when rise_from_min drops below threshold."""
        template = self.reason_choose[4]["conditions"][0]["value_template"]
        context = base_context(
            warning_reason="summer",
            rise_from_min=0.3,
            summer_rise_from_min=0.5,
        )
        self.assertTrue(render_bool(template, context))

    def test_summer_warning_does_not_reset_when_still_rising(self):
        """warning_reason stays 'summer' when rise_from_min is still above threshold."""
        template = self.reason_choose[4]["conditions"][0]["value_template"]
        context = base_context(
            warning_reason="summer",
            rise_from_min=0.6,
            summer_rise_from_min=0.5,
        )
        self.assertFalse(render_bool(template, context))


def base_context(**overrides):
    context = {
        "window_entity": "binary_sensor.window",
        "open_state_value": "on",
        "area": "Living Room",
        "warning_reason": "none",
        "winter_enabled": False,
        "current_temp_raw": 21.0,
        "winter_temp_threshold": 18.0,
        "summer_enabled": False,
        "open_minutes": 0.0,
        "summer_min_open_minutes": 30.0,
        "cooling": 0.0,
        "summer_min_cooling": 1.0,
        "rise_from_min": 0.0,
        "summer_rise_from_min": 0.5,
        "outside_guard_ok": False,
        "open_too_long_enabled": False,
        "open_too_long_minutes": 30.0,
    }
    context.update(overrides)
    return context


if __name__ == "__main__":
    unittest.main()
